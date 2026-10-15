"""Offline behavioral verification using only a temporary submission copy."""
import copy
import hashlib
import importlib.util
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from zipfile import ZipFile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, Mock

import tempfile

PROJECT = Path(__file__).resolve().parents[3]
HERE = Path(os.environ.get("ONTOWARD_TEST_OUTPUT", PROJECT / "Tmp/workflow-tests"))
HERE.mkdir(parents=True, exist_ok=True)
RUN = Path(tempfile.mkdtemp(prefix="run-", dir=HERE))
COPY = RUN / "submission"
SOURCE = Path(os.environ.get("ONTOWARD_TEST_SUBMISSION", PROJECT / "submission"))
SOURCE_MANIFEST = SOURCE / "knowledge/manifest.json"
SOURCE_MANIFEST_HASH = hashlib.sha256(SOURCE_MANIFEST.read_bytes()).hexdigest() if SOURCE_MANIFEST.exists() else None
shutil.copytree(SOURCE, COPY, ignore=shutil.ignore_patterns("__pycache__"))
sys.path.insert(0, str(COPY))

from rdflib import Graph, Literal, RDF, URIRef
from workflow.text_config import TextConfig
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.interview_planner import InterviewPlanner
from workflow.submission_writer import SubmissionWriter
from workflow.graph import build_graph, finish, route_budget, run_node
from workflow.rules.budget import BudgetPolicy
from workflow.rules.action import content_error
from workflow.rules.input import fixed_reply
from workflow.runtime import PreparedResources, assemble_consultation, prepare, consult
from workflow.state.models import ActionSpec, ClinicalValue, Fact, Hypothesis, InteractionEntry, ParsedInput, Question, RecordItem, SessionContext, WorkflowState
from knowledge.graph import ClinicalKnowledge, OW, Plan
from knowledge.conditions import ExpectedValue
from nova_sdk import Client, NovaError, RECORD_FIELDS
from settings import knowledge_manifest, knowledge_path

TTL = '''@prefix ow: <urn:ontoward:> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
ow:Alpha a ow:Disease; rdfs:label "가상질환A"@ko; ow:hasAssociation ow:alphaBase, ow:alphaLocation; ow:hasSupportingContext ow:Context .
ow:Beta a ow:Disease; rdfs:label "가상질환B"@ko; ow:hasAssociation ow:betaBase, ow:betaLocation, ow:betaExamAssociation; ow:evaluatedBy ow:TestX .
ow:Complaint a ow:Symptom; rdfs:label "가상증상"@ko; ow:hasAttribute ow:Location, ow:Quality .
ow:Other a ow:Symptom; rdfs:label "별도증상"@ko .
ow:Location a ow:FindingAttribute; rdfs:label "위치"@ko; ow:canHaveValue ow:Here, ow:Elsewhere .
ow:Quality a ow:FindingAttribute; rdfs:label "양상"@ko; ow:canHaveValue ow:Dull .
ow:Here a ow:AttributeValue; rdfs:label "가상부위"@ko .
ow:Elsewhere a ow:AttributeValue; rdfs:label "다른부위"@ko .
ow:Dull a ow:AttributeValue; rdfs:label "둔함"@ko .
ow:baseX a ow:ClinicalPattern; ow:targets ow:Complaint; ow:hasFeature ow:basePresent .
ow:basePresent a ow:ClinicalFeature; ow:expectedStatus "present" .
ow:locationX a ow:ClinicalPattern; ow:targets ow:Complaint; ow:hasFeature ow:locationPresent, ow:locationFeature; ow:refinesPattern ow:baseX .
ow:locationPresent a ow:ClinicalFeature; ow:expectedStatus "present" .
ow:locationFeature a ow:ClinicalFeature; ow:onAttribute ow:Location; ow:expected ow:hereExpected .
ow:hereExpected a ow:ExpectedValue; ow:valueJSON '{"kind":"concept","concept":"urn:ontoward:Here"}'^^rdf:JSON .
ow:alphaBase a ow:DiseasePatternAssociation; ow:pattern ow:baseX; ow:relationBasis "bodhi_present_in"; ow:predictiveness "low"; ow:typicality "high"; ow:sourceRef "synthetic:alpha:base" .
ow:betaBase a ow:DiseasePatternAssociation; ow:pattern ow:baseX; ow:relationBasis "bodhi_present_in"; ow:predictiveness "low"; ow:typicality "high"; ow:sourceRef "synthetic:beta:base" .
ow:alphaLocation a ow:DiseasePatternAssociation; ow:pattern ow:locationX; ow:relationBasis "bodhi_present_in"; ow:predictiveness "medium"; ow:typicality "high"; ow:sourceRef "synthetic:alpha:location" .
ow:betaLocation a ow:DiseasePatternAssociation; ow:pattern ow:locationX; ow:relationBasis "bodhi_present_in"; ow:predictiveness "medium"; ow:typicality "high"; ow:sourceRef "synthetic:beta:location" .
ow:betaExam a ow:ClinicalPattern; ow:targets ow:ExamX; ow:hasFeature ow:examPresent .
ow:examPresent a ow:ClinicalFeature; ow:expectedStatus "present" .
ow:betaExamAssociation a ow:DiseasePatternAssociation; ow:pattern ow:betaExam; ow:relationBasis "due_to"; ow:sourceRef "synthetic:beta:exam" .
ow:ExamX a ow:ExamFinding; rdfs:label "가상소견"@ko; ow:detectedBy ow:MethodX .
ow:MethodX a ow:ExamMethod; ow:examRequestText "가상 진찰을 하겠습니다" .
ow:Context a ow:ContextFactor; rdfs:label "가상병력"@ko; ow:contextType "past_medical_history" .
ow:TestX a ow:Test; rdfs:label "가상검사"@ko .
'''
QUESTIONS = {str(OW.Location): "어느 부위인가요?", str(OW.Quality): "어떤 느낌인가요?", str(OW.Context): "가상병력이 있나요?"}
PLANS = {str(OW.Alpha): {"education": ["가상 A 안내입니다."]}, str(OW.Beta): {
    "treatment": "준비된 가상 계획", "education": ["가상 B 첫 안내입니다.", "가상 B 둘째 안내입니다."]}}


