from __future__ import annotations

import json
import hashlib
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, SKOS, URIRef

from submission.knowledge.conditions import ExpectedValue, ScoringPolicy
from .contributions import feature_contributions

ROOT = Path(__file__).resolve().parents[2]

OW = Namespace("urn:ontoward:")
NORMALIZATION_VERSION = "v5.0.4-source-findings"


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def workspace_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Preparation paths must stay inside the workspace")
    return path


def write(path, value):
    path = workspace_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for chunk in json.JSONEncoder(indent=2, ensure_ascii=False, sort_keys=True).iterencode(value):
            stream.write(chunk)
        stream.write("\n")
    temporary.replace(path)


def write_sources(path, assertions, dispositions):
    if hasattr(dispositions, 'database'):
        write(path, dispositions.database.audit_reference())
        return
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write('{"assertions":{')
        separator = ""
        for key in sorted(assertions):
            stream.write(separator + json.dumps(key) + ":")
            for chunk in json.JSONEncoder(ensure_ascii=False, sort_keys=True).iterencode(assertions[key]):
                stream.write(chunk)
            separator = ","
        stream.write('},"dispositions":[')
        separator = ""
        for record in dispositions:
            stream.write(separator + json.dumps(record, ensure_ascii=False, sort_keys=True))
            separator = ","
        stream.write("]}\n")
    temporary.replace(path)


def condition_signature(feature):
    return (feature.get("attribute") or "", ExpectedValue.model_validate(feature["expected"]).signature()
            if feature.get("expected") else "", feature.get("status") or "")


