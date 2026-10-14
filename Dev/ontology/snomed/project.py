from __future__ import annotations

from collections import Counter, defaultdict
import re
import unicodedata

from rdflib import Graph, Literal, Namespace, RDF, RDFS, SKOS, URIRef, XSD

from .models import Evidence, Feature, OW, ROOT, ProjectionResponse, digest, write, workspace_path
from .rf2 import ATTRIBUTE_MAP, ASSOCIATED_WITH, DUE_TO, FINDING_METHOD, IS_A
from .vocabulary import require_registry, seal, source_ids, validate_packets, verify_seal


def feature_key(feature):
    return (feature.get("attribute") or "", feature.get("value_id") or "", feature.get("expected_status") or "")


def unique_features(features):
    grouped = {}
    for feature in features:
        key = feature_key(feature)
        if key not in grouped:
            grouped[key] = {**feature, "evidence": []}
        grouped[key]["evidence"].extend(feature["evidence"])
    for feature in grouped.values():
        feature["evidence"] = sorted({digest(e): e for e in feature["evidence"]}.values(), key=digest)
    return [grouped[key] for key in sorted(grouped)]


def project(rf2, registry):
    entries = require_registry(rf2, registry)
    targets = {cid: e for cid, e in entries.items() if e["kind"] in {"Symptom", "ExamFinding"}}
    diseases = {cid: e for cid, e in entries.items() if e["kind"] == "Disease"}
    decomposed = defaultdict(list)
    for item in registry["decompositions"]:
        decomposed[(item["sctid"], item["target_id"])].extend(item["qualifications"])
    packets = []
    for cid in rf2.descendants(targets):
        target_paths = {tid: rf2.path(cid, tid) for tid in targets}
        target_paths = {tid: route for tid, route in target_paths.items() if route is not None}
        # Prefer the most specific reviewed target; keep unrelated target branches separate.
        target_paths = {tid: route for tid, route in target_paths.items()
                        if not any(other != tid and rf2.path(other, tid) is not None for other in target_paths)}
        source = rf2.packet(cid)
        for tid, target_path in sorted(target_paths.items()):
            links = []
            for relation in source["relationships"]:
                if relation["typeId"] not in {DUE_TO, ASSOCIATED_WITH}:
                    continue
                for did in diseases:
                    disease_path = rf2.path(relation["destinationId"], did)
                    if disease_path is not None:
                        links.append((did, "due_to" if relation["typeId"] == DUE_TO else "associated_with",
                                      [relation, *disease_path], "exact" if relation["destinationId"] == did else "descendant",
                                      relation["destinationId"]))
            for did in diseases:
                route = rf2.path(cid, did)
                if route is not None and cid != did:
                    links.append((did, "subtype_intersection", route, "descendant", did))
            for did, basis, link_path, scope, source_disease_id in links:
                paths = sorted({r["id"]: r for r in [*target_path, *link_path]}.values(), key=lambda r: r["id"])
                features = []
                for relation in source["relationships"]:
                    attribute = ATTRIBUTE_MAP.get(relation["typeId"])
                    value = entries.get(relation["destinationId"])
                    if attribute in targets[tid]["attributes"] and value and value["kind"] == "AttributeValue" and attribute in value["value_attributes"]:
                        features.append({"attribute": attribute, "value_id": value["sctid"], "expected_status": None,
                                         "evidence": [{"kind": "relationship", "id": relation["id"], "quote": None, "start": None, "end": None}]})
                for q in decomposed[(cid, tid)]:
                    features.append({**q, "expected_status": None})
                identity = [rf2.dataset_id, registry["sha256"], cid, did, tid, basis, source_disease_id]
                disease, target = diseases[did], targets[tid]
                packets.append({"packet_id": "Pattern" + digest(identity)[:24], "source": source, "paths": paths,
                                "disease_id": did, "target_id": tid, "source_disease_id": source_disease_id,
                                "derivation_scope": scope,
                                "disease": {"sctid": did, "label": disease["label"], "kind": disease["kind"]},
                                "target": {"sctid": tid, "label": target["label"], "kind": target["kind"]},
                                "relation_basis": basis, "characteristic": basis == "due_to",
                                "allowed_attributes": targets[tid]["attributes"],
                                "allowed_values": {attr: sorted([{"sctid": e["sctid"], "label": e["label"], "aliases": e["aliases"]}
                                                                 for e in entries.values() if e["kind"] == "AttributeValue" and attr in e["value_attributes"]],
                                                                key=lambda item: item["sctid"])
                                                   for attr in targets[tid]["attributes"]},
                                "deterministic_features": unique_features(features),
                                "required_relation_ids": sorted(r["id"] for r in source["relationships"]
                                                                 if r["typeId"] not in {IS_A, DUE_TO, ASSOCIATED_WITH}),
                                "concrete_values": source["concrete"]})
    return seal({"version": 1, "stage": "projection", "dataset_id": rf2.dataset_id, "registry_sha256": registry["sha256"],
                 "packets": sorted(packets, key=lambda p: p["packet_id"])})