def write_assets():
    files = {"schema.ttl": (SOURCE / "knowledge/schema.ttl").read_text(encoding="utf-8"), "vocabulary.ttl": "", "clinical.ttl": TTL,
             "scoring_policy.json": (SOURCE / "knowledge/scoring_policy.json").read_text(encoding="utf-8"),
             "questions.json": json.dumps(QUESTIONS, ensure_ascii=False), "plans.json": json.dumps(PLANS, ensure_ascii=False)}
    entries = {}
    for name, text in files.items():
        path = COPY / "knowledge" / name
        path.write_text(text, encoding="utf-8")
        entries[name] = {"path": "knowledge/" + name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"schema_version": "5.0", "registry_version": "synthetic-v5", "normalization_version": "v5.0.1",
                "source_snapshots": [{"dataset": "synthetic", "sha256": hashlib.sha256(TTL.encode()).hexdigest()}],
                "scoring_policy_version": "v5.0.1", "scoring_policy": entries["scoring_policy.json"],
                "schema": entries["schema.ttl"], "vocabulary": entries["vocabulary.ttl"],
                "bundles": [entries["clinical.ttl"]], "questions": entries["questions.json"], "plans": entries["plans.json"]}
    (COPY / "knowledge/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


write_assets()
CONFIG = TextConfig.load()


def knowledge():
    return ClinicalKnowledge.load(knowledge_manifest())


def resources(k=None, config=None):
    config = config or CONFIG
    return PreparedResources(k or knowledge(), config)


def make_consultation(client=None, prepared=None):
    return assemble_consultation(client or FakeSDK(), prepared or resources())


def make_planner(k, config):
    return make_consultation(prepared=resources(k, config)).planner


def make_doctor(config):
    return make_consultation(prepared=resources(config=config)).doctor


def make_interpreter(config):
    return make_consultation(prepared=resources(config=config)).interpreter


def make_writer(client, k, config):
    return make_consultation(client, resources(k, config)).writer


def state(scope="Initiation", initialized=False, turns=50):
    return WorkflowState(session=SessionContext(session_id="synthetic-case",
        deadline=datetime.now(timezone.utc) + timedelta(minutes=25), turns_remaining=turns,
        current=scope, initialized=initialized))


def record(s, ident="chief", target=OW.Complaint, kind="symptom", status="present", field="S.cc", episode="episode1", attribute=None, values=None):
    s.case.put(field, RecordItem(id=ident, scope=s.session.current, status="done", source_refs=["source"],
        value=ClinicalValue(kind=kind, text="synthetic observation", status=status, concept_ids=[str(target)],
            observation_id="obs1", episode_id=episode, attribute_id=str(attribute) if attribute else None,
            values=[str(v) for v in values or []], time_context="current")))


def add_v5_pattern(k, name, target, expectations, *, disease=OW.Alpha, label="very_high", applicability=None):
    pattern, association = OW[name], OW[name + "Association"]
    k._graph.add((disease, OW.hasAssociation, association))
    for predicate, value in ((RDF.type, OW.DiseasePatternAssociation), (OW.pattern, pattern),
                             (OW.relationBasis, Literal("bodhi_present_in")), (OW.predictiveness, Literal(label)),
                             (OW.sourceRef, Literal("synthetic:" + name))):
        k._graph.add((association, predicate, value))
    if applicability:
        k._graph.add((association, OW.applicability, Literal(json.dumps(applicability), datatype=RDF.JSON)))
    k._graph.add((pattern, RDF.type, OW.ClinicalPattern))
    k._graph.add((pattern, OW.targets, target))
    feature = OW[name + "Presence"]
    k._graph.add((pattern, OW.hasFeature, feature))
    k._graph.add((feature, RDF.type, OW.ClinicalFeature))
    k._graph.add((feature, OW.expectedStatus, Literal("present")))
    for index, (attribute, expected) in enumerate(expectations):
        k._graph.add((target, OW.hasAttribute, attribute))
        k._graph.add((attribute, RDF.type, OW.FindingAttribute))
        feature, node = OW[name + f"Feature{index}"], OW[name + f"Expected{index}"]
        for predicate, value in ((RDF.type, OW.ClinicalFeature), (OW.onAttribute, attribute), (OW.expected, node)):
            k._graph.add((feature, predicate, value))
        k._graph.add((pattern, OW.hasFeature, feature))
        k._graph.add((node, RDF.type, OW.ExpectedValue))
        k._graph.add((node, OW.valueJSON, Literal(json.dumps(expected), datatype=RDF.JSON)))
    k.validate_graph()
    return association, pattern


def question(s, ident="q", purpose="feature", target=OW.Other, attribute=None, text="別の症状はありますか？", order=0, priority=0, field="S.ros", kind="SAY"):
    q = Question(item_id=ident, field=field, purpose=purpose, kind=kind, target_id=str(target) if target else None,
                 attribute_id=str(attribute) if attribute else None, text=text, order=order, priority=priority,
                 affirmative_presence=True)
    make_planner(knowledge(), CONFIG).questions.register(s, q)
    return q


def pending(s, q):
    s.interaction.pending = ActionSpec(question=q, content=q.text, request_id="request-1")


def fact(field, kind, target, text, *, q=None, attribute=None, values=None, status="present"):
    v = {"kind": kind, "text": text, "status": status, "concept_ids": [str(target)],
         "observation_id": (q or {}).get("observation_id") or "obs1",
         "episode_id": (q or {}).get("episode_id") or "episode1", "time_context": "current"}
    if attribute:
        v.update(attribute_id=str(attribute), values=[str(value) for value in values])
    result = {"field": field, "value": v, "quote": text}
    if q:
        result["record_id"] = q["item_id"]
    return result


class FakeSDK:
    session_id = "synthetic-case"
    timeout = 120

    def __init__(self, *, context="네", no_candidate=False, refusal=False, unknown_action=False, submit_status="completed", malformed=False):
        self.remaining = 50
        self.context = context
        self.no_candidate = no_candidate
        self.refusal = refusal
        self.unknown_action = unknown_action
        self.submit_status = submit_status
        self.malformed = malformed
        self.calls = []
        self.actions = []
        self.submissions = []
        self.status = "active"
        self.deadline = datetime.now(timezone.utc) + timedelta(minutes=25)

    def session(self):
        return {"session_id": self.session_id, "status": self.status, "deadline": self.deadline.isoformat(),
                "turns_remaining": self.remaining, "initial": {"opening": "가상증상이 있어요", "vital_signs": {"pulse": 80}},
                "allowed_actions": ["SAY", "EXAM", "DIAGNOSE"]}

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        payload = json.loads(messages[1]["content"])
        if messages[0]["content"] == CONFIG.doctor_prompt:
            return self.completion(payload["question"]["text"])
        q, text = payload["question"], payload["input"]
        facts = []
        if not q or q["purpose"] in {"chief", "clarification"}:
            facts = [fact("S.cc", "symptom", OW.Other if self.no_candidate else OW.Complaint, text, q=q)]
        elif q["purpose"] == "hpi":
            for attr, value in ((OW.Location, OW.Here), (OW.Quality, OW.Dull)):
                matching = next((r for r in payload["records"] if r["id"].endswith(str(attr))), None)
                matched_q = {**q, "item_id": matching["id"]} if matching else None
                facts.append(fact("S.hpi", "attribute", OW.Complaint, text, q=matched_q, attribute=attr, values=[value]))
        elif q["kind"] == "EXAM":
            facts = [fact("O.exam", "finding", OW.ExamX, text, q=q)]
        elif q["purpose"] == "context":
            facts = [fact("S.pmh", "context", OW.Context, text, q=q, status="absent" if text == "아니요" else "present")]
        elif q["purpose"] == "ros":
            facts = [fact("S.ros", "symptom", q["target_id"], text, q=q, status="absent" if text == "없어요" else "present")]
        content = "{bad json" if self.malformed else json.dumps({"facts": facts}, ensure_ascii=False)
        return self.completion(content)

    @staticmethod
    def completion(content):
        return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 20, "completion_tokens": 10}}

    def _reply(self, text, request_id, exam=False):
        self.actions.append({"kind": "EXAM" if exam else "SAY", "content": text, "request_id": request_id})
        if self.unknown_action:
            raise NovaError("API_UNAVAILABLE")
        self.remaining -= 1
        if exam and self.refusal:
            raise NovaError("EXAM_NOT_RECOGNIZED")
        answer = ("가상소견 확인" if exam else "가상부위, 둔해요" if "부위" in text or "느낌" in text else
                  self.context if text == QUESTIONS[str(OW.Context)] else
                  "가상증상이 있어요" if text in {CONFIG.texts.chief_question, CONFIG.texts.clarification_question} else
                  "없어요" if text == CONFIG.texts.open_question or text.endswith("도 있나요?") else "알겠습니다")
        return {"status": "OK", "turn": 50 - self.remaining, "turns_remaining": self.remaining,
                "result" if exam else "content": answer}

    def say(self, content, request_id):
        return self._reply(content, request_id)

    def exam(self, content, request_id):
        return self._reply(content, request_id, exam=True)

    def diagnose(self, **kwargs):
        self.submissions.append(kwargs)
        if self.submit_status == "timeout":
            raise NovaError("API_UNAVAILABLE")
        return {"status": self.submit_status}


