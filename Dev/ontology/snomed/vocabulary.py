from __future__ import annotations

import json
from collections import Counter

from rdflib import Graph, RDF, RDFS, SKOS, Namespace, URIRef

from .models import (ATTRIBUTES, KINDS, OW, ROOT, Evidence, Review, VocabularyEntry,
                     VocabularyResponse, concept_uri, digest)
from .rf2 import ATTRIBUTE_MAP, display_term, normalize, normalize_description


def quote_evidence(description):
    return {"kind": "description", "id": description["id"], "quote": description["term"],
            "start": 0, "end": len(description["term"])}


def seal(value):
    return {**value, "sha256": digest(value)}


def verify_seal(value):
    if value.get("sha256") != digest({key: item for key, item in value.items() if key != "sha256"}):
        raise ValueError("Preparation artifact digest mismatch")


def source_ids(packet):
    candidates = packet.get("candidates", [packet.get("source", {})])
    ids = set()
    for candidate in candidates:
        for key, kind in (("descriptions", "description"), ("relationships", "relationship"), ("concrete", "concrete")):
            ids.update((kind, row["id"]) for row in candidate.get(key, []))
    ids.update(("relationship", row["id"]) for row in packet.get("paths", []))
    return ids


def validate_packets(rf2, envelope):
    verify_seal(envelope)
    if envelope["dataset_id"] != rf2.dataset_id:
        raise ValueError("Packet dataset differs from the imported release")
    ids = [packet["packet_id"] for packet in envelope["packets"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate packet identity")
    for packet in envelope["packets"]:
        for candidate in packet.get("candidates", [packet.get("source", {})]):
            if candidate != rf2.packet(candidate["sctid"]):
                raise ValueError("Packet source differs from its current RF2 rows")
        for row in packet.get("paths", []):
            if rf2.evidence(Evidence(kind="relationship", id=row["id"])) != row:
                raise ValueError("Hierarchy proof differs from RF2")


def entry(rf2, sctid, kind, basis, uri=None, attributes=(), value_attributes=()):
    descriptions = rf2.descriptions(sctid)
    if not descriptions:
        raise ValueError("Vocabulary concepts require active English descriptions")
    label = rf2.label(sctid)
    aliases = sorted({display_term(description) for description in descriptions if display_term(description) != label})
    return VocabularyEntry(sctid=sctid, uri=uri or concept_uri(sctid), kind=kind, label=label,
                           aliases=aliases, attributes=list(attributes), value_attributes=list(value_attributes),
                           evidence=[Evidence.model_validate(quote_evidence(descriptions[0]))], basis=basis).model_dump()


def merge_entry(existing, candidate):
    if existing["kind"] != candidate["kind"] or existing["sctid"] != candidate["sctid"]:
        raise ValueError("Conflicting mappings for the same SNOMED concept")
    merged = dict(existing)
    for field in ("aliases", "attributes", "value_attributes", "methods"):
        merged[field] = sorted(set(existing.get(field, [])) | set(candidate.get(field, [])))
    merged["evidence"] = sorted({json.dumps(proof, sort_keys=True, ensure_ascii=False): proof
                                 for proof in existing["evidence"] + candidate["evidence"]}.values(),
                                key=lambda proof: (proof["kind"], proof["id"]))
    merged["basis"] = " | ".join(sorted(set(existing["basis"].split(" | ")) | set(candidate["basis"].split(" | "))))
    for field in ("context_type", "exam_request_text"):
        if existing.get(field) and candidate.get(field) and existing[field] != candidate[field]:
            raise ValueError(f"Conflicting {field} mappings for the same SNOMED concept")
        if not existing.get(field):
            merged[field] = candidate.get(field)
    return VocabularyEntry.model_validate(merged).model_dump()


def value_candidates(rf2, source_ids, allowed_attributes, entries):
    values = {item["sctid"]: {"sctid": item["sctid"], "label": item["label"],
                              "aliases": item["aliases"], "attributes": item["value_attributes"]}
              for item in entries.values() if item["kind"] == "AttributeValue" and
              allowed_attributes.intersection(item["value_attributes"])}
    raw_attributes = {}
    for source_id in source_ids:
        for relation in rf2.relationships(source_id):
            attribute = ATTRIBUTE_MAP.get(relation["typeId"])
            if attribute in allowed_attributes:
                raw_attributes.setdefault(relation["destinationId"], set()).add(attribute)
    for sctid, attributes in raw_attributes.items():
        descriptions = rf2.descriptions(sctid)
        if not descriptions:
            continue
        values.setdefault(sctid, {"sctid": sctid, "label": rf2.label(sctid),
                                   "aliases": sorted({display_term(row) for row in descriptions
                                                      if display_term(row) != rf2.label(sctid)}),
                                   "attributes": sorted(attributes)})
        values[sctid]["attributes"] = sorted(set(values[sctid]["attributes"]) | attributes)
    return sorted(values.values(), key=lambda item: item["sctid"])


def expand_vocabulary(rf2, seeds=None, previous=None):
    if seeds is None:
        from ..vocabulary import load_vocabulary
        seeds = load_vocabulary()["terms"]
    graph = Graph().parse(ROOT / "data/ontology/schema.ttl").parse(ROOT / "data/ontology/vocabulary.ttl")
    ow = Namespace(OW)
    known = {}
    for kind in KINDS:
        for node in graph.subjects(RDF.type, ow[kind]):
            for predicate in (RDFS.label, SKOS.altLabel):
                for label in graph.objects(node, predicate):
                    if label.language == "en":
                        known[(kind, normalize(str(label)))] = str(node)
    entries, packets, excluded, decompositions = {}, [], [], []
    if previous is not None:
        verify_seal(previous)
        if previous["dataset_id"] != rf2.dataset_id or previous.get("stage") != "vocabulary_validated":
            raise ValueError("Follow-up expansion requires validated candidates from this RF2 release")
        entries = {item["sctid"]: dict(item) for item in previous["entries"]}
        excluded = list(previous["excluded"])
        decompositions = list(previous["decompositions"])
        seeds = {}
    for kind in KINDS:
        for term in (seeds or {}).get(kind, []):
            candidates = rf2.search(term)
            exact = [cid for cid in candidates if any(normalize_description(d) == normalize(term) for d in rf2.descriptions(cid))]
            if len(exact) == 1 and (exact[0] not in entries or entries[exact[0]]["kind"] == kind):
                cid = exact[0]
                uri = known.get((kind, normalize(term)))
                attrs = [str(value).removeprefix(OW) for value in graph.objects(URIRef(uri), ow.hasAttribute)] if uri else []
                value_attrs = [str(attr).removeprefix(OW) for attr in graph.subjects(ow.canHaveValue, URIRef(uri))] if uri else []
                entries.setdefault(cid, entry(rf2, cid, kind, "approved_seed_exact_match", uri, attrs, value_attrs))
                node = URIRef(entries[cid]["uri"])
                entries[cid]["context_type"] = next((str(v) for v in graph.objects(node, ow.contextType)), None)
                entries[cid]["exam_request_text"] = next((str(v) for v in graph.objects(node, ow.examRequestText)), None)
            elif candidates:
                packets.append({"packet_id": "Seed" + digest([kind, term])[:24], "purpose": "seed_mapping", "seed_kind": kind,
                                "seed_term": term, "seed_uri": known.get((kind, normalize(term))),
                                "allowed_kinds": [kind], "candidates": [rf2.packet(cid) for cid in candidates], "paths": []})
            else:
                excluded.append({"kind": kind, "term": term, "reason": "no_local_candidate"})
    by_uri = {v["uri"]: cid for cid, v in entries.items()}
    for item in entries.values():
        item["methods"] = [by_uri[str(m)] for m in graph.objects(URIRef(item["uri"]), ow.detectedBy) if str(m) in by_uri]
    already_decided = set(entries)
    already_decided.update(item["sctid"] for item in decompositions)
    already_decided.update(item["sctid"] for item in excluded if item.get("sctid"))
    roots = set(entries)
    for packet in packets:
        if packet.get("purpose") == "seed_mapping":
            target_candidates = []
            attributes = set()
            for target_id, item in entries.items():
                if item["kind"] not in {"Symptom", "ExamFinding"}:
                    continue
                if any(rf2.path(candidate["sctid"], target_id) is not None for candidate in packet["candidates"]):
                    target_candidates.append({"sctid": target_id, "kind": item["kind"], "label": item["label"],
                                              "attributes": item["attributes"]})
                    attributes.update(item["attributes"])
            packet["candidate_targets"] = sorted(target_candidates, key=lambda item: item["sctid"])
            packet["candidate_values"] = value_candidates(rf2,
                [candidate["sctid"] for candidate in packet["candidates"]], attributes, entries)
            packet["possible_value_attributes"] = sorted(set(ATTRIBUTE_MAP.values()))
            packet["attribute_mappings"] = dict(ATTRIBUTE_MAP)
    discovered = rf2.descendants(roots)
    value_context = {}
    for cid in discovered:
        for relation in rf2.relationships(cid):
            if relation["typeId"] in ATTRIBUTE_MAP:
                value_context.setdefault(relation["destinationId"], set()).add(ATTRIBUTE_MAP[relation["typeId"]])
    for cid in sorted(set(discovered) | set(value_context)):
        if cid in already_decided:
            continue
        paths, possible = [], set()
        for root in sorted(roots):
            route = rf2.path(cid, root)
            if route is not None:
                possible.add(entries[root]["kind"])
                paths.extend(route)
        if cid in value_context:
            possible.add("AttributeValue")
        candidate_targets = []
        candidate_attributes = set()
        for target_id, item in entries.items():
            if item["kind"] not in {"Symptom", "ExamFinding"} or rf2.path(cid, target_id) is None:
                continue
            candidate_targets.append({"sctid": target_id, "kind": item["kind"], "label": item["label"],
                                      "attributes": item["attributes"]})
            candidate_attributes.update(item["attributes"])
        candidate_values = value_candidates(rf2, [cid], candidate_attributes, entries)
        packets.append({"packet_id": "Concept" + cid, "purpose": "expansion", "allowed_kinds": sorted(possible),
                        "candidates": [rf2.packet(cid)], "paths": sorted({r["id"]: r for r in paths}.values(), key=lambda r: r["id"]),
                        "possible_value_attributes": sorted(value_context.get(cid, [])),
                        "attribute_mappings": dict(ATTRIBUTE_MAP),
                        "candidate_targets": sorted(candidate_targets, key=lambda item: item["sctid"]),
                        "candidate_values": sorted(candidate_values, key=lambda item: item["sctid"])})
    return seal({"version": 1, "stage": "vocabulary", "dataset_id": rf2.dataset_id,
                 "seed_sha256": digest(seeds), "entries": sorted(entries.values(), key=lambda e: e["sctid"]),
                 "decompositions": decompositions, "packets": sorted(packets, key=lambda p: p["packet_id"]), "excluded": excluded})


def validate_vocabulary(rf2, expansion, raw):
    validate_packets(rf2, expansion)
    response = VocabularyResponse.model_validate(raw)
    packets = {p["packet_id"]: p for p in expansion["packets"]}
    returned = [d.packet_id for d in response.decisions]
    if len(returned) != len(set(returned)) or set(returned) != set(packets):
        raise ValueError("Require exactly one decision for every vocabulary packet")
    entries = {e["sctid"]: dict(e) for e in expansion["entries"]}
    decompositions, excluded = list(expansion["decompositions"]), list(expansion["excluded"])
    pending_decompositions = []
    for decision in response.decisions:
        packet = packets[decision.packet_id]
        allowed = source_ids(packet)
        if decision.decision == "exclude":
            if (decision.sctid not in {c["sctid"] for c in packet["candidates"]} or decision.kind is not None or
                    decision.target_id is not None or decision.qualifications or decision.attributes or decision.value_attributes or
                    not decision.evidence):
                raise ValueError("Excluded decisions cannot emit vocabulary")
            for proof in decision.evidence:
                rf2.evidence(proof, allowed)
            if not any(proof.kind == "description" and rf2.evidence(proof)["conceptId"] == decision.sctid for proof in decision.evidence):
                raise ValueError("Exclusions need a description of the selected concept")
            excluded.append({"packet_id": decision.packet_id, "sctid": decision.sctid, "reason": decision.reason})
            continue
        ids = {c["sctid"] for c in packet["candidates"]}
        if decision.sctid not in ids or decision.kind not in packet["allowed_kinds"] or not decision.evidence:
            raise ValueError(f"Mapping for {decision.packet_id} must select an offered concept and type "
                             f"with evidence (selected={decision.sctid}/{decision.kind}, "
                             f"allowed={sorted(packet['allowed_kinds'])})")
        for proof in decision.evidence:
            rf2.evidence(proof, allowed)
        if not any(proof.kind == "description" and rf2.evidence(proof)["conceptId"] == decision.sctid for proof in decision.evidence):
            raise ValueError("Mapping needs a description of the selected concept")
        if decision.decision == "decompose":
            pending_decompositions.append((decision, packet, allowed))
        else:
            if decision.target_id is not None or decision.qualifications:
                raise ValueError("A compound decomposition cannot be a vocabulary alias")
            if decision.kind != "AttributeValue" and decision.value_attributes:
                raise ValueError("Only categorical values have value attributes")
            if decision.kind not in {"Symptom", "ExamFinding"} and decision.attributes:
                raise ValueError("Only finding targets have applicability attributes")
            uri = packet.get("seed_uri")
            item = entry(rf2, decision.sctid, decision.kind, decision.reason, uri, decision.attributes, decision.value_attributes)
            item["evidence"] = [p.model_dump() for p in decision.evidence]
            if item["sctid"] in entries:
                entries[item["sctid"]] = merge_entry(entries[item["sctid"]], item)
            else:
                entries[item["sctid"]] = item
    for decision, packet, allowed in pending_decompositions:
        target = entries.get(decision.target_id)
        if target is None or target["kind"] not in {"Symptom", "ExamFinding"} or rf2.path(decision.sctid, decision.target_id) is None:
            raise ValueError("Decomposition requires a mapped target ancestor")
        if decision.target_id not in {item["sctid"] for item in packet.get("candidate_targets", [])}:
            raise ValueError("Decomposition target was not offered in the source packet")
        for q in decision.qualifications:
            value = entries.get(q.value_id)
            if value is None or value["kind"] != "AttributeValue" or q.attribute not in value["value_attributes"] or q.attribute not in target["attributes"]:
                raise ValueError("Decomposition value is not mapped for this target attribute")
            if q.value_id not in {item["sctid"] for item in packet.get("candidate_values", [])}:
                raise ValueError("Decomposition value was not offered in the source packet")
            for proof in q.evidence:
                row = rf2.evidence(proof, allowed)
                if proof.kind == "description" and row["conceptId"] != decision.sctid:
                    raise ValueError("A qualifier description must describe the decomposed source concept")
                if proof.kind == "relationship" and (row["sourceId"] != decision.sctid or ATTRIBUTE_MAP.get(row["typeId"]) != q.attribute or row["destinationId"] != q.value_id):
                    raise ValueError("Qualification relationship has the wrong subject or value")
        if decision.kind != target["kind"]:
            raise ValueError("A decomposed concept must retain its reviewed target type")
        decompositions.append({"packet_id": decision.packet_id, "sctid": decision.sctid, "target_id": decision.target_id,
                               "qualifications": [q.model_dump() for q in decision.qualifications],
                               "evidence": [p.model_dump() for p in decision.evidence]})
    return seal({"version": 1, "stage": "vocabulary_validated", "dataset_id": rf2.dataset_id,
                 "input_sha256": expansion["sha256"], "entries": sorted(entries.values(), key=lambda e: e["sctid"]),
                 "decompositions": sorted(decompositions, key=lambda d: d["packet_id"]), "excluded": excluded,
                 "clinical_review": "not_run", "runtime_admission": "not_run"})


def freeze_vocabulary(rf2, candidates, raw_review):
    verify_seal(candidates)
    review = Review.model_validate(raw_review)
    if review.input_sha256 != candidates["sha256"] or not review.reviewer.strip() or candidates["dataset_id"] != rf2.dataset_id:
        raise ValueError("Review must identify the exact vocabulary and reviewer")
    by_id = {e["sctid"]: e for e in candidates["entries"]}
    accepted, excluded = set(review.accepted_sctids), set(review.excluded_sctids)
    if len(accepted) != len(review.accepted_sctids) or len(excluded) != len(review.excluded_sctids) or accepted & excluded or accepted | excluded != set(by_id):
        raise ValueError("Review must partition every vocabulary candidate")
    if not set(review.metadata) <= accepted:
        raise ValueError("Review metadata must refer to selected concepts")
    entries = []
    for cid in sorted(accepted):
        metadata = review.metadata.get(cid, {})
        if not set(metadata) <= {"attributes", "value_attributes", "context_type", "methods", "exam_request_text"}:
            raise ValueError("Review cannot alter source identity or labels")
        item = VocabularyEntry.model_validate({**by_id[cid], **metadata})
        item = item.model_copy(update={"review_status": "selected"})
        if not rf2.active(cid) or item.uri not in {by_id[cid]["uri"], concept_uri(cid)}:
            raise ValueError("Invalid selected concept")
        for proof in item.evidence:
            rf2.evidence(proof)
        if not set(item.methods) <= accepted or any(by_id[m]["kind"] != "ExamMethod" for m in item.methods):
            raise ValueError("Finding methods must be selected ExamMethod concepts")
        entries.append(item.model_dump())
    if len({e["uri"] for e in entries}) != len(entries):
        raise ValueError("Vocabulary URI collision")
    decomposition_ids = [d["packet_id"] for d in candidates["decompositions"]]
    if len(set(review.accepted_decompositions)) != len(review.accepted_decompositions) or not set(review.accepted_decompositions) <= set(decomposition_ids):
        raise ValueError("Unknown or duplicate reviewed decomposition")
    decompositions = [d for d in candidates["decompositions"] if d["packet_id"] in review.accepted_decompositions]
    for decomposition in decompositions:
        if decomposition["target_id"] not in accepted or any(q["value_id"] not in accepted for q in decomposition["qualifications"]):
            raise ValueError("Decomposition references excluded vocabulary")
    return seal({"version": 1, "stage": "vocabulary_frozen", "dataset_id": rf2.dataset_id,
                 "input_sha256": candidates["sha256"], "review": review.model_dump(), "entries": entries,
                 "decompositions": decompositions, "counts": dict(Counter(e["kind"] for e in entries)),
                 "runtime_admission": "not_run"})


def require_registry(rf2, registry):
    verify_seal(registry)
    if registry["stage"] != "vocabulary_frozen" or registry["dataset_id"] != rf2.dataset_id:
        raise ValueError("Require a reviewed vocabulary from this release")
    entries = {item["sctid"]: VocabularyEntry.model_validate(item).model_dump() for item in registry["entries"]}
    if len(entries) != len(registry["entries"]) or any(not rf2.active(cid) for cid in entries):
        raise ValueError("Invalid frozen vocabulary identities")
    if any(item["review_status"] != "selected" for item in entries.values()):
        raise ValueError("Every registry entry must have an explicit selected review status")
    return entries