def validate_projection(rf2, registry, envelope, raw):
    entries = require_registry(rf2, registry)
    validate_packets(rf2, envelope)
    if envelope["registry_sha256"] != registry["sha256"]:
        raise ValueError("Projection uses another vocabulary registry")
    canonical = project(rf2, registry)
    if envelope != canonical:
        raise ValueError("Pattern linkage or allowed vocabulary differs from the deterministic projection")
    response = ProjectionResponse.model_validate(raw)
    packets = {p["packet_id"]: p for p in envelope["packets"]}
    ids = [d.packet_id for d in response.decisions]
    if len(ids) != len(set(ids)) or set(ids) != set(packets):
        raise ValueError("Require exactly one disposition for every projection packet")
    profiles, excluded = [], []
    for decision in response.decisions:
        packet = packets[decision.packet_id]
        allowed = source_ids(packet)
        for proof in [*decision.profile_evidence, *decision.unrepresentable]:
            rf2.evidence(proof, allowed)
        if decision.decision != "accept":
            if decision.features:
                raise ValueError("Excluded or unresolved profiles cannot emit features")
            excluded.append({"packet_id": decision.packet_id, "decision": decision.decision,
                             "reason": decision.reason, "unrepresentable": [e.model_dump() for e in decision.unrepresentable],
                             "concrete_values": packet["concrete_values"]})
            continue
        if decision.profile == "unresolved" or decision.unrepresentable or packet["concrete_values"]:
            raise ValueError("An unrepresentable or unresolved condition cannot be silently discarded")
        if decision.profile == "distinct" and not decision.profile_evidence:
            raise ValueError("A distinct profile needs explicit source evidence")
        features = list(packet["deterministic_features"])
        represented = {proof["id"] for feature in features for proof in feature["evidence"] if proof["kind"] == "relationship"}
        for feature in decision.features:
            allowed_values = {item["sctid"] if isinstance(item, dict) else item for item in packet["allowed_values"].get(feature.attribute, [])}
            if feature.attribute and (feature.attribute not in packet["allowed_attributes"] or feature.value_id not in allowed_values):
                raise ValueError("Feature does not use the target's reviewed attribute/value combination")
            for proof in feature.evidence:
                row = rf2.evidence(proof, allowed)
                if proof.kind == "description" and row["conceptId"] != packet["source"]["sctid"]:
                    raise ValueError("A modifier must describe the source finding")
                if proof.kind == "relationship":
                    if row["sourceId"] != packet["source"]["sctid"] or ATTRIBUTE_MAP.get(row["typeId"]) != feature.attribute or row["destinationId"] != feature.value_id or feature.expected_status is not None:
                        raise ValueError("Relationship does not ground this atomic feature")
                    represented.add(proof.id)
                if proof.kind == "concrete":
                    raise ValueError("Concrete quantities cannot become categorical features")
            features.append(feature.model_dump())
        if not set(packet["required_relation_ids"]) <= represented:
            raise ValueError("Every source defining relationship must be represented or the whole profile excluded")
        profiles.append({"packet_id": decision.packet_id, "disease_id": packet["disease_id"], "target_id": packet["target_id"],
                         "source_concept_id": packet["source"]["sctid"], "relation_basis": packet["relation_basis"],
                         "derivation_scope": packet["derivation_scope"], "characteristic": packet["characteristic"],
                         "profile": decision.profile, "profile_evidence": [p.model_dump() for p in decision.profile_evidence],
                         "features": unique_features(features), "paths": packet["paths"],
                         "source_groups": sorted({(r["sourceId"], r["relationshipGroup"]) for r in packet["source"]["relationships"]}),
                         "reason": decision.reason})
    return seal({"version": 1, "stage": "projection_validated", "dataset_id": rf2.dataset_id,
                 "registry_sha256": registry["sha256"], "input_sha256": envelope["sha256"], "profiles": profiles,
                 "excluded": excluded, "clinical_review": "not_run", "runtime_admission": "not_run"})


