from __future__ import annotations

from pathlib import Path

from rdflib import Graph


class ClinicalKnowledge:
    """Read-only v4.2 Graph, outside CaseState; no extraction or patient writes."""

    def __init__(self, graph: Graph):
        self._graph = graph

    @classmethod
    def load(cls, manifest_path: Path) -> ClinicalKnowledge:
        raise NotImplementedError("Load only admitted schema, vocabulary, and bundles into one Graph")

    def resolve_concept(self, text: str):
        raise NotImplementedError("Preserve unmapped text and concept uncertainty")

    def get_symptom_attributes(self, symptom_id: str):
        raise NotImplementedError("Return applicable attributes for a fixed HPI slot sequence")

    def get_patterns_by_target(self, finding_id: str):
        raise NotImplementedError("Traverse Pattern targets and owning Disease without a system filter")

    def get_disease_patterns(self, disease_id: str):
        raise NotImplementedError("Return single-target patterns, including patterns without features")

    def get_pattern_features(self, pattern_id: str):
        raise NotImplementedError("Resolve feature targets through their owning pattern")

    def get_supporting_context(self, disease_id: str):
        raise NotImplementedError("Return supporting context separately from patterns")

    def get_exam_methods(self, finding_id: str):
        raise NotImplementedError("Resolve detectedBy and suggested examRequestText")

    def get_planned_tests(self, disease_id: str):
        raise NotImplementedError("Read evaluatedBy for SOAP P.tests only")