class PreviewBuilder:
    def __init__(self):
        self.vocabulary, self.graph = Graph(), Graph()
        self.assertions = {}
        self.selected = {}
        self.registry = {}
        self.conflicts = set()

    def concept(self, uri, kind, label, *, korean=None, aliases=(), snomed_id=None, source_refs=()):
        node = URIRef(uri)
        self.vocabulary.add((node, RDF.type, OW[kind]))
        self.vocabulary.add((node, RDFS.label, Literal(label, lang="en")))
        if korean:
            self.vocabulary.add((node, RDFS.label, Literal(korean, lang="ko")))
        for alias in aliases:
            self.vocabulary.add((node, SKOS.altLabel, Literal(alias, lang="en")))
        previous = self.registry.get(uri, {})
        if previous and (previous["kind"] != kind or
                         previous.get("snomed_id") not in {None, snomed_id}):
            raise ValueError("Conflicting concept role or SNOMED mapping")
        self.registry[uri] = {**previous, "uri": uri, "kind": kind, "label": label,
                              "snomed_id": snomed_id or previous.get("snomed_id"),
                              "source_refs": sorted(set(source_refs) | set(previous.get("source_refs", []))),
                              "review_status": "candidate"}
        return node

    def feature(self, pattern, payload):
        signature = condition_signature(payload)
        feature = URIRef(str(OW) + "ClinicalFeature" + digest([str(pattern), signature])[:24])
        self.graph.add((pattern, OW.hasFeature, feature))
        self.graph.add((feature, RDF.type, OW.ClinicalFeature))
        if payload.get("status"):
            self.graph.add((feature, OW.expectedStatus, Literal(payload["status"])))
        if payload.get("attribute"):
            attribute = URIRef(payload["attribute"])
            target = self.graph.value(pattern, OW.targets)
            self.vocabulary.add((target, OW.hasAttribute, attribute))
            self.vocabulary.add((attribute, RDF.type, OW.FindingAttribute))
            expected = ExpectedValue.model_validate(payload["expected"]).normalized()
            value = URIRef(str(OW) + "ExpectedValue" + digest(expected.signature())[:24])
            self.graph.add((feature, OW.onAttribute, attribute))
            self.graph.add((feature, OW.expected, value))
            self.graph.add((value, RDF.type, OW.ExpectedValue))
            self.graph.set((value, OW.valueJSON, Literal(expected.model_dump_json(exclude_none=True), datatype=RDF.JSON)))
            concepts = [expected.concept] if expected.kind == "concept" else expected.concepts
            for concept in concepts:
                self.vocabulary.add((attribute, OW.canHaveValue, URIRef(concept)))

    def pattern(self, target, features):
        features = [{"status": "present"}, *features]
        unique = {condition_signature(feature): feature for feature in features}
        node = URIRef(str(OW) + "ClinicalPattern" + digest([target, sorted(unique)])[:24])
        self.graph.add((node, RDF.type, OW.ClinicalPattern))
        self.graph.add((node, OW.targets, URIRef(target)))
        for signature in sorted(unique):
            self.feature(node, unique[signature])
        return str(node)

    def association(self, disease, pattern, *, source_ref, relation_basis, derivation_scope="exact",
                    predictiveness=None, typicality=None, strong_predictor=None, applicability=(), raw=None):
        applicability = sorted(applicability, key=lambda item: json.dumps(item, sort_keys=True))
        node = URIRef(str(OW) + "DiseasePatternAssociation" + digest([disease, pattern, list(applicability)])[:24])
        key = str(node)
        assertion = {"source_ref": source_ref, "relation_basis": relation_basis, "derivation_scope": derivation_scope,
                     "predictiveness": predictiveness, "typicality": typicality, "strong_predictor": strong_predictor, "raw": raw}
        self.assertions.setdefault(key, []).append(assertion)
        previous = self.selected.get(key)
        if previous and relation_basis == previous["relation_basis"] == "bodhi_present_in" and (
                previous["predictiveness"], previous["typicality"]) != (predictiveness, typicality):
            self.conflicts.add(key)
        priority = lambda a: (a["relation_basis"] == "bodhi_present_in", a["derivation_scope"] == "exact",
                              {"due_to": 3, "associated_with": 2, "subtype_intersection": 1, "bodhi_present_in": 4,
                               "external_association": 0, "authored_association": 0}[a["relation_basis"]])
        chosen = assertion if previous is None or priority(assertion) > priority(previous) else previous
        self.selected[key] = chosen
        self.graph.add((URIRef(disease), OW.hasAssociation, node))
        self.graph.add((node, RDF.type, OW.DiseasePatternAssociation))
        self.graph.add((node, OW.pattern, URIRef(pattern)))
        self.graph.add((node, OW.sourceRef, Literal(source_ref)))
        for predicate, value in ((OW.relationBasis, chosen["relation_basis"]), (OW.derivationScope, chosen["derivation_scope"]),
                                 (OW.predictiveness, chosen["predictiveness"]), (OW.typicality, chosen["typicality"]),
                                 (OW.strongPredictor, None if chosen["strong_predictor"] is None else str(chosen["strong_predictor"]).lower())):
            self.graph.remove((node, predicate, None))
            if value is not None:
                self.graph.add((node, predicate, Literal(value)))
        if applicability:
            self.graph.set((node, OW.applicability, Literal(json.dumps(list(applicability), sort_keys=True), datatype=RDF.JSON)))
        return key

    def export(self, output, *, source_snapshots, report, dispositions, require_action_assets=True,
               retain_concepts=(), retain_attributes=(), scoring_policy_path=None, reasoning_policy_path=None):
        output = workspace_path(output)
        if output.exists() and any(output.iterdir()):
            raise ValueError("Use a new or empty preview directory")
        output.mkdir(parents=True, exist_ok=True)
        for key in sorted(self.conflicts):
            node = URIRef(key)
            self.graph.remove((None, OW.hasAssociation, node))
            self.graph.remove((node, None, None))
            dispositions.append({"association_id": key, "decision": "unresolved", "reason": "conflicting_source_likelihoods",
                                 "assertions": self.assertions[key]})
        used = set(self.graph.objects(None, OW.pattern))
        for pattern in list(self.graph.subjects(RDF.type, OW.ClinicalPattern)):
            if pattern not in used:
                for feature in list(self.graph.objects(pattern, OW.hasFeature)):
                    self.graph.remove((feature, None, None))
                self.graph.remove((pattern, None, None))
        expected_nodes = set(self.graph.objects(None, OW.expected))
        for node in list(self.graph.subjects(RDF.type, OW.ExpectedValue)):
            if node not in expected_nodes:
                self.graph.remove((node, None, None))
        attributes, categorical = {}, {}
        retained_attributes = {(URIRef(target), URIRef(attribute)) for target, attribute in retain_attributes}
        for pattern in used:
            target = self.graph.value(pattern, OW.targets)
            for feature in self.graph.objects(pattern, OW.hasFeature):
                attribute = self.graph.value(feature, OW.onAttribute)
                if attribute is not None:
                    attributes.setdefault(target, set()).add(attribute)
                    expected = ExpectedValue.model_validate_json(str(self.graph.value(self.graph.value(feature, OW.expected), OW.valueJSON)))
                    values = [expected.concept] if expected.kind == "concept" else expected.concepts
                    categorical.setdefault(attribute, set()).update(URIRef(value) for value in values)
        for target, attribute in list(self.vocabulary.subject_objects(OW.hasAttribute)):
            if attribute not in attributes.get(target, set()) and (target, attribute) not in retained_attributes:
                self.vocabulary.remove((target, OW.hasAttribute, attribute))
        for attribute, value in list(self.vocabulary.subject_objects(OW.canHaveValue)):
            if value not in categorical.get(attribute, set()) and not any(a == attribute for _, a in retained_attributes):
                self.vocabulary.remove((attribute, OW.canHaveValue, value))
        used_concepts = set(self.graph.subjects(OW.hasAssociation, None)) | set(self.graph.objects(None, OW.targets))
        used_concepts.update(URIRef(uri) for uri in retain_concepts)
        for payload in self.graph.objects(None, OW.applicability):
            used_concepts.update(URIRef(item["concept_id"]) for item in json.loads(str(payload)))
        used_concepts.update(self.graph.objects(None, OW.onAttribute))
        pending = list(used_concepts)
        while pending:
            for predicate, value in self.vocabulary.predicate_objects(pending.pop()):
                if predicate in {OW.hasAttribute, OW.canHaveValue, OW.detectedBy, OW.evaluatedBy, OW.inSystem, OW.hasSupportingContext} and value not in used_concepts:
                    used_concepts.add(value)
                    pending.append(value)
        for subject in list(set(self.vocabulary.subjects())):
            if subject not in used_concepts:
                self.vocabulary.remove((subject, None, None))
        self.registry = {key: value for key, value in self.registry.items() if URIRef(key) in used_concepts}
        combined = Graph().parse(data=(ROOT / "data/ontology/schema.ttl").read_text(encoding="utf-8"), format="turtle")
        combined += self.vocabulary
        combined += self.graph
        # Preparation imports the same submission reader without relaxing its file boundary.
        import sys
        if str(ROOT / "submission") not in sys.path:
            sys.path.insert(0, str(ROOT / "submission"))
        from knowledge.graph import ClinicalKnowledge
        scoring_policy_path = workspace_path(scoring_policy_path or ROOT / "submission/knowledge/scoring_policy.json")
        reasoning_policy_path = workspace_path(reasoning_policy_path or ROOT / "submission/knowledge/reasoning_policy.json")
        policy = ScoringPolicy.model_validate_json(scoring_policy_path.read_text())
        knowledge = ClinicalKnowledge(combined, policy=policy)
        knowledge.validate_graph(require_action_assets=require_action_assets)
        patterns = sorted(self.graph.subjects(RDF.type, OW.ClinicalPattern), key=str)
        by_target = {}
        for pattern in patterns:
            by_target.setdefault(str(self.graph.value(pattern, OW.targets)), []).append(pattern)
        for members in by_target.values():
            for child, parent in knowledge._refinement_edges([str(node) for node in members]):
                self.graph.add((URIRef(child), OW.refinesPattern, URIRef(parent)))
        (output / "schema.ttl").write_bytes((ROOT / "data/ontology/schema.ttl").read_bytes())
        (output / "scoring_policy.json").write_bytes(scoring_policy_path.read_bytes())
        (output / "reasoning_policy.json").write_bytes(reasoning_policy_path.read_bytes())
        for name, graph in (("vocabulary.ttl", self.vocabulary), ("clinical.ttl", self.graph)):
            (output / name).write_text("".join(sorted(f"{s.n3()} {p.n3()} {o.n3()} .\n" for s, p, o in graph)), encoding="utf-8")
        assets = {name: {"path": "knowledge/" + name, "sha256": digest((output / name).read_bytes())}
                  for name in ("schema.ttl", "vocabulary.ttl", "clinical.ttl", "scoring_policy.json", "reasoning_policy.json")}
        self.registry = dict(sorted(self.registry.items()))
        registry_version = digest(self.registry)
        manifest = {"schema_version": "5.0", "registry_version": registry_version,
                    "normalization_version": report.get("normalization_version", NORMALIZATION_VERSION), "source_snapshots": source_snapshots,
                    "scoring_policy_version": policy.version, "scoring_policy": assets["scoring_policy.json"],
                    "reasoning_policy": assets["reasoning_policy.json"],
                    "schema": assets["schema.ttl"], "vocabulary": assets["vocabulary.ttl"], "bundles": [assets["clinical.ttl"]],
                    "preparation_status": "preview_only", "build_id": report.get("build_id")}
        if report.get("algorithm_version"):
            manifest["algorithm_version"] = report["algorithm_version"]
        report = {**report, "status": "preview_only", "schema_version": "5.0", "patterns": len(patterns),
                  "associations": len(set(self.graph.subjects(RDF.type, OW.DiseasePatternAssociation))),
                  "features": len(set(self.graph.subjects(RDF.type, OW.ClinicalFeature))), "registry_version": registry_version,
                  "model_calls": report.get("model_calls", 0), "clinical_review": "not_run", "runtime_admission": "not_run"}
        write(output / "manifest.json", manifest)
        write(output / "registry.json", {"version": registry_version, "entries": list(self.registry.values()), "review_status": "candidate"})
        write_sources(output / "sources.json", self.assertions, dispositions)
        write(output / "report.json", report)
        write(output / "feature-contributions.json", [c.model_dump() for key in sorted(knowledge._profile_cache)
                                                      for c in feature_contributions(knowledge,key)])
        return report