class Verification(unittest.TestCase):
    def test_discard_batch_rejects_pending_and_done_without_partial_changes(self):
        for protected in ("pending", "done"):
            with self.subTest(protected=protected):
                s = state("ChiefComplaint", True)
                question(s, ident="first")
                q = question(s, ident="protected")
                if protected == "pending":
                    pending(s, q)
                else:
                    record(s, ident="protected")
                before = s.model_dump()
                with self.assertRaises(ValueError):
                    make_consultation().questions.discard_unasked(s, {"first", "protected"})
                self.assertEqual(before, s.model_dump())

    def test_discard_repeatedly_preserves_facts_and_clears_selected(self):
        s = state("ChiefComplaint", True)
        record(s)
        q = question(s)
        w = make_consultation()
        w.interactions.select_question(s, q)
        w.questions.discard_unasked(s, {q.item_id, "missing"})
        self.assertIsNone(s.interaction.selected)
        self.assertIsNone(s.case.get(q.item_id))
        self.assertFalse(s.questions.questions)
        self.assertIsNotNone(s.case.get("chief"))
        before = s.model_dump()
        w.questions.discard_unasked(s, {q.item_id, "missing"})
        self.assertEqual(before, s.model_dump())

    def test_budget_decision_is_pure_and_preservation_differs_from_execution_order(self):
        s = state("ChiefComplaint", True)
        w = make_consultation()
        record(s)
        w.planner.prepare_chief_complaint(s)
        s.session.limits["ChiefComplaint"].actions = 2
        before = s.model_dump()
        decision = w.budget.evaluate(s)
        self.assertEqual(before, s.model_dump())
        self.assertTrue(decision.discard)
        w.check_budget(s)
        self.assertIn("open_inquiry", [q.purpose for q in s.questions.questions])
        w.planner.select_question(s)
        self.assertEqual(s.interaction.selected.question.purpose, "hpi")

    def test_clarification_resumes_regular_session_preparation(self):
        s = state("ChiefComplaint")
        client = FakeSDK()
        w = make_consultation(client)
        w.enter_session(s)
        self.assertTrue(s.session.initialized)
        self.assertFalse(s.session.questions_prepared)
        self.assertEqual(s.questions.questions[0].purpose, "clarification")
        w.planner.select_question(s)
        w.doctor.frame_action(s, client)
        w.doctor.validate_action(s)
        w.doctor.execute_action(s, client)
        w.interpreter.process_input(s, knowledge(), client)
        w.refresh_after_input(s)
        w.advance_session(s)
        self.assertEqual(s.session.current, "ChiefComplaint")
        self.assertTrue(s.session.questions_prepared)
        self.assertIn("hpi", [q.purpose for q in s.questions.questions])
        self.assertIn("open_inquiry", [q.purpose for q in s.questions.questions])

    def test_injected_clock_expires_collection_between_framing_and_execution(self):
        clock = [datetime(2026, 10, 14, tzinfo=timezone.utc)]
        client = FakeSDK()
        w = assemble_consultation(client, resources(), now=lambda: clock[0], sleep=lambda _: None,
                                  new_request_id=lambda: "fixed-request")
        s = state("Initiation", True)
        s.session.deadline = clock[0] + timedelta(seconds=121)
        q = question(s, purpose="chief", field="S.cc", target=None, text=CONFIG.texts.chief_question)
        w.interactions.select_question(s, q)
        w.doctor.frame_action(s, client)
        w.doctor.validate_action(s)
        self.assertTrue(s.interaction.selected.ready)
        clock[0] += timedelta(seconds=2)
        w.check_budget(s)
        self.assertTrue(s.session.finalizing)
        self.assertIsNone(s.interaction.selected)
        self.assertFalse(client.actions)
        self.assertEqual(client.calls[0]["request_id"], "fixed-request")

    def test_node_validation_does_not_replay_completed_external_action(self):
        s = state("Initiation", True)
        q = question(s, purpose="chief", field="S.cc", target=None, text=CONFIG.texts.chief_question)
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="once", ready=True)
        client = FakeSDK()
        w = make_consultation(client)
        def execute_then_invalidate(updated):
            w.doctor.execute_action(updated, client)
            updated.case.S["invalid"] = {}
        before = s.model_dump()
        with self.assertRaises(ValueError):
            run_node(s, execute_then_invalidate)
        self.assertEqual(len(client.actions), 1)
        self.assertEqual(before, s.model_dump())

    def test_submission_repair_guard_rejects_second_reset(self):
        s = state()
        writer = make_writer(FakeSDK(), knowledge(), CONFIG)
        writer.begin_repair(s)
        s.interaction.submission_request_id = "second-submission"
        s.interaction.submission_result = {"status": "pending"}
        before = s.model_dump()
        with self.assertRaises(ValueError):
            writer.begin_repair(s)
        self.assertEqual(before, s.model_dump())

    def test_v5_shared_patterns_refinement_replacement_and_joint_deltas(self):
        k = knowledge()
        k._graph.set((OW.alphaBase, OW.predictiveness, Literal("medium")))
        k._graph.set((OW.alphaLocation, OW.predictiveness, Literal("low")))
        association, pattern = add_v5_pattern(k, "jointVariant", OW.Complaint, [
            (OW.Location, {"kind": "concept", "concept": str(OW.Here)}),
            (OW.Quality, {"kind": "concept", "concept": str(OW.Dull)})])
        s = state("DifferentialDiagnosis", True)
        record(s)
        reasoner = ClinicalReasoner(k)
        reasoner.retrieve_candidates(s)
        scores = lambda: {h.disease_id: h.evidence_score for h in s.differential.hypotheses}
        self.assertEqual(scores()[str(OW.Alpha)], 2)
        record(s, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        reasoner.refresh_hypotheses(s)
        self.assertEqual(scores()[str(OW.Alpha)], 1)
        self.assertEqual(scores()[str(OW.Beta)], 2)
        shared = {profile.association_id: profile.id for disease in (OW.Alpha, OW.Beta)
                  for profile in k.get_disease_patterns(str(disease))}
        self.assertEqual(shared[str(OW.alphaLocation)], shared[str(OW.betaLocation)])
        joint = [c for c in k.get_feature_contributions(str(association)) if c.baseline_association == str(OW.alphaBase)]
        self.assertEqual([(c.kind, c.delta_score, len(c.changed_feature_ids)) for c in joint], [("joint", 2, 2)])
        record(s, "quality", kind="attribute", field="S.hpi", attribute=OW.Quality, values=[OW.Dull])
        reasoner.refresh_hypotheses(s)
        self.assertEqual(scores()[str(OW.Alpha)], 4)
        self.assertEqual(scores()[str(OW.Beta)], 2)
        s.case.get("quality").value.episode_id = "another-episode"
        reasoner.refresh_hypotheses(s)
        self.assertEqual(scores()[str(OW.Alpha)], 1)
        k._graph.set((OW.alphaLocation, OW.predictiveness, Literal("zero")))
        k.validate_graph()
        reasoner.refresh_hypotheses(s)
        self.assertEqual(scores()[str(OW.Alpha)], 0)

    def test_v5_typed_time_bases_units_and_episode_boundaries(self):
        from knowledge.conditions import ExpectedValue, numeric_match
        k = knowledge()
        add_v5_pattern(k, "elapsedVariant", OW.Complaint, [(OW.TimeSinceOnset,
            {"kind": "interval", "lower": 5, "upper": 14, "unit": "day"})])
        s = state("DifferentialDiagnosis", True)
        record(s)
        record(s, "duration", kind="attribute", field="S.hpi", attribute=OW.EpisodeDuration)
        s.case.get("duration").value.measurement = ExpectedValue(kind="quantity", value=7, unit="day")
        reasoner = ClinicalReasoner(k)
        reasoner.retrieve_candidates(s)
        alpha = lambda: next(h for h in s.differential.hypotheses if h.disease_id == str(OW.Alpha))
        self.assertEqual(alpha().evidence_score, 1)
        record(s, "elapsed", kind="attribute", field="S.hpi", attribute=OW.TimeSinceOnset)
        s.case.get("elapsed").value.measurement = ExpectedValue(kind="quantity", value=168, unit="h")
        reasoner.refresh_hypotheses(s)
        self.assertEqual(alpha().evidence_score, 4)
        s.case.get("elapsed").value.episode_id = "another-episode"
        reasoner.refresh_hypotheses(s)
        self.assertEqual(alpha().evidence_score, 1)
        self.assertEqual(numeric_match(ExpectedValue(kind="quantity", value=1, unit="month"),
                                      ExpectedValue(kind="quantity", value=30, unit="day")), "unknown")
        with self.assertRaises(ValueError):
            ClinicalValue(kind="attribute", text="7 days", attribute_id=str(OW.TimeSinceOnset),
                measurement={"kind": "quantity", "value": True, "unit": "day"})
        with self.assertRaises(ValueError):
            ExpectedValue(kind="quantity", value=3, unit="day", lower=2)

    def test_v5_applicability_is_required_and_unknown_is_not_support(self):
        k = knowledge()
        k._graph.remove((OW.Alpha, OW.hasSupportingContext, OW.Context))
        k._graph.set((OW.alphaLocation, OW.applicability, Literal(json.dumps([{
            "concept_id": str(OW.Context), "status": "present", "subject": "patient", "time_context": "current"}]), datatype=RDF.JSON)))
        k.validate_graph()
        s = state("ContextFactor", True)
        record(s)
        record(s, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        reasoner = ClinicalReasoner(k)
        reasoner.retrieve_candidates(s)
        alpha = lambda: next(h for h in s.differential.hypotheses if h.disease_id == str(OW.Alpha))
        self.assertEqual(alpha().evidence_score, 1)
        make_planner(k, CONFIG).prepare_context_questions(s)
        required_question = next(q for q in s.questions.questions if q.target_id == str(OW.Context))
        self.assertEqual((required_question.subject, required_question.time_context), ("patient", "current"))
        record(s, "old-context", OW.Context, "context", "present", "S.pmh")
        s.case.get("old-context").value.time_context = "past"
        make_planner(k, CONFIG).select_question(s)
        self.assertEqual(s.interaction.selected.question.item_id, required_question.item_id)
        s.case.remove({"old-context"})
        record(s, "context", OW.Context, "context", "unknown", "S.pmh")
        reasoner.refresh_hypotheses(s)
        self.assertEqual(alpha().evidence_score, 1)
        s.case.get("context").value.status = "present"
        reasoner.refresh_hypotheses(s)
        self.assertEqual(alpha().evidence_score, 2)
        self.assertIn("context", alpha().evidence_ids)
        s.case.get("context").value.subject = "family"
        reasoner.refresh_hypotheses(s)
        self.assertEqual(alpha().evidence_score, 1)

    def test_v5_verified_value_path_does_not_create_patient_observations(self):
        from knowledge.conditions import ExpectedValue, FeatureCondition
        k = knowledge()
        k._graph.set((OW.hereExpected, OW.valueJSON, Literal(json.dumps({
            "kind": "concept", "concept": str(OW.Here), "match": "subsumption"}), datatype=RDF.JSON)))
        for predicate, value in ((RDF.type, OW.ValueMatch), (OW.observedConcept, OW.Elsewhere),
                                 (OW.expectedConcept, OW.Here), (OW.relationKind, Literal("approved_region")),
                                 (OW.sourceRef, Literal("synthetic:reviewed-region-path"))):
            k._graph.add((OW.locationPath, predicate, value))
        k.validate_graph()
        s = state("DifferentialDiagnosis", True)
        record(s)
        record(s, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Elsewhere])
        ClinicalReasoner(k).retrieve_candidates(s)
        self.assertEqual([h.evidence_score for h in s.differential.hypotheses], [2, 2])
        self.assertEqual(s.case.get("location").value.values, [str(OW.Elsewhere)])
        exact = FeatureCondition(id="exact", attribute=str(OW.Location), expected=ExpectedValue(kind="concept", concept=str(OW.Here)))
        broad = next(feature for feature in k.get_pattern_features(str(OW.locationX)) if feature.expected)
        self.assertTrue(k.feature_refines(exact, broad))
        self.assertFalse(k.feature_refines(broad, exact))

    def test_v5_policy_fraction_zero_and_manifest_version(self):
        from knowledge.conditions import ScoringPolicy
        k = knowledge()
        k._graph.set((OW.alphaBase, OW.predictiveness, Literal("rare")))
        k.validate_graph()
        s = state("DifferentialDiagnosis", True)
        record(s)
        ClinicalReasoner(k).retrieve_candidates(s)
        alpha = next(h for h in s.differential.hypotheses if h.disease_id == str(OW.Alpha))
        self.assertEqual(alpha.evidence_score, 0.5)
        self.assertEqual(WorkflowState.model_validate_json(s.model_dump_json()).differential.hypotheses[-1].score, 0.5)
        self.assertEqual(k.policy.weight("zero", "due_to", "exact"), (0, "bodhi_ordinal"))
        self.assertEqual(k.policy.weight(None, "due_to", "descendant"), (0.5, "snomed_generalized"))
        with self.assertRaises(ValueError):
            ScoringPolicy.model_validate({**k.policy.model_dump(), "labels": {"high": 3}})
        manifest = COPY / "knowledge/manifest.json"
        previous = manifest.read_text()
        try:
            raw = json.loads(previous)
            raw["schema_version"] = "4.2"
            manifest.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                knowledge()
        finally:
            manifest.write_text(previous)

    def setUp(self):
        self.sleep = patch("workflow.io.request_executor.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def run_flow(self, client=None, r=None):
        client = client or FakeSDK()
        workflow = make_consultation(client, r or resources())
        initial = workflow.nova_session.initialize_case(client)
        result = WorkflowState.model_validate(build_graph(workflow, (r or resources()).knowledge).invoke(initial.model_dump(), {"recursion_limit": workflow.budget.graph_step_limit(initial)}))
        return result, client

    def test_full_five_session_workflow(self):
        result, client = self.run_flow()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.case.diagnosis, "가상질환B")
        self.assertEqual(client.actions[0]["content"], CONFIG.texts.chief_question)
        self.assertEqual([a["kind"] for a in client.actions], ["SAY", "SAY", "SAY", "SAY", "EXAM", "SAY", "SAY"])
        note = client.submissions[0]["note"]
        self.assertEqual({s: tuple(f) for s, f in note.items()}, RECORD_FIELDS)
        self.assertEqual(note["O"]["tests"], "")
        self.assertIn("가상소견", note["A"]["evidence"])
        self.assertIn("가상검사", note["P"]["tests"])
        self.assertEqual(result.session.doctor_calls, len(client.calls))
        self.assertEqual(result.session.input_tokens, len(client.calls) * 20)
        self.assertEqual(len(result.interaction.model_history), len(client.calls))
        self.assertEqual({call["role"] for call in result.interaction.model_history}, {"doctor", "gateway"})
        self.assertTrue(all(c["model"] == "openai/gpt-6-luna" for c in client.calls))
        (HERE / "synthetic-full-flow.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def test_prepare_and_consult_sdk_entrypoints(self):
        result = consult(FakeSDK(), prepare())
        self.assertEqual(result["interaction"]["termination"], "submitted")
        fallback = consult(FakeSDK(no_candidate=True), prepare())
        self.assertEqual(fallback["case"]["diagnosis_kind"], "symptom")

    def test_zero_context_bonus_and_no_candidates(self):
        s, _ = self.run_flow(FakeSDK(context="아니요"))
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertTrue(all(h.context_bonus == 0 for h in s.differential.hypotheses))
        s, client = self.run_flow(FakeSDK(no_candidate=True))
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(s.case.diagnosis_kind, "symptom")
        self.assertEqual(s.case.diagnosis, "별도증상")
        self.assertEqual(s.session.clarifications, 2)
        self.assertFalse(s.differential.hypotheses)
        self.assertEqual(client.submissions[0]["note"]["P"]["treatment"], "")
        self.assertIn("원인 미확정", client.submissions[0]["note"]["A"]["evidence"])

    def test_pure_routes_initialization_pending_and_current_scope(self):
        s = state()
        self.assertEqual(route_budget(s), "enter_session")
        q = question(s)
        pending(s, q)
        self.assertEqual(route_budget(s), "process_input")
        s.interaction.pending = None
        s.session.initialized = True
        s.case.get(q.item_id).scope = "Education"
        self.assertEqual(route_budget(s), "advance_session")
        s.case.get(q.item_id).scope = "Initiation"
        s.differential.hypotheses = [Hypothesis(disease_id=str(OW.Alpha), evidence_score=100)]
        self.assertEqual(route_budget(s), "select_question")
        client = FakeSDK()
        w = make_consultation(client, resources())
        s = state("DifferentialDiagnosis")
        s.differential.hypotheses = [Hypothesis(disease_id=str(OW.Alpha), context_bonus=0)]
        w.enter_session(s)
        self.assertIsNone(s.interaction.termination)
        self.assertFalse(client.calls)

    def test_budget_prunes_both_records_and_refs_preserves_open(self):
        s = state("ChiefComplaint", True)
        interview = make_planner(knowledge(), CONFIG)
        record(s)
        interview.prepare_chief_complaint(s)
        s.session.limits["ChiefComplaint"].actions = 2
        make_consultation().check_budget(s)
        ids = {q.item_id for q in s.questions.questions}
        self.assertIn("ChiefComplaint:open", ids)
        self.assertTrue(any(str(OW.Location) in ident for ident in ids))
        self.assertFalse(any(str(OW.Quality) in item.id for _, item in s.case.entries()))
        before = s.model_dump()
        make_consultation(FakeSDK(), resources()).enter_session(s)
        self.assertEqual(before, s.model_dump())
        self.assertEqual({i.id for i in s.case.unasked("ChiefComplaint")}, ids)

    def test_budget_keeps_pending_done_and_plans(self):
        s = state("Education", True)
        record(s)
        record(s, ident="plan", kind="plan", field="P.education")
        q = question(s, purpose="education", field="P.education")
        pending(s, q)
        s.session.limits["Education"].actions = 0
        make_consultation().check_budget(s)
        self.assertIsNotNone(s.case.get("q"))
        s.interaction.pending = None
        make_consultation().check_budget(s)
        self.assertIsNone(s.case.get("q"))
        self.assertIsNotNone(s.case.get("chief"))
        self.assertIsNotNone(s.case.get("plan"))

    def test_parsing_budget_is_reserved_before_action(self):
        s = state("ContextFactor", True)
        question(s, target=OW.Context, purpose="context")
        s.session.call_limit = 0
        make_consultation().check_budget(s)
        self.assertFalse(s.case.unasked("ContextFactor"))
        self.assertFalse(s.questions.questions)
        self.assertEqual(s.session.usage["ChiefComplaint"].calls, 0)

    def test_score_dedup_correction_episodes_and_context(self):
        k = knowledge()
        k._graph.add((OW.alphaLocation, OW.sourceRef, Literal("synthetic:second-source")))
        k.validate_graph()
        s = state("DifferentialDiagnosis", True)
        record(s)
        record(s, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        r = ClinicalReasoner(k)
        r.retrieve_candidates(s)
        self.assertEqual([(h.disease_id, h.evidence_score) for h in s.differential.hypotheses], [(str(OW.Alpha), 2), (str(OW.Beta), 2)])
        r.refresh_hypotheses(s)
        self.assertEqual(s.differential.hypotheses[0].score, 2)
        s.case.get("location").value.status = "absent"
        r.refresh_hypotheses(s)
        self.assertEqual(s.differential.hypotheses[0].score, 1)
        s.case.get("location").value.episode_id = "other-episode"
        r.refresh_hypotheses(s)
        self.assertEqual(s.differential.hypotheses[0].score, 1)
        for status in ("absent", "unknown", "uncertain", "present"):
            record(s, "context", OW.Context, "context", status, "S.pmh")
            record(s, "context-duplicate", OW.Context, "context", status, "S.pmh")
            r.refresh_hypotheses(s)
            alpha = next(h for h in s.differential.hypotheses if h.disease_id == str(OW.Alpha))
            self.assertEqual(alpha.context_bonus, int(status == "present"))

    def test_relation_weight_and_ambiguous_recall(self):
        s = state("DifferentialDiagnosis", True)
        record(s)
        record(s, "exam", OW.ExamX, "finding", field="O.exam")
        r = ClinicalReasoner(knowledge())
        r.retrieve_candidates(s)
        self.assertEqual(s.differential.hypotheses[0].disease_id, str(OW.Beta))
        self.assertEqual(s.differential.hypotheses[0].evidence_score, 3)
        s.case.get("exam").value.status = "unknown"
        s.case.get("chief").value.status = "uncertain"
        s.case.get("chief").value.concept_ids.append(str(OW.Other))
        r.refresh_hypotheses(s)
        self.assertTrue(all(h.evidence_score == 0 for h in s.differential.hypotheses))

    def test_strict_reply_vs_compound_free_text(self):
        s = state("ContextFactor", True)
        q = question(s, purpose="context", target=OW.Context, field="S.pmh")
        pending(s, q)
        gateway = make_interpreter(CONFIG)
        self.assertEqual(fixed_reply(CONFIG, s, "아니요.").facts[0].value.status, "absent")
        self.assertIsNone(fixed_reply(CONFIG, s, "아니요, 하지만 어제는 있었어요"))
        self.assertEqual(fixed_reply(CONFIG, s, "모르겠어요").facts, [])
        s.interaction.incoming = {"content": "모르겠어요"}
        client = FakeSDK()
        gateway.process_input(s, knowledge(), client)
        self.assertEqual(s.case.get("q").status, "done")
        self.assertEqual(s.case.get("q").value.status, "unknown")
        self.assertFalse(client.calls)

    def test_structured_and_malformed_inputs_preserve_raw(self):
        s = state()
        s.interaction.incoming = {"initial": {"opening": "가상증상", "facts": [fact("S.cc", "symptom", OW.Complaint, "가상증상")]}}
        client = FakeSDK()
        make_interpreter(CONFIG).process_input(s, knowledge(), client)
        self.assertFalse(client.calls)
        self.assertTrue(s.case.S["cc"])
        s = make_consultation().nova_session.initialize_case(FakeSDK())
        client = FakeSDK(malformed=True)
        make_interpreter(CONFIG).process_input(s, knowledge(), client)
        self.assertFalse(s.case.S["cc"])
        self.assertEqual(s.interaction.history[0].response["opening"], "가상증상이 있어요")
        self.assertEqual(len(client.calls), 1)
        self.assertIn("invalid_gateway_output", s.interaction.issues)

    def test_fact_grounding_and_correction_boundary(self):
        s = state()
        gateway = make_interpreter(CONFIG)
        forged = fact("O.exam", "finding", OW.ExamX, "reported")
        self.assertIsNone(gateway._validate_facts({"facts": [forged]}, s, knowledge(), "reported"))
        record(s)
        correction = fact("S.cc", "symptom", OW.Complaint, "correction", status="absent")
        correction["record_id"] = "chief"
        parsed = gateway._validate_facts({"facts": [correction]}, s, knowledge(), "correction")
        self.assertIsNotNone(parsed)
        gateway._apply_facts(s, parsed, "correction-source")
        self.assertEqual(s.case.get("chief").value.status, "absent")
        self.assertEqual(s.case.get("chief").source_refs, ["source", "correction-source"])
        correction["value"]["episode_id"] = "different"
        self.assertIsNone(gateway._validate_facts({"facts": [correction]}, s, knowledge(), "correction"))

    def test_invalid_answer_target_and_missing_response(self):
        s = state("ChiefComplaint", True)
        q = question(s, target=OW.Complaint, purpose="hpi", attribute=OW.Location, field="S.hpi")
        pending(s, q)
        wrong = fact("S.hpi", "attribute", OW.Complaint, "reply", q=q.model_dump(), attribute=OW.Quality, values=[OW.Dull])
        gateway = make_interpreter(CONFIG)
        self.assertIsNone(gateway._validate_facts({"facts": [wrong]}, s, knowledge(), "reply"))
        gateway.process_input(s, knowledge(), FakeSDK())
        self.assertEqual(s.interaction.termination, "unknown")
        self.assertEqual(s.interaction.pending.request_id, "request-1")

    def test_packaging_configured_texts_and_exclusions(self):
        package_copy = RUN / "packaging-copy"
        shutil.copytree(SOURCE, package_copy, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        spec = importlib.util.spec_from_file_location("packaging_check", PROJECT / "Dev/packaging/package_submission.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.SOURCE = package_copy
        module.OUTPUT = HERE / "configured-texts.zip"
        import settings
        with patch.object(settings, "ROOT", package_copy), patch("builtins.print"):
            module.main()
            with ZipFile(module.OUTPUT) as archive:
                self.assertEqual(archive.read("nova_sdk.py"), (SOURCE / "nova_sdk.py").read_bytes())
                self.assertIn("config/input_parser.txt", archive.namelist())
                self.assertIn("config/doctor.txt", archive.namelist())
                self.assertIn("config/texts.ko.json", archive.namelist())
                self.assertFalse(any("README" in n or "PROJECT_STATE" in n or "AGENTS" in n or "__pycache__" in n for n in archive.namelist()))
                self.assertFalse(any("fixture" in n for n in archive.namelist()))
                if SOURCE_MANIFEST.exists():
                    manifest = json.loads(archive.read("knowledge/manifest.json"))
                    for asset in manifest["bundles"]:
                        self.assertEqual(hashlib.sha256(archive.read(asset["path"])).hexdigest(), asset["sha256"])
                        self.assertNotEqual(archive.read(asset["path"]).decode(), TTL)
                else:
                    self.assertFalse(any("clinical.ttl" in n for n in archive.namelist()))
            (package_copy / "config/input_parser.txt").rename(package_copy / "config/custom-parser.txt")
            public = package_copy / ".env"
            public.write_text(public.read_text().replace("config/input_parser.txt", "config/custom-parser.txt"))
            module.main()
            with ZipFile(module.OUTPUT) as archive:
                self.assertIn("config/custom-parser.txt", archive.namelist())
                self.assertNotIn("config/input_parser.txt", archive.namelist())
            (package_copy / "config/custom-parser.txt").unlink()
            with self.assertRaisesRegex(ValueError, "Missing runtime files"):
                module.main()

    def test_nfc_length_and_test_block(self):
        interface = make_doctor(CONFIG)
        for content, allowed in (("가" * 30, True), ("가" * 31, False), ("가" * 30, True), ("", False)):
            s = state("DifferentialDiagnosis", True)
            q = question(s, text=content)
            s.interaction.selected = ActionSpec(question=q, content=content, request_id="length")
            s.session.models_available = False
            interface.validate_action(s)
            self.assertEqual(s.interaction.selected is not None, allowed)
        with self.assertRaises(ValueError):
            Question(item_id="test", field="O.tests", kind="TEST", purpose="feature", text="test", order=0, priority=0)

    def test_exam_refusal_and_unknown_delivery(self):
        s, client = self.run_flow(FakeSDK(refusal=True))
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(sum(a["kind"] == "EXAM" for a in client.actions), 1)
        refused = client.submissions[0]["note"]["O"]["exam"]
        self.assertIn("가상소견", refused)
        self.assertIn(": 미확인", refused)
        self.assertNotIn("가상소견", client.submissions[0]["note"]["A"]["evidence"])
        self.assertFalse(any(item.value.kind == "finding" and str(OW.ExamX) in item.value.concept_ids
                             for _, item in s.case.entries() if item.value))
        s, client = self.run_flow(FakeSDK(unknown_action=True))
        self.assertEqual(s.interaction.termination, "unknown")
        self.assertEqual(len(client.actions), 3)
        self.assertEqual(len({action["request_id"] for action in client.actions}), 1)
        self.assertIsNotNone(s.interaction.pending)
        self.assertEqual(s.interaction.history[-1].request["request_id"], client.actions[0]["request_id"])
        self.assertFalse(client.submissions)

    def test_submission_unknown_keeps_exact_payload(self):
        for result in ("timeout", "not_completed"):
            s, client = self.run_flow(FakeSDK(submit_status=result))
            self.assertEqual(s.interaction.termination, "unknown")
            self.assertEqual(len(client.submissions), 3 if result == "timeout" else 1)
            self.assertEqual(len({item["request_id"] for item in client.submissions}), 1)
            self.assertEqual(client.submissions[0]["request_id"], s.interaction.submission_request_id)
            self.assertEqual(client.submissions[0]["note"], s.interaction.submission_payload["note"])

    def test_closed_expired_reserve_and_fiftieth_turn(self):
        for status, expected in (("closed", "closed"), ("expired", "expired")):
            client = FakeSDK()
            client.status = status
            s, client = self.run_flow(client)
            self.assertEqual(s.interaction.termination, expected)
            self.assertFalse(client.calls)
        s = state("ChiefComplaint", True)
        question(s, ident="unasked-at-reserve")
        s.session.deadline = datetime.now(timezone.utc) + timedelta(seconds=119)
        make_consultation().check_budget(s)
        self.assertTrue(s.session.finalizing)
        self.assertIsNone(s.case.get("unasked-at-reserve"))
        self.assertFalse(s.questions.questions)
        make_consultation(FakeSDK(), resources()).finalize(s)
        self.assertEqual(s.interaction.reason, "no_supported_diagnosis")
        s = state("DifferentialDiagnosis", True, turns=1)
        s.session.doctor_successes = 1
        s.differential.initialized = True
        record(s)
        client = FakeSDK()
        client.remaining = 1
        q = question(s, target=OW.ExamX, kind="EXAM", field="O.exam", text="가상 진찰을 하겠습니다")
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="last-turn", ready=True)
        make_doctor(CONFIG).execute_action(s, client)
        make_interpreter(CONFIG).process_input(s, knowledge(), client)
        make_consultation().check_budget(s)
        self.assertEqual(s.session.turns_remaining, 0)
        submission = make_writer(client, knowledge(), CONFIG)
        make_consultation(client, resources()).finalize(s)
        submission.submit_diagnosis(s)
        submission.confirm_submission(s)
        self.assertEqual(s.interaction.termination, "submitted")

        self.assertEqual(s.case.diagnosis, "가상질환B")
        self.assertIn("턴 50", s.interaction.submission_payload["note"]["O"]["exam"])

    def test_soap_exact_fields_bytes_and_doctor_requirement(self):
        s, _ = self.run_flow()
        agent = make_writer(FakeSDK(), knowledge(), CONFIG)
        variants = []
        for kind in ("extra", "missing", "number", "record_bytes", "diagnosis_bytes", "doctor"):
            t = s.model_copy(deep=True)
            t.interaction.termination = None
            note = t.interaction.submission_payload["note"]
            if kind == "extra": note["A"]["diagnosis"] = "bad"
            if kind == "missing": del note["S"]["cc"]
            if kind == "number": note["S"]["cc"] = 3
            if kind == "record_bytes": note["S"]["hpi"] = "가" * 33334
            if kind == "diagnosis_bytes": t.interaction.submission_payload["diagnosis"] = "가" * 167
            if kind == "doctor": t.session.doctor_successes = 0
            agent.validate_submission(t)
            self.assertIsNotNone(t.interaction.submission_error, kind)
            t.interaction.submission_repairs = 1
            agent.validate_submission(t)
            self.assertEqual(t.interaction.termination, "failed", kind)

    def test_education_revision_preserves_delivered_and_budget(self):
        s = state("Education", True)
        s.differential.selected_id = str(OW.Beta)
        agent = make_planner(knowledge(), CONFIG)
        s.case.diagnosis_kind = "disease"
        agent.prepare_education(s)
        delivered = s.questions.questions[0]
        s.case.get(delivered.item_id).status = "done"
        s.case.get(delivered.item_id).value = ClinicalValue(kind="education", text=delivered.text, status="present")
        s.case.get(delivered.item_id).source_refs = ["delivered"]
        s.differential.selected_id = str(OW.Alpha)
        agent.prepare_education(s, replace=True)
        self.assertEqual(len(s.case.unasked("Education")), 1)
        self.assertIsNotNone(s.case.get(delivered.item_id))
        self.assertEqual(s.case.get("plan:education").value.concept_ids, [str(OW.Alpha)])
        self.assertEqual(s.session.current, "Education")

    def test_missing_plan_question_and_observed_past(self):
        k = knowledge()
        k.plans = {}
        k.questions = {}
        s, client = self.run_flow(r=resources(k))
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertTrue(any(issue.startswith("missing_template:") for issue in s.interaction.issues))
        self.assertTrue(any(issue.startswith("missing_plan:") for issue in s.interaction.issues))
        self.assertEqual(s.case.P["treatment"], {})
        s = state()
        record(s)
        s.case.get("chief").value.time_context = "past"
        self.assertFalse(InterviewPlanner.has_resolved_evidence(s, str(OW.Complaint)))

    def test_knowledge_paths_hashes_and_missing_manifest(self):
        for path in ("../data/schema.ttl", "/tmp/external.ttl", "config/texts.ko.json"):
            with self.assertRaises(ValueError): knowledge_path(path)
        with self.assertRaises(FileNotFoundError):
            ClinicalKnowledge.load(COPY / "knowledge/missing.json")
        link = COPY / "knowledge/escape.ttl"
        link.unlink(missing_ok=True)
        link.symlink_to(HERE / "outside.ttl")
        with self.assertRaises(ValueError): knowledge_path("knowledge/escape.ttl")
        link.unlink()
        asset = COPY / "knowledge/clinical.ttl"
        old = asset.read_bytes()
        try:
            asset.write_bytes(old + b"\n")
            with self.assertRaisesRegex(ValueError, "digest mismatch"): knowledge()
        finally:
            asset.write_bytes(old)
        self.assertEqual(hashlib.sha256(SOURCE_MANIFEST.read_bytes()).hexdigest() if SOURCE_MANIFEST.exists() else None,
                         SOURCE_MANIFEST_HASH)

    def test_doctor_regeneration_fallback_and_no_draft_delivery(self):
        for outputs, expected, source in ((["가" * 31, "", "무엇이 불편하세요?"], "무엇이 불편하세요?", "doctor"),
                                           (["가" * 31] * 3, CONFIG.texts.chief_question, "prepared")):
            s = state()
            interview = make_planner(knowledge(), CONFIG)
            interview.prepare_initiation(s)
            interview.select_question(s)
            client = FakeSDK()
            client.chat = Mock(side_effect=[client.completion(text) for text in outputs])
            interface = make_doctor(CONFIG)
            for _ in outputs:
                interface.frame_action(s, client)
                interface.validate_action(s)
                self.assertFalse(client.actions)
                self.assertEqual(s.interaction.dialogue(), [])
            selected = s.interaction.selected
            self.assertEqual((selected.content, selected.render_source, selected.render_attempts), (expected, source, 3))
            messages = client.chat.call_args_list
            self.assertEqual(json.loads(messages[1].kwargs["messages"][1]["content"])["validation_feedback"],
                             {"error": "content_too_long", "codepoints": 31})
            self.assertEqual(len({call.kwargs["request_id"] for call in messages}), 3)
            interface.execute_action(s, client)
            self.assertEqual([a["content"] for a in client.actions], [expected])
            self.assertEqual(s.interaction.dialogue()[0]["doctor"], expected)
        s = state()
        q = question(s, text="가" * 31)
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="invalid")
        s.session.models_available = False
        interface.validate_action(s)
        self.assertIsNone(s.interaction.selected)
        self.assertEqual(s.case.get(q.item_id).value.status, "unknown")
        self.assertEqual(content_error("가" * 29 + "\n"), None)
        self.assertEqual(content_error("가" * 30 + "\n"), "content_too_long")

    def test_actual_korean_context_short_answer_and_case_isolation(self):
        s = state("ChiefComplaint", True)
        q = question(s, purpose="ros", text="별도증상이 있나요?")
        for index in range(6):
            s.interaction.history.append(InteractionEntry(id=f"past-{index}", kind="SAY", delivered=True,
                turn=index + 1, question=q, request={"content": "어디가 불편하세요?"}, response={"content": "거기도요"}))
        s.interaction.history.append(InteractionEntry(id="unsent", kind="SAY", request={"content": "유령 질문"}))
        s.interaction.model_history.append({"role": "doctor", "draft": "유령 출력"})
        pending(s, q)
        s.interaction.pending.content = "별도증상은 없으시죠?"
        s.interaction.pending.render_source = "doctor"
        s.interaction.incoming = {"content": "네"}
        answer = fact("S.ros", "symptom", OW.Other, "네", q=q.model_dump(), status="absent")
        answer["context_refs"] = ["past-0"]
        client = FakeSDK()
        client.chat = Mock(return_value=client.completion(json.dumps({"facts": [answer]}, ensure_ascii=False)))
        gateway = make_interpreter(CONFIG)
        self.assertIsNone(fixed_reply(CONFIG, s, "네"))
        gateway.process_input(s, knowledge(), client)
        payload = json.loads(client.chat.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload["spoken_question"], "별도증상은 없으시죠?")
        self.assertEqual(payload["question"]["text"], "별도증상이 있나요?")
        self.assertEqual(len(payload["dialogue"]), 6)
        self.assertEqual(s.case.get("q").value.status, "absent")
        self.assertEqual(s.case.get("q").context_refs, ["past-0"])
        self.assertNotIn("유령", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(state().interaction.dialogue(), [])
        answer["context_refs"] = ["unsent"]
        self.assertIsNone(gateway._validate_facts({"facts": [answer]}, s, knowledge(), "네"))
        answer["context_refs"] = []
        answer["quote"] = answer["value"]["text"] = "의사가 한 말"
        self.assertIsNone(gateway._validate_facts({"facts": [answer]}, s, knowledge(), "네"))
        s.interaction.pending = ActionSpec(question=q, content=q.text, request_id="prepared")
        q.affirmative_presence = False
        self.assertIsNone(fixed_reply(CONFIG, s, "네"))

    def test_contextual_correction_preserves_episode_and_quote(self):
        for reply in ("거기도요", "아까보다 덜해요", "아니요, 아까 말한 곳이에요"):
            s = state("ChiefComplaint", True)
            record(s, ident="location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
            s.interaction.history.append(InteractionEntry(id="earlier", kind="SAY", delivered=True,
                request={"content": "어느 부위인가요?"}, response={"content": "가상부위요"}))
            correction = fact("S.hpi", "attribute", OW.Complaint, reply, attribute=OW.Location, values=[OW.Here])
            correction.update(record_id="location", context_refs=["earlier"])
            gateway = make_interpreter(CONFIG)
            parsed = gateway._validate_facts({"facts": [correction]}, s, knowledge(), reply)
            self.assertIsNotNone(parsed)
            gateway._apply_facts(s, parsed, "current")
            self.assertEqual(s.case.get("location").value.text, reply)
            self.assertEqual(s.case.get("location").value.episode_id, "episode1")
            self.assertEqual(s.case.get("location").context_refs, ["earlier"])

    def test_focused_ros_union_limits_order_and_cross_system_retrieval(self):
        k = knowledge()
        for system in (OW.SystemA, OW.SystemB):
            k._graph.add((system, RDF.type, OW.BodySystem))
            k._graph.add((OW.Complaint, OW.inSystem, system))
        for index in range(9):
            symptom = OW[f"Ros{index}"]
            k._graph.add((symptom, RDF.type, OW.Symptom))
            for system in (OW.SystemA, OW.SystemB):
                k._graph.add((symptom, OW.inSystem, system))
        s = state("ChiefComplaint", True)
        record(s)
        record(s, ident="known", target=OW.Ros0, field="S.ros", status="absent")
        for index in range(25):
            attribute = OW[f"Attribute{index:02}"]
            k._graph.add((OW.Complaint, OW.hasAttribute, attribute))
            k._graph.add((attribute, RDF.type, OW.FindingAttribute))
            k.questions[str(attribute)] = "언제 시작되었나요?"
        interview = make_planner(k, CONFIG)
        interview.prepare_chief_complaint(s)
        make_consultation().check_budget(s)
        qs = sorted(s.questions.questions, key=lambda q: q.order)
        self.assertEqual([q.purpose for q in qs], ["hpi"] * 13 + ["open_inquiry"] + ["ros"] * 6)
        ros = [q for q in qs if q.purpose == "ros"]
        self.assertEqual([q.target_id for q in ros], [str(OW[f"Ros{i}"]) for i in range(1, 7)])
        record(s, ident="open-answer", target=OW.Ros1, field="S.ros")
        for q in qs:
            if q.purpose != "ros":
                s.case.get(q.item_id).status = "done"
        interview.select_question(s)
        self.assertEqual(s.interaction.selected.question.target_id, str(OW.Ros2))
        # A disease associated with a ROS target remains retrievable even without its own system link.
        k._graph.add((OW.Cross, RDF.type, OW.Disease))
        k._graph.add((OW.Cross, OW.hasAssociation, OW.crossAssociation))
        k._graph.add((OW.crossAssociation, RDF.type, OW.DiseasePatternAssociation))
        k._graph.add((OW.crossAssociation, OW.pattern, OW.crossPattern))
        k._graph.add((OW.crossAssociation, OW.relationBasis, Literal("associated_with")))
        k._graph.add((OW.crossAssociation, OW.sourceRef, Literal("synthetic:cross")))
        k._graph.add((OW.crossPattern, RDF.type, OW.ClinicalPattern))
        k._graph.add((OW.crossPattern, OW.targets, OW.Ros1))
        k._graph.add((OW.crossPattern, OW.hasFeature, OW.crossPresence))
        k._graph.add((OW.crossPresence, RDF.type, OW.ClinicalFeature))
        k._graph.add((OW.crossPresence, OW.expectedStatus, Literal("present")))
        k.validate_graph()
        ClinicalReasoner(k).retrieve_candidates(s)
        self.assertIn(str(OW.Cross), [h.disease_id for h in s.differential.hypotheses])
        other = state("ChiefComplaint", True)
        record(other, target=OW.Other)
        interview.prepare_chief_complaint(other)
        self.assertEqual([q.purpose for q in other.questions.questions], ["open_inquiry"])

    def test_ros_full_flow_explicit_negative_and_unknown(self):
        k = knowledge()
        k._graph.add((OW.System, RDF.type, OW.BodySystem))
        k._graph.add((OW.Complaint, OW.inSystem, OW.System))
        k._graph.add((OW.Other, OW.inSystem, OW.System))
        s, client = self.run_flow(r=resources(k))
        self.assertEqual(s.interaction.termination, "submitted")
        ros = s.case.get(f"ChiefComplaint:ros:{OW.Other}")
        self.assertEqual(ros.value.status, "absent")
        self.assertIn(ros.id, s.case.S["ros"])
        content = [a["content"] for a in client.actions]
        self.assertLess(content.index(CONFIG.texts.open_question), content.index("별도증상도 있나요?"))

    def test_clarification_is_not_dropped_as_already_known(self):
        s = state("ChiefComplaint", True)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=OW.Location, field="S.hpi")
        pending(s, q)
        s.interaction.incoming = {"content": "설명하기 어려워요"}
        make_interpreter(CONFIG).process_input(s, knowledge(), FakeSDK(malformed=True))
        self.assertTrue(s.interaction.needs_clarification)
        interview = make_planner(knowledge(), CONFIG)
        self.assertTrue(interview.prepare_clarification(s, q))
        interview.select_question(s)
        self.assertEqual(s.interaction.selected.question.purpose, "clarification")
        self.assertTrue(interview.prepare_clarification(s, q))
        self.assertFalse(interview.prepare_clarification(s, q))

    def test_empty_opening_and_no_supported_diagnosis(self):
        client = FakeSDK()
        original = client.session
        client.session = lambda: {**original(), "initial": {"opening": "", "vital_signs": {"pulse": 80}}}
        s, client = self.run_flow(client)
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(client.actions[0]["content"], CONFIG.texts.chief_question)
        self.assertEqual(s.interaction.model_history[0]["role"], "doctor")
        client = FakeSDK(malformed=True)
        s, client = self.run_flow(client)
        self.assertEqual(s.interaction.termination, "failed")
        self.assertEqual(s.session.clarifications, 2)
        self.assertEqual(len(client.actions), 3)
        self.assertFalse(client.submissions)
        s = state()
        record(s, target=OW.Other, status="uncertain")
        ClinicalReasoner(knowledge()).select_diagnosis(s)
        self.assertEqual(s.interaction.reason, "no_supported_diagnosis")
        with self.assertRaises(ValueError): finish(s)

    def test_transport_identity_delays_timeout_and_usage_once(self):
        s = state()
        client = FakeSDK()
        calls, timeouts = [], []
        def chat(**kwargs):
            calls.append(copy.deepcopy(kwargs))
            timeouts.append(client.timeout)
            if len(calls) < 3:
                raise NovaError("REQUEST_PENDING")
            return client.completion("안녕하세요")
        client.chat = chat
        with patch("workflow.io.request_executor.time.sleep") as sleep:
            self.assertEqual(make_consultation().interpreter.model.complete(s, client, role="doctor", messages=[]), "안녕하세요")
        self.assertEqual(calls, [calls[0]] * 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5])
        self.assertEqual(timeouts, [240] * 3)
        self.assertEqual(client.timeout, 120)
        self.assertEqual((s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens), (1, 20, 10))
        self.assertEqual(len(s.interaction.model_history), 1)
        s.session.deadline = datetime.now(timezone.utc) + timedelta(seconds=125)
        seen = []
        make_consultation().doctor.executor.execute(s, client, lambda: seen.append(client.timeout), {}, [])
        self.assertLessEqual(seen[0], 5)

    def test_action_retries_and_response_format_new_identity(self):
        for code, same_id in (("REQUEST_PENDING", True), ("PATIENT_RESPONSE_INVALID", False)):
            s = state()
            q = question(s, text=CONFIG.texts.chief_question, purpose="chief", field="S.cc", target=None)
            s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="first", ready=True)
            client, requests = FakeSDK(), []
            real = client.say
            def say(**kwargs):
                requests.append(kwargs)
                if len(requests) == 1:
                    raise NovaError(code)
                return real(**kwargs)
            client.say = say
            make_doctor(CONFIG).execute_action(s, client)
            self.assertEqual(requests[0]["request_id"] == requests[1]["request_id"], same_id)
            self.assertEqual(requests[0]["content"], requests[1]["content"])
            self.assertEqual(s.session.usage["Initiation"].actions, 1)
            self.assertEqual(len(s.interaction.dialogue()), 1)

    def test_shared_budget_reserves_gateway_and_finalizes(self):
        s = state()
        s.session.call_limit = 3
        q = question(s, purpose="chief", text=CONFIG.texts.chief_question, field="S.cc", target=None)
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="budget")
        client = FakeSDK()
        client.chat = Mock(return_value=client.completion("가" * 31))
        interface = make_doctor(CONFIG)
        for _ in range(2):
            interface.frame_action(s, client)
            interface.validate_action(s)
        self.assertTrue(s.interaction.selected.ready)
        self.assertEqual(s.interaction.selected.render_source, "prepared")
        self.assertEqual(BudgetPolicy().calls_left(s.session), 1)
        interface.execute_action(s, client)
        client.chat = Mock(return_value=client.completion(json.dumps({"facts": [fact("S.cc", "symptom", OW.Other, "가상증상이 있어요", q=q.model_dump())]}, ensure_ascii=False)))
        make_interpreter(CONFIG).process_input(s, knowledge(), client)
        self.assertEqual(BudgetPolicy().calls_left(s.session), 0)
        make_consultation().check_budget(s)
        workflow = make_consultation(client, resources())
        workflow.finalize(s)
        workflow.writer.submit_diagnosis(s)
        workflow.writer.confirm_submission(s)
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(s.case.diagnosis_kind, "symptom")
        s = state()
        s.session.output_tokens = s.session.output_token_limit - 2048
        self.assertFalse(interface.budget.can_frame(s, ActionSpec(question=q, content=q.text, request_id="tokens")))

    def test_soap_reconstruction_local_and_server(self):
        s, _ = self.run_flow()
        s.interaction.termination = None
        s.interaction.submission_payload["note"]["A"]["diagnosis"] = "invalid"
        workflow = make_consultation(FakeSDK(), resources())
        workflow.writer.validate_submission(s)
        self.assertIsNotNone(s.interaction.submission_error)
        workflow.repair_submission(s)
        workflow.writer.validate_submission(s)
        self.assertIsNone(s.interaction.submission_error)
        self.assertNotIn("diagnosis", s.interaction.submission_payload["note"]["A"])
        for failures, expected in ((1, "submitted"), (2, "failed")):
            client, submissions = FakeSDK(), []
            def diagnose(**kwargs):
                submissions.append(copy.deepcopy(kwargs))
                if len(submissions) <= failures:
                    raise NovaError("INVALID_RECORD_FIELDS")
                return {"status": "completed"}
            client.diagnose = diagnose
            s, _ = self.run_flow(client)
            self.assertEqual(s.interaction.termination, expected)
            self.assertEqual(s.interaction.submission_repairs, 1)
            self.assertEqual(len(submissions), 2)
            self.assertNotEqual(submissions[0]["request_id"], submissions[1]["request_id"])

    def test_delivered_education_survives_gateway_failure(self):
        s = state("Education", True)
        record(s)
        q = question(s, text="준비된 안내입니다.", purpose="education", field="P.education", target=None)
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="education", ready=True)
        client = FakeSDK(malformed=True)
        client._reply = lambda *args, **kwargs: {"status": "OK", "turn": 1, "turns_remaining": 49, "content": "새로운 증상이 있어요"}
        make_doctor(CONFIG).execute_action(s, client)
        make_interpreter(CONFIG).process_input(s, knowledge(), client)
        self.assertEqual(s.case.get(q.item_id).value.kind, "education")
        self.assertEqual(s.case.get(q.item_id).value.text, q.text)
        self.assertTrue(s.interaction.needs_clarification)
        interview = make_planner(knowledge(), CONFIG)
        interview.prepare_clarification(s, s.interaction.clarification_target)
        clarification = s.questions.questions[-1]
        self.assertEqual(clarification.field, "S.ros")
        self.assertFalse(hasattr(SubmissionWriter, "prepare_education"))

    def test_text_environment_overrides_and_invalid_config(self):
        alternate = COPY / "config/review-parser.txt"
        alternate.write_text(CONFIG.parser_prompt + "\nPreserve this review marker.", encoding="utf-8")
        texts = CONFIG.texts.model_dump()
        texts["open_question"] = "추가 증상을 알려주시겠어요?"
        alternate_text = COPY / "config/review-texts.json"
        alternate_text.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        with patch.dict(os.environ, {"ONTOWARD_PARSER_PROMPT": "config/review-parser.txt", "ONTOWARD_TEXTS": "config/review-texts.json"}):
            config = TextConfig.load()
            self.assertIn("review marker", config.parser_prompt)
            s = state("ChiefComplaint")
            make_planner(knowledge(), config).prepare_open_inquiry(s, 0)
            self.assertEqual(s.questions.questions[0].text, texts["open_question"])
        with patch.dict(os.environ, {"ONTOWARD_PARSER_PROMPT": "../outside.txt"}):
            with self.assertRaises(ValueError): TextConfig.load()
        texts["absent_replies"].append("네")
        alternate_text.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        with patch.dict(os.environ, {"ONTOWARD_TEXTS": "config/review-texts.json"}):
            with self.assertRaises(ValueError): TextConfig.load()

    def test_new_fact_during_education_changes_remaining_delivery(self):
        k = knowledge()
        k._graph.parse(data='''@prefix ow: <urn:ontoward:> .
          @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
          ow:Gamma a ow:Disease; rdfs:label "가상질환C"@ko; ow:hasAssociation ow:ga1, ow:ga2, ow:ga3 .
          ow:ga1 a ow:DiseasePatternAssociation; ow:pattern ow:g1; ow:relationBasis "due_to"; ow:sourceRef "synthetic:g1" .
          ow:ga2 a ow:DiseasePatternAssociation; ow:pattern ow:g2; ow:relationBasis "due_to"; ow:sourceRef "synthetic:g2" .
          ow:ga3 a ow:DiseasePatternAssociation; ow:pattern ow:g3; ow:relationBasis "due_to"; ow:sourceRef "synthetic:g3" .
          ow:g1 a ow:ClinicalPattern; ow:targets ow:Complaint; ow:hasFeature ow:g1f .
          ow:g2 a ow:ClinicalPattern; ow:targets ow:ExamX; ow:hasFeature ow:g2f .
          ow:g3 a ow:ClinicalPattern; ow:targets ow:Other; ow:hasFeature ow:g3f .
          ow:g1f a ow:ClinicalFeature; ow:expectedStatus "present" .
          ow:g2f a ow:ClinicalFeature; ow:expectedStatus "present" .
          ow:g3f a ow:ClinicalFeature; ow:expectedStatus "present" .''', format="turtle")
        k.validate_graph()
        k.plans[str(OW.Gamma)] = Plan(treatment="가상 C 계획", education=["가상 C 안내입니다."])
        client = FakeSDK()
        original_chat, original_reply = client.chat, client._reply
        def reply(text, request_id, exam=False):
            result = original_reply(text, request_id, exam)
            if text == "가상 B 첫 안내입니다.":
                result["content"] = "별도증상도 있어요"
            return result
        def chat(messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            if messages[0]["content"] == CONFIG.parser_prompt and payload["input"] == "별도증상도 있어요":
                client.calls.append({"messages": messages, **kwargs})
                return client.completion(json.dumps({"facts": [fact("S.ros", "symptom", OW.Other, payload["input"])]}, ensure_ascii=False))
            return original_chat(messages, **kwargs)
        client._reply, client.chat = reply, chat
        s, client = self.run_flow(client, resources(k))
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(s.case.diagnosis, "가상질환C")
        delivered = [a["content"] for a in client.actions]
        self.assertIn("가상 B 첫 안내입니다.", delivered)
        self.assertIn("가상 C 안내입니다.", delivered)
        self.assertNotIn("가상 B 둘째 안내입니다.", delivered)
        self.assertEqual(s.session.usage["Education"].actions, 2)
        self.assertIn("가상 C 계획", client.submissions[0]["note"]["P"]["treatment"])

    def test_model_limit_finalization_and_clarification_candidate_recovery(self):
        for code in ("MODEL_CALL_LIMIT", "MODEL_TOKEN_BUDGET"):
            client, count = FakeSDK(), [0]
            original = client.chat
            def chat(messages, **kwargs):
                count[0] += 1
                if count[0] == 2:
                    raise NovaError(code)
                return original(messages, **kwargs)
            client.chat = chat
            s, client = self.run_flow(client)
            self.assertEqual(s.interaction.termination, "submitted")
            self.assertIn(code, s.interaction.issues)
            self.assertEqual(count[0], 2)
        client = FakeSDK(no_candidate=True)
        original = client.chat
        def chat(messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            if messages[0]["content"] == CONFIG.parser_prompt and payload["question"] and payload["question"]["purpose"] == "clarification":
                client.no_candidate = False
            return original(messages, **kwargs)
        client.chat = chat
        s, client = self.run_flow(client)
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(s.case.diagnosis_kind, "disease")
        self.assertEqual(s.session.clarifications, 1)

    def test_shared_resources_keep_case_dialogue_separate(self):
        r = resources()
        first, _ = self.run_flow(r=r)
        second, client = self.run_flow(FakeSDK(no_candidate=True), r)
        first_ids = {row["id"] for row in first.interaction.dialogue() if row["id"] != "initial"}
        second_ids = {row["id"] for row in second.interaction.dialogue() if row["id"] != "initial"}
        self.assertTrue(first_ids.isdisjoint(second_ids))
        first_doctor = next(c for c in client.calls if c["messages"][0]["content"] == CONFIG.doctor_prompt)
        view = json.loads(first_doctor["messages"][1]["content"])["dialogue"]
        self.assertEqual([row["id"] for row in view], ["initial"])

    def test_whitespace_feedback_and_unknown_usage_stop_collection(self):
        s = state()
        q = question(s, text=CONFIG.texts.chief_question)
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="blank")
        client = FakeSDK()
        client.chat = Mock(return_value=client.completion("   "))
        interface = make_doctor(CONFIG)
        interface.frame_action(s, client)
        interface.validate_action(s)
        self.assertEqual(s.interaction.selected.feedback, {"error": "empty_content", "codepoints": 3})
        client.chat = Mock(return_value={"choices": [{"message": {"content": "text"}}]})
        self.assertIsNone(make_consultation().interpreter.model.complete(s, client, role="gateway", messages=[]))
        self.assertFalse(s.session.models_available)

    def test_pinned_sdk_wire_with_local_response_double(self):
        sdk = Client(api_base="https://offline.invalid", token="synthetic", session_id="synthetic-case")
        server, wire = FakeSDK(), []
        def request(method, path, body=None):
            wire.append({"method": method, "path": path, "body": copy.deepcopy(body)})
            if method == "GET":
                return server.session()
            payload = dict(body)
            if path == "/v1/chat/completions":
                payload.pop("session_id")
                return server.chat(**payload)
            action = payload.pop("action")
            return {"SAY": server.say, "EXAM": server.exam, "DIAGNOSE": server.diagnose}[action](**payload)
        sdk._request = request
        result = consult(sdk, resources())
        self.assertEqual(result["interaction"]["termination"], "submitted")
        actions = [row["body"] for row in wire if row["path"] == "/v1/session/actions"]
        self.assertEqual(actions[0]["action"], "SAY")
        self.assertEqual(actions[-1]["action"], "DIAGNOSE")
        self.assertEqual(set(actions[-1]), {"request_id", "action", "note", "diagnosis"})
        self.assertEqual(sum(len(section) for section in actions[-1]["note"].values()), 15)
        self.assertTrue(all(len(a["content"]) <= 30 for a in actions[:-1]))
        (HERE / "synthetic-sdk-wire.json").write_text(json.dumps(wire, ensure_ascii=False, indent=2))


    def test_asked_history_does_not_resolve_unknown_or_empty_attribute(self):
        s = state("DifferentialDiagnosis", True)
        record(s)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=OW.Location, field="S.hpi")
        q.observation_id, q.episode_id = "obs1", "episode1"
        pending(s, q)
        s.interaction.history.append(InteractionEntry(id="request-1", kind="SAY", question=q, delivered=True))
        planner = make_planner(knowledge(), CONFIG)
        planner.questions.complete_unresolved(s, s.interaction.pending, "모르겠어요", "request-1")
        planner.interactions.consume_input(s)
        args = (s, str(OW.Complaint), str(OW.Location), "obs1", "episode1")
        self.assertTrue(planner.was_asked(*args))
        self.assertFalse(planner.has_resolved_evidence(*args))
        ClinicalReasoner(knowledge()).retrieve_candidates(s)
        planner.prepare_differential_questions(s)
        self.assertTrue(any(item.purpose == "clarification" for item in s.questions.questions))
        record(s, ident="clarified", field="S.hpi", kind="attribute", attribute=OW.Location, values=[OW.Here])
        self.assertTrue(planner.has_resolved_evidence(*args))
        s.case.get("clarified").value.values = []
        self.assertFalse(planner.has_resolved_evidence(*args))
        self.assertFalse(planner.was_asked(s, str(OW.Other)))
        ros = Question(item_id="ros-unknown", field="S.ros", purpose="ros", target_id=str(OW.Other), text="별도증상 있나요?", order=0, priority=1)
        s.interaction.history.append(InteractionEntry(id="ros-request", kind="SAY", question=ros, delivered=True))
        record(s, ident="ros-fact", target=OW.Other, status="uncertain", episode="new-episode", field="S.ros")
        s.case.get("ros-fact").source_refs = ["ros-request"]
        self.assertTrue(planner.was_asked(s, str(OW.Other), observation="obs1", episode="new-episode"))
        self.assertFalse(planner.was_asked(s, str(OW.Other), observation="obs1", episode="separate-episode"))
        self.assertFalse(planner.has_resolved_evidence(s, str(OW.Other)))

    def test_soap_preserves_subject_time_episode_values_and_calendar_units(self):
        k = knowledge()
        from rdflib import RDFS
        for key, label in ((OW.Left, "왼쪽"), (OW.Right, "오른쪽"), (OW.Laterality, "좌우"),
                           (OW.EpisodeDuration, "한 번의 지속시간")):
            k._graph.add((key, RDFS.label, Literal(label, lang="ko")))
        writer = make_writer(FakeSDK(), k, CONFIG)
        item = RecordItem(id="private-request", scope="ChiefComplaint", status="done", source_refs=["source"],
            value=ClinicalValue(kind="attribute", text="네", status="present", concept_ids=[str(OW.Complaint)],
                attribute_id=str(OW.Laterality), values=[str(OW.Left)], subject="patient", time_context="current",
                observation_id="private-observation", episode_id="private-episode"))
        left = writer._describe_record(item)
        changed = item.model_copy(deep=True)
        changed.value.values = [str(OW.Right)]
        self.assertNotEqual(left, writer._describe_record(changed))
        changed.value.time_context, changed.value.subject = "past", "family"
        self.assertIn("가족 · 과거", writer._describe_record(changed))
        self.assertNotIn("private-", left)
        measured = item.model_copy(deep=True)
        measured.value.values, measured.value.attribute_id = [], str(OW.EpisodeDuration)
        measured.value.measurement = ExpectedValue(kind="interval", lower=1.0, upper=2.0, unit="month", upper_unit="year", upper_inclusive=False)
        self.assertIn("[1 개월, 2 년)", writer._describe_record(measured))
        s = state("Education", True)
        s.case.put("S.hpi", item)
        measured.id, measured.value.episode_id = "another-record", "another-private-episode"
        s.case.put("S.hpi", measured)
        writer.build_soap(s)
        rendered = s.interaction.submission_payload["note"]["S"]["hpi"]
        self.assertIn("발현 1", rendered)
        self.assertIn("발현 2", rendered)

    def test_differential_shares_support_policy_and_excludes_primary(self):
        s, k = state("Education", True), knowledge()
        s.case.diagnosis, s.case.diagnosis_kind = k.label(str(OW.Beta)), "disease"
        s.differential.selected_id = str(OW.Beta)
        s.differential.hypotheses = [Hypothesis(disease_id=str(OW.Alpha), evidence_score=0, context_bonus=1),
                                     Hypothesis(disease_id=str(OW.Beta), evidence_score=0.5, context_bonus=0)]
        writer = make_writer(FakeSDK(), k, CONFIG)
        writer.build_soap(s)
        self.assertEqual(s.interaction.submission_payload["note"]["A"]["differential"], "")
        from rdflib import RDFS
        for i in range(7):
            ident = str(OW[f"Alternative{i}"])
            k._graph.add((URIRef(ident), RDFS.label, Literal(f"대안{i}", lang="ko")))
            s.differential.hypotheses.append(Hypothesis(disease_id=ident, evidence_score=0.25))
        writer.build_soap(s)
        self.assertEqual(s.interaction.submission_payload["note"]["A"]["differential"].splitlines(), [f"대안{i}" for i in range(5)])

    def test_parser_vocabulary_bounds_and_required_question_values(self):
        k, s = knowledge(), state("ChiefComplaint", True)
        from rdflib import RDFS
        for i in range(600):
            node = OW[f"Added{i:04d}"]
            k._graph.add((node, RDF.type, OW.Symptom))
            k._graph.add((node, RDFS.label, Literal(f"extra symptom {i}", lang="en")))
        for i in range(207):
            node = OW[f"Place{i:04d}"]
            k._graph.add((node, RDF.type, OW.AttributeValue))
            k._graph.add((node, RDFS.label, Literal(f"부위{i}", lang="ko")))
            k._graph.add((OW.Location, OW.canHaveValue, node))
        k.validate_graph()
        q = question(s, target=OW.Complaint, attribute=OW.Location, purpose="hpi", field="S.hpi")
        pending(s, q)
        interpreter = make_interpreter(CONFIG)
        vocabulary, size = interpreter._vocabulary(s, k, "부위206")
        ids = {entry["id"] for entry in vocabulary}
        self.assertLessEqual(len(vocabulary), 256)
        self.assertLessEqual(size, 32768)
        self.assertEqual(size, len(json.dumps(vocabulary, ensure_ascii=False, separators=(",", ":")).encode()))
        self.assertTrue(set(k.get_attribute_values(str(OW.Location))) <= ids)
        self.assertTrue({str(OW.Complaint), str(OW.Location)} <= ids)
        expanded, expanded_size = interpreter._vocabulary(s, k, "부위206", expanded=True)
        self.assertLessEqual(len(expanded), 1024)
        self.assertLessEqual(expanded_size, 131072)
        self.assertGreater(len(expanded), len(vocabulary))

    def test_parser_expands_once_and_preserves_first_valid_facts(self):
        for mode in ("resolve", "malformed", "mutate_frozen", "budget"):
            with self.subTest(mode=mode):
                k, s, client = knowledge(), state("ChiefComplaint", True), FakeSDK()
                from rdflib import RDFS
                for i in range(300):
                    node = OW[f"Added{i:04d}"]
                    k._graph.add((node, RDF.type, OW.Symptom))
                    k._graph.add((node, RDFS.label, Literal(f"unused label {i}", lang="en")))
                far = str(OW.ZzzUnlinked)
                k._graph.add((URIRef(far), RDF.type, OW.Symptom))
                k._graph.add((URIRef(far), RDFS.label, Literal("unseen terminology", lang="en")))
                k.validate_graph()
                q = question(s, purpose="open_inquiry", target=None)
                pending(s, q)
                s.interaction.incoming = {"content": "가상증상과 별도 보고"}
                first = fact("S.ros", "symptom", OW.Complaint, "가상증상")
                unlinked = fact("S.ros", "symptom", OW.Other, "별도 보고")
                unlinked["value"].update(concept_ids=[], observation_id="other-observation", episode_id="other-episode")
                payloads = []
                def chat(messages, **kwargs):
                    payload = json.loads(messages[1]["content"])
                    payloads.append(payload)
                    if payload["parser_pass"] == "primary":
                        self.assertNotIn(far, {entry["id"] for entry in payload["vocabulary"]})
                        return client.completion(json.dumps({"facts": [first, unlinked]}, ensure_ascii=False))
                    if mode == "malformed":
                        return client.completion("{invalid")
                    replacement = copy.deepcopy(payload["unlinked_facts"][0])
                    replacement["value"]["concept_ids"] = [far]
                    if mode == "mutate_frozen":
                        replacement = copy.deepcopy(first)
                        replacement["value"]["status"] = "absent"
                    return client.completion(json.dumps({"facts": [replacement]}, ensure_ascii=False))
                client.chat = chat
                if mode == "budget":
                    s.session.call_limit = 1
                make_interpreter(CONFIG).process_input(s, k, client)
                records = [item for _, item in s.case.entries() if item.value and item.value.kind == "symptom"]
                linked = next(item for item in records if item.value.text == "가상증상")
                other = next(item for item in records if item.value.text == "별도 보고")
                self.assertEqual(linked.value.status, "present")
                self.assertEqual(linked.value.concept_ids, [str(OW.Complaint)])
                self.assertEqual(other.value.concept_ids, [far] if mode == "resolve" else [])
                self.assertEqual(len(payloads), 1 if mode == "budget" else 2)
                self.assertTrue(all("parser_payload" in entry for entry in s.interaction.model_history))
                self.assertEqual(s.session.doctor_calls, len(payloads))

    def test_display_label_asset_is_hash_pinned_without_graph_mutation(self):
        manifest_path = COPY / "knowledge/manifest.json"
        original = manifest_path.read_bytes()
        path = COPY / "knowledge/display-labels.json"
        try:
            path.write_text(json.dumps({str(OW.Complaint): "검토한 가상증상"}, ensure_ascii=False))
            manifest = json.loads(original)
            manifest["labels"] = {"path": "knowledge/display-labels.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            manifest_path.write_text(json.dumps(manifest))
            k = knowledge()
            before = set(k._graph)
            self.assertEqual(k.label(str(OW.Complaint)), "검토한 가상증상")
            self.assertIn(str(OW.Complaint), k.search_concepts("검토한 가상증상이 있어요"))
            self.assertEqual(set(k._graph), before)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                knowledge()
        finally:
            manifest_path.write_bytes(original)
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Verification)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"tests": result.testsRun, "failures": [str(t) for t, _ in result.failures],
              "errors": [str(t) for t, _ in result.errors], "successful": result.wasSuccessful(),
              "dependencies": {name: version(name) for name in ("langgraph", "pydantic", "rdflib")},
              "runtime_assets": str(COPY / "knowledge"), "network": "none", "real_doctor": "not_run", "official_sdk": "not_run"}
    (HERE / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
