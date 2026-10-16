from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "submission"))

from rdflib import Graph, RDF, URIRef
from Dev.ontology.connections import context_type, project
from Dev.ontology.admission import apply_exam_requests, approved_text_assets
from Dev.ontology.database import file_hash
from Dev.ontology.v5 import OW, PreviewBuilder, write
from knowledge.graph import ClinicalKnowledge
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.state.models import ClinicalValue, RecordItem, SessionContext, WorkflowState


def run():
    checks = []
    def require(value, name):
        if not value:
            raise AssertionError(name)
        checks.append(name)

    class Database:
        def __init__(self):
            self.connection = sqlite3.connect(":memory:")
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("CREATE TABLE rf2_components(id,source_id,destination_id,kind,active,characteristic,type_id)")
            self.connection.execute("INSERT INTO rf2_components VALUES('site','s','site','relationship','1','900000000000011006','363698007')")
        def bodhi_rows(self, name):
            if name == "nodes_condition.csv":
                return [(n, n, {"snomed_id": cid, "name": label, "concept_type": kind, "type_condition": "medical_history"})
                        for n, (cid, label, kind) in enumerate([
                            ("d", "Disease", "Disorder"), ("risk", "Smoking", "Lifestyle"),
                            ("family-source-id", "FH disease", "FamilyHistory"), ("need", "Required disorder", "Disorder")])]
            if name == "edges_is_influenced_by.csv":
                return [(n, n, {"condition_snomed_id_src": a, "condition_snomed_id_dst": b,
                    "relation_strength": strength, "relation_polarity": polarity})
                    for n, (a, b, strength, polarity) in enumerate([
                        ("d", "risk", "high", "positive"), ("d", "family-source-id", "medium", "positive"),
                        ("d", "need", "zero", "positive"), ("d", "need", "high", "negative"),
                        ("risk", "d", "high", "positive"), ("d", "d", "high", "positive")])]
            return [(20, 20, {"condition_snomed_id_src": "d", "condition_snomed_id_dst": "need",
                             "relation_strength": "high", "relation_polarity": "positive"})]
    class Terminology:
        children = {"91689009": ["system", "entire"]}
        fsns = {"system": "Structure of test system (body structure)", "entire": "Entire body system (body structure)"}
        parents = {"system": [("91689009", "system-parent")]}
        def ancestor_paths(self, cid):
            return {"site": [], "system": ["site-system"], "entire": ["site-entire"]}

    builder = PreviewBuilder()
    disease, symptom = str(OW.TestDisease), str(OW.TestSymptom)
    builder.concept(disease, "Disease", "Disease", snomed_id="d", source_refs=["test:d"])
    builder.concept(symptom, "Symptom", "Symptom", snomed_id="s", source_refs=["test:s"])
    pattern = builder.pattern(symptom, [])
    old = builder.association(disease, pattern, source_ref="test:association", relation_basis="due_to")
    database = Database()
    proofs, report = project(database, Terminology(), builder)
    graph = Graph().parse(ROOT / "data/ontology/schema.ttl") + builder.vocabulary + builder.graph
    knowledge = ClinicalKnowledge(graph)
    knowledge.validate_graph()
    risk, family, need = [str(OW) + "BodhiContext" + cid for cid in ("risk", "family-source-id", "need")]
    require({r["id"] for r in knowledge.get_supporting_context(disease)} == {risk, family}, "only_directed_positive_nonzero_nonself_influences_support")
    require(knowledge.get_context_type(family) == "family_history", "family_history_keeps_source_identity_without_asserting_a_valid_sctid")
    require(need not in {r["id"] for r in knowledge.get_supporting_context(disease)}, "prerequisite_is_not_a_support_bonus")
    profile = knowledge.get_disease_patterns(disease)[0]
    require(profile.association_id != old and [c.concept_id for c in profile.applicability] == [need], "prerequisite_rekeys_association_and_keeps_condition")
    require(knowledge.get_symptom_systems(symptom) == [str(OW) + "BodySystemSnomedCTsystem"], "site_ancestry_maps_only_specific_organ_systems")
    require(knowledge.get_system_symptoms(str(OW) + "BodySystemSnomedCTsystem") == [symptom], "reverse_ros_query_consumes_projected_links")
    require(all(refs for refs in proofs.values()), "every_new_relation_retains_source_proof")
    state = WorkflowState(session=SessionContext(session_id="connections-test", deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
        turns_remaining=50, current="DifferentialDiagnosis", initialized=True))
    def fact(ident, concept, kind="context", status="present", subject="patient"):
        state.case.put("S.cc" if kind == "symptom" else "S.fh" if subject == "family" else "S.pmh",
            RecordItem(id=ident, scope="DifferentialDiagnosis", status="done", source_refs=["test:" + ident],
                value=ClinicalValue(kind=kind, text=ident, concept_ids=[concept], status=status, subject=subject,
                    time_context="current" if kind == "symptom" else "unspecified", observation_id="one" if kind == "symptom" else None, episode_id="one" if kind == "symptom" else None)))
    reasoner = ClinicalReasoner(knowledge)
    fact("chief", symptom, "symptom")
    reasoner.retrieve_candidates(state)
    require(state.differential.hypotheses[0].evidence_score == 0, "unasked_prerequisite_recalls_disease_without_activating_support")
    fact("required", need)
    reasoner.refresh_hypotheses(state)
    require(state.differential.hypotheses[0].evidence_score == 2, "confirmed_prerequisite_activates_source_association")
    fact("risk", risk)
    fact("family", family, subject="family")
    reasoner.refresh_hypotheses(state)
    require(state.differential.hypotheses[0].context_bonus == 1, "multiple_confirmed_contexts_keep_existing_one_point_cap")
    fact("risk", risk, status="unknown")
    fact("family", family, subject="patient")
    reasoner.refresh_hypotheses(state)
    require(state.differential.hypotheses[0].context_bonus == 0, "unknown_and_wrong_family_subject_do_not_support")
    fact("required", need, status="absent")
    reasoner.refresh_hypotheses(state)
    require(state.differential.hypotheses[0].evidence_score == 0, "absent_prerequisite_disables_support")
    categories = [("FH asthma", "Misc", "family_history"), ("H/O surgery", "Procedure", "surgical_history"),
        ("On amiodarone treatment", "Misc", "medication_history"), ("Allergen exposure", "Allergy", "allergy_history"),
        ("Smoker", "Lifestyle", "social_history"), ("Driver", "Misc", "occupational_history"),
        ("Stress", "Misc", "psychosocial_history"), ("Taken a vaccine", "Procedure", "screening_history"),
        ("Pregnant", "Disorder", "demographic"), ("Diabetes", "Disorder", "past_medical_history")]
    require(all(context_type({"name": label, "concept_type": kind, "type_condition": "medical_history"}) == expected
                for label, kind, expected in categories), "all_ten_context_categories_are_representable")
    require(not list(graph.triples((None, OW.evaluatedBy, None))), "influence_and_prerequisite_edges_never_create_test_plans")
    scratch = ROOT / "Tmp/d20-verification"
    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=scratch) as temporary:
        path = Path(temporary) / "exam-requests.json"
        method, finding = URIRef(str(OW.TestMethod)), URIRef(str(OW.TestFinding))
        builder.vocabulary.add((method, RDF.type, OW.ExamMethod))
        builder.vocabulary.add((finding, RDF.type, OW.ExamFinding))
        builder.vocabulary.add((finding, OW.detectedBy, method))
        missing_text = Graph().parse(ROOT / "data/ontology/schema.ttl") + builder.vocabulary + builder.graph
        ClinicalKnowledge(missing_text).validate_graph(require_action_assets=False)
        try:
            ClinicalKnowledge(missing_text).validate_graph()
        except ValueError:
            require(True, "graph_only_validation_never_weakens_consultation_request_requirements")
        else:
            raise AssertionError("missing_request_text_accepted_for_consultation")
        write(path, {str(method): "Inspect now"})
        receipt = {"text_assets": {"exam_requests": {"path": path.relative_to(ROOT).as_posix(), "sha256": file_hash(path)}}}
        source = approved_text_assets(receipt, ROOT / "Tmp/test-admission")["exam_requests"]
        apply_exam_requests(builder, source)
        with_text = Graph().parse(ROOT / "data/ontology/schema.ttl") + builder.vocabulary + builder.graph
        ClinicalKnowledge(with_text).validate_graph()
        require(ClinicalKnowledge(with_text).get_exam_methods(str(finding))[0]["text"] == "Inspect now",
                "pinned_separate_text_asset_completes_the_existing_exam_path")
        for payload, name in (({str(OW.UnknownMethod): "Inspect now"}, "unapproved_exam_method_rejected"),
                              ({str(method): "x" * 31}, "overlong_exam_request_rejected")):
            write(path, payload)
            try:
                apply_exam_requests(builder, path)
            except ValueError:
                require(True, name)
            else:
                raise AssertionError(name)
        try:
            approved_text_assets(receipt, ROOT / "Tmp/test-admission")
        except ValueError:
            require(True, "changed_exam_request_pin_rejected_before_admission")
        else:
            raise AssertionError("changed_exam_pin_accepted")
    database.connection.close()
    result = {"status": "pass", "checks": checks, "check_count": len(checks), "real_model_calls": 0, "network": "none"}
    write(ROOT / "Tmp/d20-verification/connections-unit.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run()