def incompatible(left, right):
    a, b = defaultdict(set), defaultdict(set)
    for item, target in ((left, a), (right, b)):
        for feature in item["features"]:
            key = feature["attribute"] or "status"
            target[key].add(feature["value_id"] or feature["expected_status"])
    return any(a[key] != b[key] for key in a.keys() & b.keys())


def merge_profiles(profiles):
    pairs = defaultdict(list)
    for profile in profiles:
        pairs[(profile["disease_id"], profile["target_id"])].append(profile)
    output = []
    for pair, items in sorted(pairs.items()):
        buckets = defaultdict(list)
        for item in items:
            signature = sorted(feature_key(f) for f in item["features"])
            explicit = digest([signature, item["profile_evidence"]]) if item["profile"] == "distinct" else "compatible"
            buckets[(item["characteristic"], explicit)].append(item)
        groups = []
        for (importance, explicit), members in sorted(buckets.items()):
            if explicit == "compatible" and any(incompatible(a, b) for a in members for b in members):
                alternatives = defaultdict(list)
                for member in members:
                    alternatives[digest(sorted(feature_key(f) for f in member["features"]))].append(member)
                groups.extend(alternatives.values())
            else:
                groups.append(members)
        merged = []
        for members in groups:
            features = unique_features([f for m in members for f in m["features"]])
            signature = [members[0]["characteristic"], sorted(feature_key(f) for f in features),
                         sorted({digest(m["profile_evidence"]) for m in members if m["profile"] == "distinct"})]
            merged.append({"disease_id": pair[0], "target_id": pair[1], "characteristic": members[0]["characteristic"],
                           "features": features, "sources": sorted(members, key=lambda m: m["packet_id"]), "profile_hash": digest(signature)})
        base = OW + "ClinicalPattern" + digest(pair)[:24]
        for index, item in enumerate(sorted(merged, key=lambda m: m["profile_hash"])):
            item["uri"] = base if index == 0 else base + "Variant" + item["profile_hash"][:24]
            output.append(item)
    return output


