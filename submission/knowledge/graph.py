from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from rdflib import Graph, Namespace, RDF, RDFS, SKOS, URIRef
from settings import ROOT, knowledge_path

from .conditions import Applicability, AssociationProfile, ExpectedValue, FeatureCondition, FeatureContribution, ScoringPolicy, numeric_match

OW = Namespace("urn:ontoward:")
HPI_ORDER = tuple(str(OW[name]) for name in (
    "Location", "Laterality", "Quality", "PainQuality", "Onset", "TimeSinceOnset", "Course", "EpisodeDuration", "Frequency",
    "Timing", "Severity", "Trigger", "AggravatingFactor", "RelievingFactor", "RadiationLocation", "Radiation",
))


class Asset(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = Field(pattern=r"^5\.0$")
    registry_version: str = Field(min_length=1)
    normalization_version: str = Field(min_length=1)
    source_snapshots: list[dict[str, object]] = Field(min_length=1)
    scoring_policy_version: str = Field(min_length=1)
    scoring_policy: Asset
    schema_asset: Asset = Field(alias="schema")
    vocabulary: Asset
    bundles: list[Asset] = Field(min_length=1)
    questions: Asset | None = None
    plans: Asset | None = None


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tests: str = ""
    treatment: str = ""
    disposition: str = ""
    follow_up: str = ""
    education: list[str] = Field(default_factory=list)


class ClinicalKnowledge:
    def __init__(self, graph: Graph, questions: dict[str, str] | None = None, plans: dict[str, Plan] | None = None,
                 policy: ScoringPolicy | None = None):
        self._graph = graph
        self.questions = questions or {}
        self.plans = plans or {}
        self.policy = policy or ScoringPolicy.load_default()
        self._contributions: dict[str, list[FeatureContribution]] = {}

    @classmethod
    def load(cls, manifest_path: Path) -> ClinicalKnowledge:
        manifest_path = knowledge_path(manifest_path.relative_to(ROOT).as_posix())
        manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

        def read(asset: Asset, suffix: str) -> bytes:
            path = knowledge_path(asset.path)
            if path.suffix != suffix:
                raise ValueError(f"Expected {suffix} asset: {asset.path}")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != asset.sha256:
                raise ValueError(f"Knowledge digest mismatch: {asset.path}")
            return data

        graph = Graph()
        for asset in [manifest.schema_asset, manifest.vocabulary, *manifest.bundles]:
            graph.parse(data=read(asset, ".ttl").decode("utf-8"), format="turtle")
        questions = json.loads(read(manifest.questions, ".json")) if manifest.questions else {}
        if not isinstance(questions, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in questions.items()):
            raise ValueError("Question assets must map identifiers to template strings")
        raw_plans = json.loads(read(manifest.plans, ".json")) if manifest.plans else {}
        if not isinstance(raw_plans, dict):
            raise ValueError("Plan assets must map disease URIs to plans")
        policy = ScoringPolicy.model_validate_json(read(manifest.scoring_policy, ".json"))
        if policy.version != manifest.scoring_policy_version:
            raise ValueError("Scoring policy version differs from the manifest")
        knowledge = cls(graph, questions, {key: Plan.model_validate(value) for key, value in raw_plans.items()}, policy)
        knowledge.validate_graph()
        return knowledge

    def label(self, concept_id: str) -> str:
        labels = list(self._graph.objects(URIRef(concept_id), RDFS.label))
        return str(next((label for label in labels if label.language == "ko"),
                        next((label for label in labels if label.language == "en"), concept_id)))

    def has_type(self, concept_id: str, kind: str) -> bool:
        return (URIRef(concept_id), RDF.type, OW[kind]) in self._graph

    def resolve_concept(self, text: str) -> list[str]:
        normalized = text.strip().casefold()
        return sorted({str(subject) for predicate in (RDFS.label, SKOS.altLabel)
                       for subject, label in self._graph.subject_objects(predicate)
                       if str(label).strip().casefold() == normalized})

    def concepts(self) -> list[dict[str, str]]:
        return [{"id": str(subject), "label": self.label(str(subject)), "kind": kind}
                for kind in ("Symptom", "ExamFinding", "ContextFactor", "AttributeValue", "FindingAttribute")
                for subject in sorted(set(self._graph.subjects(RDF.type, OW[kind])), key=str)]

    def get_symptom_attributes(self, symptom_id: str) -> list[str]:
        values = {str(value) for value in self._graph.objects(URIRef(symptom_id), OW.hasAttribute)}
        return sorted(values, key=lambda value: (HPI_ORDER.index(value) if value in HPI_ORDER else len(HPI_ORDER), value))

    def get_symptom_systems(self, symptom_id: str) -> list[str]:
        return sorted({str(value) for value in self._graph.objects(URIRef(symptom_id), OW.inSystem)
                       if self.has_type(str(value), "BodySystem")})

    def get_system_symptoms(self, system_id: str) -> list[str]:
        return sorted({str(value) for value in self._graph.subjects(OW.inSystem, URIRef(system_id))
                       if self.has_type(str(value), "Symptom")})

    def get_attribute_values(self, attribute_id: str) -> list[str]:
        return sorted(str(value) for value in self._graph.objects(URIRef(attribute_id), OW.canHaveValue))

    def _profile(self, association) -> AssociationProfile:
        owners = set(self._graph.subjects(OW.hasAssociation, association))
        if len(owners) != 1:
            raise ValueError("Association requires exactly one disease")
        pattern = self._one(association, OW.pattern)
        prediction = self._optional(association, OW.predictiveness)
        basis = self._optional(association, OW.relationBasis)
        scope = self._optional(association, OW.derivationScope) or "exact"
        score, weight_basis = self.policy.weight(prediction, basis, scope)
        strong = self._optional(association, OW.strongPredictor)
        if strong not in {None, "true", "false"}:
            raise ValueError("Strong predictor must be true, false or absent")
        return AssociationProfile(id=str(pattern), association_id=str(association), disease_id=str(next(iter(owners))),
            target=str(self._one(pattern, OW.targets)),
            applicability=[Applicability.model_validate(item) for item in sorted(json.loads(self._optional(association, OW.applicability) or "[]"), key=lambda item: json.dumps(item, sort_keys=True))],
            predictiveness=prediction, typicality=self._optional(association, OW.typicality),
            strong_predictor=None if strong is None else strong == "true", relation_basis=basis, derivation_scope=scope,
            source_refs=sorted(str(ref) for ref in self._graph.objects(association, OW.sourceRef)), score=score, weight_basis=weight_basis)

    def get_patterns_by_target(self, finding_id: str) -> list[AssociationProfile]:
        return [self._profile(association)
                for pattern in sorted(self._graph.subjects(OW.targets, URIRef(finding_id)), key=str)
                for association in sorted(self._graph.subjects(OW.pattern, pattern), key=str)]

    def get_disease_patterns(self, disease_id: str) -> list[AssociationProfile]:
        return [self._profile(association) for association in sorted(self._graph.objects(URIRef(disease_id), OW.hasAssociation), key=str)]

    def get_pattern_features(self, pattern_id: str) -> list[FeatureCondition]:
        features = []
        for feature in sorted(self._graph.objects(URIRef(pattern_id), OW.hasFeature), key=str):
            node = self._one(feature, OW.expected, required=False)
            expected = ExpectedValue.model_validate_json(str(self._one(node, OW.valueJSON))) if node is not None else None
            features.append(FeatureCondition(id=str(feature), attribute=self._optional(feature, OW.onAttribute),
                                              expected=expected, status=self._optional(feature, OW.expectedStatus)))
        return features

    def get_feature_contributions(self, association_id: str) -> list[FeatureContribution]:
        return list(self._contributions.get(association_id, []))

    def value_matches(self, observed: str, expected: str, *, hierarchy=False) -> bool:
        if observed == expected:
            return True
        if hierarchy:
            return any(self.has_type(str(path), "ValueMatch") and self._optional(path, OW.expectedConcept) == expected
                       for path in self._graph.subjects(OW.observedConcept, URIRef(observed)))
        return False

    def feature_refines(self, child: FeatureCondition, parent: FeatureCondition) -> bool:
        if child.attribute != parent.attribute or (parent.status is not None and child.status != parent.status):
            return False
        if parent.expected is None:
            return child.expected is None
        a, b = child.expected, parent.expected
        if a is None:
            return False
        if a.signature() == b.signature():
            return True
        if a.kind in {"quantity", "interval"} and b.kind in {"quantity", "interval"}:
            return numeric_match(b, a) == "matched"
        if a.kind in {"concept", "concept_set"} and b.kind in {"concept", "concept_set"}:
            def clauses(value):
                concepts = [value.concept] if value.kind == "concept" else value.concepts
                result = []
                for concept in concepts:
                    allowed = {concept}
                    if value.match == "subsumption":
                        allowed.update(str(self._one(path, OW.observedConcept)) for path in
                            self._graph.subjects(OW.expectedConcept, URIRef(concept)) if self.has_type(str(path), "ValueMatch"))
                    result.append(allowed)
                return result if value.kind == "concept_set" and value.selection == "all_of" else [set().union(*result)]
            return all(any(c <= p for c in clauses(a)) for p in clauses(b))
        return False

    def pattern_refines(self, child_id: str, parent_id: str) -> bool:
        child, parent = self.get_pattern_features(child_id), self.get_pattern_features(parent_id)
        if self._one(URIRef(child_id), OW.targets) != self._one(URIRef(parent_id), OW.targets):
            return False
        return (all(any(self.feature_refines(c, p) for c in child) for p in parent)
                and not all(any(self.feature_refines(p, c) for p in parent) for c in child))

    def get_supporting_context(self, disease_id: str) -> list[dict[str, str]]:
        return [{"id": str(context), "type": str(self._one(context, OW.contextType))}
                for context in sorted(self._graph.objects(URIRef(disease_id), OW.hasSupportingContext), key=str)]

    def get_context_type(self, context_id: str) -> str:
        return str(self._one(URIRef(context_id), OW.contextType))

    def get_exam_methods(self, finding_id: str) -> list[dict[str, str]]:
        return [{"id": str(method), "text": str(self._one(method, OW.examRequestText))}
                for method in sorted(self._graph.objects(URIRef(finding_id), OW.detectedBy), key=str)]

    def get_planned_tests(self, disease_id: str) -> list[str]:
        return [self.label(str(test)) for test in sorted(self._graph.objects(URIRef(disease_id), OW.evaluatedBy), key=str)]

    def question(self, key: str, target_id: str | None = None) -> str:
        text = self.questions.get(key, "")
        return text.replace("{symptom}", self.label(target_id)) if target_id else text

    def _one(self, subject, predicate, required=True):
        values = list(self._graph.objects(subject, predicate))
        if len(values) > 1 or (required and len(values) != 1):
            raise ValueError(f"Invalid cardinality: {subject} {predicate}")
        return values[0] if values else None

    def _optional(self, subject, predicate):
        value = self._one(subject, predicate, required=False)
        return str(value) if value is not None else None

    def validate_graph(self) -> None:
        if self._optional(OW.OntologySchema, OW.schemaVersion) != "5.0":
            raise ValueError("Knowledge graph requires schema version 5.0")
        if any(list(self._graph.subject_objects(predicate)) for predicate in (OW.hasPattern, OW.expectsValue, OW.clinicalRole, OW.importance)):
            raise ValueError("v5.0 rejects v4.2 ownership, values and manual roles")
        for pattern in self._graph.subjects(RDF.type, OW.ClinicalPattern):
            target = self._one(pattern, OW.targets)
            associations = set(self._graph.subjects(OW.pattern, pattern))
            if not associations or not all((a, RDF.type, OW.DiseasePatternAssociation) in self._graph for a in associations):
                raise ValueError("Pattern requires an association")
            if sum((target, RDF.type, OW[kind]) in self._graph for kind in ("Symptom", "ExamFinding")) != 1:
                raise ValueError("Pattern requires one finding target")
            features = self.get_pattern_features(str(pattern))
            if any(not self.has_type(feature.id, "ClinicalFeature") for feature in features):
                raise ValueError("Pattern features must be typed ClinicalFeature")
            if not features or len({f.signature() for f in features}) != len(features):
                raise ValueError("Pattern requires distinct nonempty feature conditions")
            for parent in self._graph.objects(pattern, OW.refinesPattern):
                if not self.pattern_refines(str(pattern), str(parent)):
                    raise ValueError("Refinement must preserve every parent condition")
        for feature in self._graph.subjects(RDF.type, OW.ClinicalFeature):
            owners = set(self._graph.subjects(OW.hasFeature, feature))
            if len(owners) != 1 or list(self._graph.objects(feature, OW.targets)) or not self.has_type(str(next(iter(owners))), "ClinicalPattern"):
                raise ValueError("Feature must inherit its single pattern target")
            condition = next(f for f in self.get_pattern_features(str(next(iter(owners)))) if f.id == str(feature))
            target = self._one(next(iter(owners)), OW.targets)
            if condition.attribute:
                node = self._one(feature, OW.expected)
                if (not self.has_type(str(node), "ExpectedValue")
                        or self._one(node, OW.valueJSON).datatype != RDF.JSON
                        or not self.has_type(condition.attribute, "FindingAttribute")
                        or (target, OW.hasAttribute, URIRef(condition.attribute)) not in self._graph):
                    raise ValueError("Feature expectation and attribute must be admitted")
                values = [condition.expected.concept] if condition.expected.kind == "concept" else condition.expected.concepts
                if any(not self.has_type(v, "AttributeValue") or (URIRef(condition.attribute), OW.canHaveValue, URIRef(v)) not in self._graph for v in values):
                    raise ValueError("Feature concept value is not admitted for its attribute")
        for path in self._graph.subjects(RDF.type, OW.ValueMatch):
            if self._optional(path, OW.relationKind) not in {"is_a", "regional_part", "approved_region"}:
                raise ValueError("Value match must preserve its relation type")
            if not list(self._graph.objects(path, OW.sourceRef)):
                raise ValueError("Value match requires path evidence")
            for predicate in (OW.observedConcept, OW.expectedConcept):
                if not self.has_type(str(self._one(path, predicate)), "AttributeValue"):
                    raise ValueError("Value match endpoints must be admitted values")
        profiles, identities = [], set()
        for association in self._graph.subjects(RDF.type, OW.DiseasePatternAssociation):
            profile = self._profile(association)
            if not self.has_type(profile.disease_id, "Disease") or not self.has_type(profile.id, "ClinicalPattern"):
                raise ValueError("Association endpoints must be admitted")
            if profile.typicality is not None and profile.typicality not in self.policy.labels:
                raise ValueError("Unknown typicality label")
            if any(not self.has_type(condition.concept_id, "ContextFactor") for condition in profile.applicability):
                raise ValueError("Applicability requires admitted contexts")
            identity = (profile.disease_id, profile.id, tuple(c.model_dump_json() for c in profile.applicability))
            if identity in identities:
                raise ValueError("Duplicate disease-pattern-applicability association")
            identities.add(identity)
            profiles.append(profile)
        self._contributions = {}
        grouped = {}
        for profile in profiles:
            key = (profile.disease_id, profile.target, tuple(c.model_dump_json() for c in profile.applicability))
            grouped.setdefault(key, []).append(profile)
        for child in profiles:
            child_features = self.get_pattern_features(child.id)
            contributions = []
            key = (child.disease_id, child.target, tuple(c.model_dump_json() for c in child.applicability))
            for parent in grouped[key]:
                if (parent.disease_id != child.disease_id or parent.applicability != child.applicability
                        or not self.pattern_refines(child.id, parent.id)):
                    continue
                signatures = {f.signature() for f in self.get_pattern_features(parent.id)}
                changed = [f.id for f in child_features if f.signature() not in signatures]
                contributions.append(FeatureContribution(baseline_association=parent.association_id,
                    refined_association=child.association_id, changed_feature_ids=changed,
                    delta_score=child.score-parent.score, kind="atomic" if len(changed) == 1 else "joint", policy_version=self.policy.version))
            self._contributions[child.association_id] = sorted(contributions, key=lambda c: c.baseline_association)
        context_types = {"past_medical_history", "surgical_history", "medication_history", "allergy_history",
                         "family_history", "social_history", "occupational_history", "psychosocial_history",
                         "screening_history", "demographic"}
        for context in self._graph.subjects(RDF.type, OW.ContextFactor):
            if self._optional(context, OW.contextType) not in context_types:
                raise ValueError("Invalid ContextFactor type")
        for finding in self._graph.subjects(RDF.type, OW.ExamFinding):
            if not self.get_exam_methods(str(finding)):
                raise ValueError("ExamFinding requires a detection method")
