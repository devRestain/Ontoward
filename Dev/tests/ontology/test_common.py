import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "submission"))

from rdflib import Graph, RDF, URIRef
from Dev.ontology import authored
from Dev.ontology.v5 import OW, PreviewBuilder
from knowledge.conditions import ScoringPolicy
from knowledge.graph import ClinicalKnowledge

SOURCE = {"author": "Synthetic test author", "date": "2026-10-18", "assertion": "Synthetic test assertion"}
POLICY = ROOT / "data/preparation/v5/common-complaints-inputs-2026-10-18/scoring_policy.json"


class Verification(unittest.TestCase):
    def setUp(self):
        self.builder = PreviewBuilder()
        self.disease, self.target = str(OW.TestDisease), str(OW.TestSymptom)
        self.builder.concept(self.disease, "Disease", "Synthetic disease", source_refs=["synthetic:disease"])
        self.builder.concept(self.target, "Symptom", "Synthetic symptom", source_refs=["synthetic:symptom"])
        self.questions = {}
        self.policy = ScoringPolicy.model_validate_json(POLICY.read_text())

    def apply(self, *records):
        return authored.apply(self.builder, [(i, authored.Entry.model_validate({"source": SOURCE, **r}))
            for i, r in enumerate(records, 1)], self.questions, source_name="synthetic-test.jsonl")

    def knowledge(self):
        k = ClinicalKnowledge(Graph().parse(ROOT / "data/ontology/schema.ttl") + self.builder.vocabulary + self.builder.graph,
            policy=self.policy)
        k.validate_graph()
        return k

    def test_legacy_weights_and_new_qualitative_policy(self):
        old = ScoringPolicy.load_default()
        for basis in ("bodhi_present_in", "due_to", "associated_with", "subtype_intersection"):
            for scope in ("exact", "descendant"):
                for likelihood in (*old.labels, *([] if basis == "bodhi_present_in" else [None])):
                    self.assertEqual(old.weight(likelihood, basis, scope), self.policy.weight(likelihood, basis, scope))
        self.assertEqual(self.policy.weight(None, "external_association", "exact"), (1, "external_association"))
        self.assertEqual(self.policy.weight("2.5", "authored_association", "exact"), (2.5, "author_judgment"))
        for score, basis, scope in [("high", "external_association", "exact"), (None, "external_association", "descendant"),
                                     ("nan", "authored_association", "exact")]:
            with self.assertRaises(ValueError):
                self.policy.weight(score, basis, scope)

    def test_authored_judgment_retains_source_and_conditions_without_literature(self):
        context = str(OW.TestContext)
        self.apply({"type": "concept", "id": context, "kind": "ContextFactor", "label": "Synthetic history",
            "context_type": "past_medical_history"}, {"type": "association", "target": self.target,
            "disease": self.disease, "support": 2.5, "applicability": [{"concept_id": context}]})
        profile = self.knowledge().get_disease_patterns(self.disease)[0]
        self.assertEqual((profile.score, profile.weight_basis), (2.5, "author_judgment"))
        self.assertEqual(profile.applicability[0].concept_id, context)
        assertion = self.builder.assertions[profile.association_id][0]
        self.assertEqual(assertion["raw"]["source"], {**SOURCE, "references": []})
        self.assertTrue(assertion["source_ref"].startswith("authored:"))

    def test_record_attribute_does_not_invent_diagnostic_pattern_or_threshold(self):
        attribute = str(OW.TestMeasurement)
        self.apply({"type": "attribute", "target": self.target, "attribute": attribute, "label": "Synthetic length",
            "question": {"text": "수치를 알려 주세요.", "answer_type": "quantity", "units": ["cm"]}})
        self.assertFalse(list(self.builder.graph.subjects(RDF.type, OW.ClinicalPattern)))
        self.assertEqual(self.questions[self.target + "|" + attribute]["units"], ["cm"])
        with self.assertRaises(ValueError):
            self.apply({"type": "association", "target": self.target, "disease": self.disease,
                "features": [{"attribute": attribute, "expected": {"kind": "quantity", "value": 1, "unit": "kg"}}]})

    def test_authored_claim_cannot_create_unregistered_categorical_value(self):
        attribute = str(OW.TestAttribute)
        self.apply({"type": "attribute", "target": self.target, "attribute": attribute, "label": "Synthetic dimension",
            "question": {"text": "양상을 알려 주세요.", "answer_type": "category"},
            "values": [{"id": str(OW.TestValue), "label": "Synthetic value"}]})
        with self.assertRaises(ValueError):
            self.apply({"type": "association", "target": self.target, "disease": self.disease,
                "features": [{"attribute": attribute, "expected": {"kind": "concept", "concept": str(OW.Invented)}}]})

    def test_authored_input_rejects_silently_discarded_conditions_and_duplicate_keys(self):
        with self.assertRaises(ValueError):
            authored.Entry.model_validate({"type": "alias", "target": self.target, "source": SOURCE,
                "aliases": {"ko": ["가상 표현"]}, "support": 2})
        scratch = ROOT / "Tmp/common-complaints-2026-10-18"
        with TemporaryDirectory(dir=scratch) as temporary:
            path = Path(temporary) / "duplicate.jsonl"
            path.write_text('{"type":"alias","type":"association"}')
            with self.assertRaises(ValueError):
                authored.read_entries(path)

    def test_duplicate_source_does_not_boost_existing_bodhi_weight(self):
        pattern = self.builder.pattern(self.target, [])
        self.builder.association(self.disease, pattern, source_ref="synthetic:bodhi", relation_basis="bodhi_present_in",
            predictiveness="medium", typicality="low")
        self.apply({"type": "association", "target": self.target, "disease": self.disease, "support": 4})
        profiles = self.knowledge().get_disease_patterns(self.disease)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].weight_basis, "bodhi_ordinal")


if __name__ == "__main__":
    unittest.main()
