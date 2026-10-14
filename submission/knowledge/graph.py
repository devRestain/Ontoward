from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from rdflib import Graph, Namespace, RDF, RDFS, SKOS, URIRef
from settings import ROOT, knowledge_path

OW = Namespace("urn:ontoward:")
HPI_ORDER = tuple(str(OW[name]) for name in (
    "Location", "Laterality", "Quality", "Onset", "Course", "EpisodeDuration", "Frequency",
    "Timing", "Severity", "Trigger", "AggravatingFactor", "RelievingFactor", "Radiation",
))


class Asset(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")
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
    def __init__(self, graph: Graph, questions: dict[str, str] | None = None, plans: dict[str, Plan] | None = None):
        self._graph = graph
        self.questions = questions or {}
        self.plans = plans or {}

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
        knowledge = cls(graph, questions, {key: Plan.model_validate(value) for key, value in raw_plans.items()})
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

    def get_patterns_by_target(self, finding_id: str) -> list[tuple[str, str]]:
        return sorted({(str(disease), str(pattern))
                       for pattern in self._graph.subjects(OW.targets, URIRef(finding_id))
                       for disease in self._graph.subjects(OW.hasPattern, pattern)})

    def get_disease_patterns(self, disease_id: str) -> list[dict[str, object]]:
        return [{"id": str(pattern), "target": str(self._one(pattern, OW.targets)),
                 "characteristic": self._optional(pattern, OW.importance) == "characteristic"}
                for pattern in sorted(self._graph.objects(URIRef(disease_id), OW.hasPattern), key=str)]

    def get_pattern_features(self, pattern_id: str) -> list[dict[str, str | None]]:
        return [{"id": str(feature), "attribute": self._optional(feature, OW.onAttribute),
                 "value": self._optional(feature, OW.expectsValue), "status": self._optional(feature, OW.expectedStatus),
                 "role": self._optional(feature, OW.clinicalRole)}
                for feature in sorted(self._graph.objects(URIRef(pattern_id), OW.hasFeature), key=str)]

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
        for pattern in self._graph.subjects(RDF.type, OW.ClinicalPattern):
            owners = set(self._graph.subjects(OW.hasPattern, pattern))
            target = self._one(pattern, OW.targets)
            if len(owners) != 1 or not all((owner, RDF.type, OW.Disease) in self._graph for owner in owners):
                raise ValueError("Pattern requires one Disease owner")
            if sum((target, RDF.type, OW[kind]) in self._graph for kind in ("Symptom", "ExamFinding")) != 1:
                raise ValueError("Pattern requires one finding target")
            if self._optional(pattern, OW.importance) not in {None, "characteristic"}:
                raise ValueError("Invalid pattern importance")
        for feature in self._graph.subjects(RDF.type, OW.ClinicalFeature):
            owners = set(self._graph.subjects(OW.hasFeature, feature))
            if len(owners) != 1 or list(self._graph.objects(feature, OW.targets)):
                raise ValueError("Feature must inherit its single pattern target")
            attribute, expected = self._optional(feature, OW.onAttribute), self._optional(feature, OW.expectsValue)
            status, role = self._optional(feature, OW.expectedStatus), self._optional(feature, OW.clinicalRole)
            if bool(attribute) != bool(expected) or (not attribute and status is None):
                raise ValueError("Feature requires a paired categorical or status condition")
            if status not in {None, "present", "absent"} or role not in {None, "supportive", "characteristic", "opposing"}:
                raise ValueError("Invalid feature status or role")
            target = self._one(next(iter(owners)), OW.targets)
            if attribute and ((target, OW.hasAttribute, URIRef(attribute)) not in self._graph or
                              (URIRef(attribute), OW.canHaveValue, URIRef(expected)) not in self._graph):
                raise ValueError("Feature attribute/value is not admitted for its target")
        context_types = {"past_medical_history", "surgical_history", "medication_history", "allergy_history",
                         "family_history", "social_history", "occupational_history", "psychosocial_history",
                         "screening_history", "demographic"}
        for context in self._graph.subjects(RDF.type, OW.ContextFactor):
            if self._optional(context, OW.contextType) not in context_types:
                raise ValueError("Invalid ContextFactor type")
        for finding in self._graph.subjects(RDF.type, OW.ExamFinding):
            if not self.get_exam_methods(str(finding)):
                raise ValueError("ExamFinding requires a detection method")