def export_preview(rf2, registry, validated, output_dir):
    entries = require_registry(rf2, registry)
    verify_seal(validated)
    if validated["stage"] != "projection_validated" or validated["registry_sha256"] != registry["sha256"] or validated["dataset_id"] != rf2.dataset_id:
        raise ValueError("Require validated profiles from the frozen registry")
    output_dir = workspace_path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Preview output must be a new or empty directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    ow = Namespace(OW)
    schema = (ROOT / "data/ontology/schema.ttl").read_bytes()
    vocabulary, graph = Graph(), Graph()
    vocabulary.bind("ow", ow)
    graph.bind("ow", ow)
    patterns, exclusions = [], list(validated["excluded"])
    used = set()
    for pattern in merge_profiles(validated["profiles"]):
        finding = entries[pattern["target_id"]]
        if finding["kind"] == "ExamFinding" and (not finding["methods"] or any(not entries[m]["exam_request_text"] for m in finding["methods"])):
            exclusions.append({"pattern": pattern["uri"], "reason": "exam_method_or_reviewed_request_missing"})
            continue
        patterns.append(pattern)
        used.update([pattern["disease_id"], pattern["target_id"], *finding["methods"]])
        node = URIRef(pattern["uri"])
        graph.add((node, RDF.type, ow.ClinicalPattern))
        graph.add((URIRef(entries[pattern["disease_id"]]["uri"]), ow.hasPattern, node))
        graph.add((node, ow.targets, URIRef(finding["uri"])))
        if pattern["characteristic"]:
            graph.add((node, ow.importance, Literal("characteristic")))
        for feature in pattern["features"]:
            Feature.model_validate(feature)
            feature_node = URIRef(OW + "ClinicalFeature" + digest([pattern["uri"], feature_key(feature)])[:24])
            graph.add((feature_node, RDF.type, ow.ClinicalFeature))
            graph.add((node, ow.hasFeature, feature_node))
            if feature["attribute"]:
                value = entries[feature["value_id"]]
                used.add(value["sctid"])
                graph.add((feature_node, ow.onAttribute, ow[feature["attribute"]]))
                graph.add((feature_node, ow.expectsValue, URIRef(value["uri"])))
            if feature["expected_status"]:
                graph.add((feature_node, ow.expectedStatus, Literal(feature["expected_status"])))
    for cid in sorted(used):
        item, node = entries[cid], URIRef(entries[cid]["uri"])
        vocabulary.add((node, RDF.type, ow[item["kind"]]))
        vocabulary.add((node, RDFS.label, Literal(item["label"], lang="en")))
        for alias in item["aliases"]:
            vocabulary.add((node, SKOS.altLabel, Literal(alias, lang="en")))
        for attr in item["attributes"]:
            vocabulary.add((node, ow.hasAttribute, ow[attr]))
        for attr in item["value_attributes"]:
            vocabulary.add((ow[attr], ow.canHaveValue, node))
        for method in item["methods"]:
            vocabulary.add((node, ow.detectedBy, URIRef(entries[method]["uri"])))
        if item["kind"] == "ExamMethod":
            text = unicodedata.normalize("NFC", item["exam_request_text"] or "")
            if not 1 <= len(text) <= 30:
                raise ValueError("Reviewed EXAM text must contain 1-30 NFC code points")
            vocabulary.add((node, ow.examRequestText, Literal(text, datatype=XSD.string)))
    (output_dir / "schema.ttl").write_bytes(schema)
    # Sorted N-Triples is also valid Turtle and gives repeatable bytes without blank nodes.
    for name, content in (("vocabulary.ttl", vocabulary), ("clinical.ttl", graph)):
        lines = sorted(f"{s.n3()} {p.n3()} {o.n3()} .\n" for s, p, o in content)
        (output_dir / name).write_text("".join(lines), encoding="utf-8")
    assets = {name: {"path": "knowledge/" + name, "sha256": digest((output_dir / name).read_bytes())}
              for name in ("schema.ttl", "vocabulary.ttl", "clinical.ttl")}
    report = {"status": "preview_only", "dataset_id": rf2.dataset_id, "registry_sha256": registry["sha256"],
              "vocabulary_counts": dict(Counter(e["kind"] for e in entries.values())),
              "patterns": len(patterns), "variants": sum("Variant" in p["uri"] for p in patterns),
              "patterns_with_features": sum(bool(p["features"]) for p in patterns),
              "feature_pattern_ratio": sum(bool(p["features"]) for p in patterns) / len(patterns) if patterns else 0,
              "targets_per_disease": {did: len({p["target_id"] for p in patterns if p["disease_id"] == did}) for did in sorted({p["disease_id"] for p in patterns})},
              "source_paths": dict(Counter(s["relation_basis"] for p in patterns for s in p["sources"])),
              "excluded": exclusions, "clinical_review": "not_run", "runtime_admission": "not_run", "model_calls": "see_call_ledger"}
    write(output_dir / "manifest.json", {"schema": assets["schema.ttl"], "vocabulary": assets["vocabulary.ttl"], "bundles": [assets["clinical.ttl"]],
                                         "preparation_status": "preview_only", "dataset_id": rf2.dataset_id})
    write(output_dir / "sources.json", {"patterns": patterns, "excluded": exclusions})
    write(output_dir / "report.json", report)
    return report
