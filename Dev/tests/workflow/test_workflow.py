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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from education_fixtures import education_response, KOREAN
from normalization_fixtures import context_from_facts, mapping_from_contracts

PROJECT = Path(__file__).resolve().parents[3]
HERE = Path(os.environ.get("ONTOWARD_TEST_OUTPUT", PROJECT / "Tmp/d18-verification/workflow"))
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
from workflow.runtime import PreparedResources, assemble_consultation, prepare, consult
from workflow.state.evidence import EvidenceIndex
from workflow.state.models import ActionSpec, ClinicalValue, Fact, Hypothesis, InteractionEntry, ParsedInput, Question, RecordItem, SessionContext, WorkflowState
from knowledge.graph import ClinicalKnowledge, OW, Plan
from knowledge.conditions import ExpectedValue, QuestionTemplate
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
    source_manifest = json.loads(SOURCE_MANIFEST.read_text()) if SOURCE_MANIFEST.exists() else {}
    reasoning_path = source_manifest.get("reasoning_policy", {}).get("path", "knowledge/reasoning_policy.json")
    files = {"schema.ttl": (SOURCE / "knowledge/schema.ttl").read_text(encoding="utf-8"), "vocabulary.ttl": "", "clinical.ttl": TTL,
             "scoring_policy.json": (SOURCE / "knowledge/scoring_policy.json").read_text(encoding="utf-8"),
             "reasoning_policy.json": (SOURCE / reasoning_path).read_text(encoding="utf-8"),
             "questions.json": json.dumps({key: {"text": text, "answer_type": "presence" if key == str(OW.Context) or key in {str(OW.Complaint), str(OW.Other)} else "category", "affirmative": key == str(OW.Context) or key in {str(OW.Complaint), str(OW.Other)}} for key, text in {**QUESTIONS, str(OW.Complaint): "가상증상 있나요?", str(OW.Other): "별도증상 있나요?"}.items()}, ensure_ascii=False), "plans.json": json.dumps(PLANS, ensure_ascii=False)}
    entries = {}
    for name, text in files.items():
        path = COPY / "knowledge" / name
        path.write_text(text, encoding="utf-8")
        entries[name] = {"path": "knowledge/" + name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"schema_version": "5.0", "registry_version": "synthetic-v5", "normalization_version": "v5.0.1",
                "source_snapshots": [{"dataset": "synthetic", "sha256": hashlib.sha256(TTL.encode()).hexdigest()}],
                "scoring_policy_version": "v5.0.1", "scoring_policy": entries["scoring_policy.json"],
                "schema": entries["schema.ttl"], "vocabulary": entries["vocabulary.ttl"],
                "reasoning_policy": entries["reasoning_policy.json"], "bundles": [entries["clinical.ttl"]], "questions": entries["questions.json"], "plans": entries["plans.json"]}
    (COPY / "knowledge/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


write_assets()
(COPY / ".env").write_text((COPY / ".env").read_text().replace(
    "ONTOWARD_EDUCATION_ENABLED=true", "ONTOWARD_EDUCATION_ENABLED=false"))
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


def complete_common_history(s):
    from workflow.rules.collection import INTAKE, HISTORY, CATEGORY_FIELDS
    for slot in (*INTAKE, *HISTORY):
        q = Question(item_id="answered:" + slot, purpose="intake" if slot in INTAKE else "history",
            field=CATEGORY_FIELDS[slot], text="확인 질문입니다.", record_category=slot, order=0, priority=0)
        s.interaction.history.append(InteractionEntry(id=q.item_id, kind="SAY", delivered=True, question=q,
            request={"content": q.text}, response={"content": "모르겠어요"}))
    q = Question(item_id="greeted", purpose="greeting", field="S.hpi", text=CONFIG.texts.greeting, order=-1, priority=1)
    s.interaction.history.append(InteractionEntry(id=q.item_id, kind="SAY", delivered=True, question=q,
        request={"content":q.text}, response={"content":"안녕하세요"}))
    s.questions.context_coverage = [str(OW.Context)]


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
                 affirmative_presence=attribute is None, answer_type="category" if attribute else "presence", time_context="current")
    make_planner(knowledge(), CONFIG).questions.register(s, q)
    return q


def pending(s, q):
    s.interaction.pending = ActionSpec(question=q, content=q.text, request_id="request-1")


def fact(field, kind, target, text, *, q=None, attribute=None, values=None, status="present"):
    v = {"kind": kind, "text": text, "status": status, "concept_ids": [str(target)],
         "observation_id": (q or {}).get("observation_id") or "obs1",
         "episode_id": (q or {}).get("episode_id") or "episode1", "time_context": (q or {}).get("time_context", "current")}
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
        education = education_response(payload)
        if education is not None:
            return self.completion(json.dumps(education, ensure_ascii=False))
        if payload.get("task") == "empathy":
            return self.completion(json.dumps({"text": CONFIG.texts.empathy_fallback}, ensure_ascii=False))
        if payload.get("task") == "input_mapping":
            return self.completion("{bad json" if self.malformed else json.dumps(mapping_from_contracts(payload)))
        if payload.get("task") == "input_context":
            q, text = payload["question"], payload["input"]
            if self.malformed:
                return self.completion("{bad json")
            if not text.strip() or text in {"알겠습니다", "감사합니다", "안녕하세요"}:
                return self.completion('{"statements":[]}')
            if text in CONFIG.texts.unknown_replies:
                return self.completion(json.dumps({"statements": [{"quote": text, "role": "unknown"}]}))
            target = q["target_id"] if q and q["target_id"] else str(OW.Other if self.no_candidate else OW.Complaint)
            kind = "finding" if q and q["kind"] == "EXAM" else "context" if q and q["purpose"] == "context" else "symptom"
            facts = []
            if q and q["purpose"] == "hpi":
                for attr, value in ((OW.Location, OW.Here), (OW.Quality, OW.Dull)):
                    facts.append(fact("S.hpi", "attribute", target, text, q=q, attribute=attr, values=[value]))
            elif not q or q["purpose"] not in {"greeting", "intake", "history", "open_inquiry", "empathy"}:
                facts = [fact(q["field"] if q else "S.cc", kind, target, text, q=q,
                              status="absent" if text in {"아니요", "없어요"} else "present")]
            return self.completion(json.dumps(context_from_facts(facts), ensure_ascii=False))
        if payload.get("task") == "terminology":
            return self.completion(json.dumps({"facts": [], "clinical_content": False}))
        q, text = payload["question"], payload["input"]
        facts = []
        if not q or q["purpose"] in {"chief", "clarification"}:
            facts = [fact("S.cc", "symptom", OW.Other if self.no_candidate else OW.Complaint, text, q=q)]
        elif q["purpose"] == "hpi":
            for attr, value in ((OW.Location, OW.Here), (OW.Quality, OW.Dull)):
                supplied = {row["id"] for row in payload["vocabulary"]}
                if not {str(attr), str(value)} <= supplied:
                    continue
                matching = next((r for r in payload["records"] if r["id"].endswith(str(attr))), None)
                matched_q = {**q, "item_id": matching["id"]} if matching else None
                facts.append(fact("S.hpi", "attribute", OW.Complaint, text, q=matched_q, attribute=attr, values=[value]))
        elif q["kind"] == "EXAM":
            facts = [fact("O.exam", "finding", OW.ExamX, text, q=q)]
        elif q["purpose"] == "context":
            facts = [fact("S.pmh", "context", OW.Context, text, q=q, status="absent" if text == "아니요" else "present")]
        elif q["purpose"] == "ros":
            facts = [fact("S.ros", "symptom", q["target_id"], text, q=q, status="absent" if text == "없어요" else "present")]
        content = "{bad json" if self.malformed else json.dumps({"facts": facts, "clinical_content": bool(facts)}, ensure_ascii=False)
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
                  "안녕하세요" if text == CONFIG.texts.greeting else
                  "모르겠어요" if text in {*CONFIG.texts.intake_questions.values(), *CONFIG.texts.history_questions.values()} else
                  "가상증상이 있어요" if text == CONFIG.texts.clarification_question else
                  "없어요" if text == CONFIG.texts.open_question or text.endswith("도 있나요?") or text == "별도증상 있나요?" else "알겠습니다")
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
        s.session.turns_remaining = w.budget.required_actions(s, "ContextFactor") + 3 + 2
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

        w.doctor.validate_action(s)
        w.doctor.execute_action(s, client)
        w.interpreter.process_input(s, knowledge(), client)
        w.refresh_after_input(s)
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
        s.session.deadline = clock[0] + timedelta(seconds=241)
        q = question(s, purpose="chief", field="S.cc", target=None, text=CONFIG.texts.greeting)
        w.interactions.select_question(s, q)

        w.doctor.validate_action(s)
        self.assertTrue(s.interaction.selected.ready)
        clock[0] += timedelta(seconds=2)
        w.doctor.execute_action(s, client)
        self.assertTrue(s.session.finalizing)
        self.assertIsNone(s.interaction.selected)
        self.assertFalse(client.actions)
        self.assertFalse(client.calls)

    def test_node_validation_does_not_replay_completed_external_action(self):
        s = state("Initiation", True)
        q = question(s, purpose="chief", field="S.cc", target=None, text=CONFIG.texts.greeting)
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
        reasoner.refresh_hypotheses(s, force=True)
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
        planner = make_planner(k, CONFIG)
        paths, _ = planner._frontier(s, reasoner.evaluate(EvidenceIndex.from_case(s.case), reasoner.anchor(s.case)), [str(OW.Alpha)])
        required = next(p.specs[0] for p in paths if p.specs[0]["target_id"] == str(OW.Context))
        planner._register(s, required, 0, 1)
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
        self.assertEqual(client.actions[0]["content"], CONFIG.texts.greeting)
        self.assertIn("EXAM", [a["kind"] for a in client.actions])
        self.assertLessEqual(len(client.actions), 36)
        note = client.submissions[0]["note"]
        self.assertEqual({s: tuple(f) for s, f in note.items()}, RECORD_FIELDS)
        self.assertEqual(note["O"]["tests"], "")
        self.assertIn("가상소견", note["A"]["evidence"])
        self.assertIn("가상검사", note["P"]["tests"])
        self.assertEqual(result.session.doctor_calls, len(client.calls))
        self.assertEqual(result.session.input_tokens, len(client.calls) * 20)
        self.assertEqual(len(result.interaction.model_history), len(client.calls))
        self.assertEqual({call["role"] for call in result.interaction.model_history}, {"gateway"})
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
        self.assertEqual(s.session.clarifications, 0)
        self.assertFalse(s.differential.hypotheses)
        self.assertEqual(client.submissions[0]["note"]["P"]["treatment"], "")
        self.assertIn("Cause undetermined", client.submissions[0]["note"]["A"]["evidence"])

    def test_pure_routes_initialization_and_current_scope(self):
        s = state()
        self.assertEqual(route_budget(s), "enter_session")
        q = question(s)
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
        s.session.turns_remaining = interview.budget.required_actions(s, "ContextFactor") + 3 + 2
        make_consultation().check_budget(s)
        ids = {q.item_id for q in s.questions.questions}
        self.assertIn("ChiefComplaint:open", ids)
        self.assertTrue(any(q.attribute_id == str(OW.Location) for q in s.questions.questions))
        self.assertFalse(any(str(OW.Quality) in item.id for _, item in s.case.entries()))
        before = s.model_dump()
        make_consultation(FakeSDK(), resources()).enter_session(s)
        self.assertEqual(before, s.model_dump())
        self.assertEqual({i.id for i in s.case.unasked("ChiefComplaint")}, ids)

    def test_last_response_is_processed_before_budget_and_keeps_facts_and_plans(self):
        s = state("Education", True)
        record(s)
        record(s, ident="plan", kind="plan", field="P.education")
        q = question(s, purpose="education", field="P.education")
        pending(s, q)
        s.session.turns_remaining = 0
        s.session.doctor_successes = 1
        s.interaction.incoming = {"content": "알겠습니다", "facts": []}
        make_interpreter(CONFIG).process_input(s, knowledge(), FakeSDK())
        make_consultation().check_budget(s)
        self.assertIsNone(s.interaction.pending)
        self.assertIsNone(s.case.get("q"))
        self.assertEqual(s.questions.education[0].status, "undelivered")
        self.assertTrue(s.session.finalizing)
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



    def test_fact_grounding_and_correction_boundary(self):
        s = state()
        gateway = make_interpreter(CONFIG)
        forged = fact("O.exam", "finding", OW.ExamX, "reported")
        self.assertTrue(gateway._validate_facts({"facts": [forged]}, s, knowledge(), "reported").rejected_facts)
        record(s)
        correction = fact("S.cc", "symptom", OW.Complaint, "correction", status="absent")
        correction["record_id"] = "chief"
        parsed = gateway._validate_facts({"facts": [correction]}, s, knowledge(), "correction")
        self.assertIsNotNone(parsed)
        gateway._apply_facts(s, parsed, "correction-source")
        self.assertEqual(s.case.get("chief").value.status, "absent")
        self.assertEqual(s.case.get("chief").source_refs, ["source", "correction-source"])
        correction["value"]["episode_id"] = "different"
        self.assertTrue(gateway._validate_facts({"facts": [correction]}, s, knowledge(), "correction").rejected_facts)

    def test_invalid_answer_target_and_missing_response(self):
        s = state("ChiefComplaint", True)
        q = question(s, target=OW.Complaint, purpose="hpi", attribute=OW.Location, field="S.hpi")
        pending(s, q)
        wrong = fact("S.hpi", "attribute", OW.Complaint, "reply", q=q.model_dump(), attribute=OW.Quality, values=[OW.Dull])
        gateway = make_interpreter(CONFIG)
        self.assertTrue(gateway._validate_facts({"facts": [wrong]}, s, knowledge(), "reply").rejected_facts)
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
        (package_copy / "knowledge/superseded-clinical.ttl").write_text(TTL)
        import settings
        with patch.object(settings, "ROOT", package_copy), patch("builtins.print"):
            module.main()
            with ZipFile(module.OUTPUT) as archive:
                self.assertEqual(archive.read("nova_sdk.py"), (SOURCE / "nova_sdk.py").read_bytes())
                self.assertIn("config/input_parser.txt", archive.namelist())
                self.assertNotIn("config/doctor.txt", archive.namelist())
                self.assertIn("config/texts.ko.json", archive.namelist())
                self.assertFalse(any("README" in n or "PROJECT_STATE" in n or "AGENTS" in n or "__pycache__" in n for n in archive.namelist()))
                self.assertFalse(any("fixture" in n for n in archive.namelist()))
                self.assertNotIn("knowledge/superseded-clinical.ttl", archive.namelist())
                if SOURCE_MANIFEST.exists():
                    manifest = json.loads(archive.read("knowledge/manifest.json"))
                    if manifest.get("preparation_status") == "withdrawn_by_D18":
                        self.assertNotIn("bundles", manifest)
                        self.assertFalse(any(n.endswith("clinical.ttl") for n in archive.namelist()))
                    else:
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
        self.assertEqual(refused, "")
        self.assertNotIn("가상소견", client.submissions[0]["note"]["A"]["evidence"])
        self.assertFalse(any(item.value.kind == "finding" and str(OW.ExamX) in item.value.concept_ids
                             for _, item in s.case.entries() if item.value))
        s, client = self.run_flow(FakeSDK(unknown_action=True))
        self.assertEqual(s.interaction.termination, "unknown")
        self.assertEqual(len(client.actions), 2)
        self.assertEqual(len({action["request_id"] for action in client.actions}), 1)
        self.assertIsNotNone(s.interaction.pending)
        self.assertEqual(s.interaction.history[-1].request["request_id"], client.actions[0]["request_id"])
        self.assertFalse(client.submissions)

    def test_submission_unknown_keeps_exact_payload(self):
        for result in ("timeout", "not_completed"):
            s, client = self.run_flow(FakeSDK(submit_status=result))
            self.assertEqual(s.interaction.termination, "unknown")
            self.assertEqual(len(client.submissions), 2 if result == "timeout" else 1)
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
        s.session.gateway_successes = s.session.doctor_successes = 1
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
        self.assertIn("turn 50", s.interaction.submission_payload["note"]["O"]["exam"])

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

    def test_education_finalization_preserves_generated_plan_and_delivery(self):
        s = state("Education", True)
        record(s)
        client = FakeSDK()
        agent = make_consultation(client, resources(config=CONFIG.model_copy(update={"education_enabled": True})))
        agent.prepare_education(s)
        before = s.case.model_dump()["P"]
        agent.planner.select_question(s)
        agent.doctor.validate_action(s)
        agent.doctor.execute_action(s, client)
        agent.interpreter.process_input(s, agent.planner.knowledge, client)
        calls = len(client.calls)
        agent.finalize(s)
        self.assertEqual(s.case.model_dump()["P"], before)
        self.assertEqual(len(client.calls), calls)
        self.assertEqual(sum(item.status == "delivered" for item in s.questions.education), 1)

    def test_missing_plan_question_and_observed_past(self):
        k = knowledge()
        k.plans = {}
        k.questions = {}
        s, client = self.run_flow(r=resources(k))
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertTrue(any(issue.startswith("unavailable_question:") for issue in s.interaction.issues))
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

    def test_prepared_doctor_validates_and_delivers_without_model_calls(self):
        s, client = state(), FakeSDK()
        interview = make_planner(knowledge(), CONFIG)
        interview.prepare_initiation(s)
        interview.select_question(s)
        interface = make_doctor(CONFIG)
        interface.validate_action(s)
        self.assertTrue(s.interaction.selected.ready)
        self.assertFalse(client.calls)
        interface.execute_action(s, client)
        self.assertEqual(client.actions[0]["content"], CONFIG.texts.greeting)
        self.assertEqual(s.interaction.dialogue()[0]["doctor"], CONFIG.texts.greeting)
        other = state()
        q = question(other, text="가" * 31)
        other.interaction.selected = ActionSpec(question=q, content=q.text, request_id="invalid")
        interface.validate_action(other)
        self.assertIsNone(other.interaction.selected)
        self.assertFalse(other.interaction.dialogue())
        self.assertEqual(other.case.get(q.item_id).value.status, "unknown")
        self.assertEqual(content_error("가" * 29 + "\n"), None)
        self.assertEqual(content_error("가" * 30 + "\n"), "content_too_long")


    def test_contextual_correction_preserves_episode_and_quote(self):
        for reply in ("거기도요", "아까보다 덜해요", "아니요, 아까 말한 곳이에요"):
            s = state("ChiefComplaint", True)
            record(s)
            record(s, ident="location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
            s.interaction.history.append(InteractionEntry(id="earlier", kind="SAY", delivered=True,
                request={"content": "어느 부위인가요?"}, response={"content": "가상부위요"}))
            correction = fact("S.hpi", "attribute", OW.Complaint, reply, attribute=OW.Location, values=[OW.Here])
            correction.update(record_id="location", context_refs=["earlier"])
            gateway = make_interpreter(CONFIG)
            parsed = gateway._validate_facts({"facts": [correction]}, s, knowledge(), reply)
            self.assertIsNotNone(parsed)
            gateway._apply_facts(s, parsed, "current")
            self.assertEqual(s.case.get("location").value.text, "")
            self.assertEqual(s.case.get("location").value.episode_id, "episode1")
            self.assertEqual(s.case.get("location").context_refs, ["earlier"])

    def test_focused_ros_union_limits_order_and_cross_system_retrieval(self):
        k, s = knowledge(), state("ChiefComplaint", True)
        for system in (OW.SystemA, OW.SystemB):
            k._graph.add((system, RDF.type, OW.BodySystem))
            k._graph.add((OW.Complaint, OW.inSystem, system))
        for index in range(9):
            symptom = OW[f"Ros{index}"]
            k._graph.add((symptom, RDF.type, OW.Symptom))
            k.questions[str(symptom)] = QuestionTemplate(text=f"증상{index} 있나요?", answer_type="presence", affirmative=True)
            for system in (OW.SystemA, OW.SystemB):
                k._graph.add((symptom, OW.inSystem, system))
            add_v5_pattern(k, f"rosUtility{index}", symptom, [], disease=OW.Beta)
        k.validate_graph()
        record(s)
        record(s, ident="known", target=OW.Ros0, field="S.ros", status="absent")
        record(s, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        record(s, "quality", kind="attribute", field="S.hpi", attribute=OW.Quality, values=[OW.Dull])
        planner = make_planner(k, CONFIG)
        planner.prepare_chief_complaint(s)
        opening = next(q for q in s.questions.questions if q.purpose == "open_inquiry")
        s.case.get(opening.item_id).status = "done"
        s.interaction.history.append(InteractionEntry(id="open", kind="SAY", delivered=True, question=opening,
            request={"content": opening.text}, response={"content": "없어요"}))
        ClinicalReasoner(k).retrieve_candidates(s)
        planner.replan(s, force=True)
        ros = [q for q in s.questions.questions if q.purpose == "ros" and s.case.get(q.item_id).status == "unasked"]
        self.assertEqual(len(ros), 1)
        delivered = []
        for index in range(6):
            planner.select_question(s)
            selected = s.interaction.selected.question
            self.assertEqual(selected.purpose, "ros")
            self.assertNotEqual(selected.target_id, str(OW.Ros0))
            delivered.append(selected.semantic_key())
            s.interaction.history.append(InteractionEntry(id=f"ros:{index}", kind="SAY", delivered=True, question=selected,
                request={"content": selected.text}, response={"content": "없어요"}))
            item = s.case.get(selected.item_id)
            item.status = "done"
            item.source_refs = [f"ros:{index}"]
            item.value = ClinicalValue(kind="symptom", text="없어요", status="absent", concept_ids=[selected.target_id],
                observation_id=selected.observation_id, episode_id=selected.episode_id, time_context=selected.time_context)
            s.session.usage["ChiefComplaint"].actions += 1
            planner.interactions.clear_selected(s)
            ClinicalReasoner(k).refresh_hypotheses(s)
            planner.replan(s, force=True)
        self.assertEqual(len(set(delivered)), 6)
        self.assertFalse(any(q.purpose == "ros" and s.case.get(q.item_id).status == "unasked" for q in s.questions.questions))
        k._graph.add((OW.Cross, RDF.type, OW.Disease))
        add_v5_pattern(k, "cross", OW.Ros1, [], disease=OW.Cross)
        record(s, ident="new", target=OW.Ros1, field="S.ros")
        ClinicalReasoner(k).refresh_hypotheses(s)
        self.assertIn(str(OW.Cross), [h.disease_id for h in s.differential.hypotheses])

    def test_ros_full_flow_explicit_negative_and_unknown(self):
        k = knowledge()
        k._graph.add((OW.System, RDF.type, OW.BodySystem))
        k._graph.add((OW.Complaint, OW.inSystem, OW.System))
        k._graph.add((OW.Other, OW.inSystem, OW.System))
        add_v5_pattern(k, "otherRosUtility", OW.Other, [], disease=OW.Beta)
        s, client = self.run_flow(r=resources(k))
        self.assertEqual(s.interaction.termination, "submitted")
        ros = next(item for _, item in s.case.entries() if item.value and item.value.concept_ids == [str(OW.Other)] and item.value.status == "absent")
        self.assertEqual(ros.value.status, "absent")
        self.assertIn(ros.id, s.case.S["ros"])
        content = [a["content"] for a in client.actions]
        self.assertLess(content.index(CONFIG.texts.open_question), content.index("별도증상 있나요?"))

    def test_clarification_is_not_dropped_as_already_known(self):
        s = state("ChiefComplaint", True)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=OW.Location, field="S.hpi")
        pending(s, q)
        s.interaction.incoming = {"content": "설명하기 어려워요"}
        make_interpreter(CONFIG).process_input(s, knowledge(), FakeSDK(malformed=True))
        self.assertEqual(s.questions.answer_outcomes[q.item_id], "unknown")
        interview = make_planner(knowledge(), CONFIG)
        self.assertTrue(interview.prepare_clarification(s, q))
        interview.select_question(s)
        self.assertEqual(s.interaction.selected.question.purpose, "clarification")
        self.assertTrue(interview.prepare_clarification(s, q))
        self.assertEqual(s.session.clarifications, 1)

    def test_empty_opening_and_no_supported_diagnosis(self):
        client = FakeSDK()
        original = client.session
        client.session = lambda: {**original(), "initial": {"opening": "", "vital_signs": {"pulse": 80}}}
        s, client = self.run_flow(client)
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(client.actions[0]["content"], CONFIG.texts.greeting)
        self.assertEqual(s.interaction.model_history[0]["role"], "gateway")
        client = FakeSDK(malformed=True)
        s, client = self.run_flow(client)
        self.assertEqual(s.interaction.termination, "failed")
        self.assertEqual(s.session.clarifications, 2)
        self.assertEqual(len(client.actions), 7)
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
            if len(calls) < 2:
                raise NovaError("REQUEST_PENDING")
            return client.completion("안녕하세요")
        client.chat = chat
        with patch("workflow.io.request_executor.time.sleep") as sleep:
            self.assertEqual(make_consultation().interpreter.model.complete(s, client, role="gateway", messages=[]), "안녕하세요")
        self.assertEqual(calls, [calls[0]] * 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2])
        self.assertEqual(timeouts, [240] * 2)
        self.assertEqual(client.timeout, 120)
        self.assertEqual((s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens), (1, 20, 10))
        self.assertEqual(len(s.interaction.model_history), 1)
        s.session.deadline = datetime.now(timezone.utc) + timedelta(seconds=125)
        seen = []
        make_consultation().doctor.executor.execute(s, client, lambda: seen.append(client.timeout), {}, [])
        self.assertLessEqual(seen[0], 5)

    def test_action_transient_replay_and_no_response_format_retry(self):
        for code in ("REQUEST_PENDING", "PATIENT_RESPONSE_INVALID", "EXAMINER_RESPONSE_INVALID"):
            s = state()
            q = question(s, text=CONFIG.texts.greeting, purpose="chief", field="S.cc", target=None)
            s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="first", ready=True)
            client, requests = FakeSDK(), []
            real = client.say
            def say(**kwargs):
                requests.append(kwargs)
                if len(requests) == 1:
                    raise NovaError(code)
                return real(**kwargs)
            client.say = say
            with patch("workflow.io.request_executor.time.sleep") as sleep:
                make_doctor(CONFIG).execute_action(s, client)
            self.assertEqual(len(requests), 2 if code == "REQUEST_PENDING" else 1)
            if code == "REQUEST_PENDING":
                self.assertEqual(requests[0], requests[1])
                sleep.assert_called_once_with(2)
            else:
                sleep.assert_not_called()
                make_interpreter(CONFIG).process_input(s, knowledge(), client)
                self.assertEqual(s.case.get(q.item_id).value.status, "unknown")
                self.assertIsNone(s.interaction.pending)
            self.assertEqual(s.session.usage["Initiation"].actions, int(code == "REQUEST_PENDING"))
            self.assertEqual(len(s.interaction.dialogue()), int(code == "REQUEST_PENDING"))


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
        config = CONFIG.model_copy(update={"education_enabled": True})
        record(s)
        q = question(s, text="준비된 안내입니다.", purpose="education", field="P.education", target=None)
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="education", ready=True)
        client = FakeSDK(malformed=True)
        client._reply = lambda *args, **kwargs: {"status": "OK", "turn": 1, "turns_remaining": 49, "content": "새로운 증상이 있어요"}
        agent = make_consultation(client, resources(config=config))
        agent.reasoner.select_diagnosis(s)
        agent.freeze_diagnosis(s)
        agent.doctor.execute_action(s, client)
        agent.interpreter.process_input(s, agent.planner.knowledge, client)
        self.assertIsNone(s.case.get(q.item_id))
        self.assertEqual(s.questions.education[0].status, "delivered")
        self.assertEqual(s.questions.education[0].question.text, q.text)
        self.assertFalse(s.interaction.needs_clarification)
        self.assertEqual(client.calls, [])
        agent.refresh_after_input(s)
        self.assertFalse(s.interaction.needs_clarification)
        self.assertEqual(s.case.P["education"], {})
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
        texts = CONFIG.texts.model_dump()
        del texts["soap_labels"]["cc"]
        alternate_text.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        with patch.dict(os.environ, {"ONTOWARD_TEXTS": "config/review-texts.json"}):
            with self.assertRaisesRegex(ValueError, "SOAP category"): TextConfig.load()

    def test_new_fact_during_education_preserves_fixed_diagnosis_and_plan(self):
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
            if text == KOREAN["education"]:
                result["content"] = "별도증상도 있어요"
            return result
        def chat(messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            if messages[0]["content"] == CONFIG.parser_prompt and payload["input"] == "별도증상도 있어요":
                client.calls.append({"messages": messages, **kwargs})
                return client.completion(json.dumps({"facts": [fact("S.ros", "symptom", OW.Other, payload["input"])]}, ensure_ascii=False))
            return original_chat(messages, **kwargs)
        client._reply, client.chat = reply, chat
        s, client = self.run_flow(client, resources(k, CONFIG.model_copy(update={"education_enabled": True})))
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(s.case.diagnosis, s.case.fixed_diagnosis.name)
        delivered = [a["content"] for a in client.actions]
        self.assertIn(KOREAN["education"], delivered)
        self.assertNotIn(CONFIG.texts.correction_education, delivered)
        self.assertEqual(s.session.usage["Education"].actions, 5)
        self.assertFalse(any(item.value and item.value.status == "present" and str(OW.Other) in item.value.concept_ids for _, item in s.case.entries()))
        self.assertIn("Review the treatment plan", client.submissions[0]["note"]["P"]["treatment"])

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
                original(messages, **kwargs)
                corrections = [fact("S.cc", "symptom", OW.Complaint, payload["input"],
                    q={**payload["question"], "item_id": item["id"],
                       "observation_id": item["value"]["observation_id"], "episode_id": item["value"]["episode_id"]})
                    for item in payload["records"] if item["value"] and item["value"]["concept_ids"] == [str(OW.Other)]]
                return client.completion(json.dumps({"facts": corrections}, ensure_ascii=False))
            return original(messages, **kwargs)
        client.chat = chat
        s, client = self.run_flow(client)
        self.assertEqual(s.interaction.termination, "submitted")
        self.assertEqual(s.case.diagnosis_kind, "symptom")
        self.assertEqual(s.session.clarifications, 0)

    def test_shared_resources_keep_case_dialogue_separate(self):
        r = resources()
        first, _ = self.run_flow(r=r)
        second, client = self.run_flow(FakeSDK(no_candidate=True), r)
        first_ids = {row["id"] for row in first.interaction.dialogue() if row["id"] != "initial"}
        second_ids = {row["id"] for row in second.interaction.dialogue() if row["id"] != "initial"}
        self.assertTrue(first_ids.isdisjoint(second_ids))
        view = json.loads(client.calls[0]["messages"][1]["content"])["dialogue"]
        self.assertEqual(view, [])
        self.assertIsNot(first.differential.search_cache, second.differential.search_cache)

    def test_invalid_prepared_content_and_unknown_usage_stop_collection(self):
        s, client = state(), FakeSDK()
        q = question(s, text="   ")
        s.interaction.selected = ActionSpec(question=q, content=q.text, request_id="blank")
        make_doctor(CONFIG).validate_action(s)
        self.assertIsNone(s.interaction.selected)
        self.assertFalse(client.calls)
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
        self.assertFalse(any(item.purpose == "clarification" for item in s.questions.questions))
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
        self.assertIn("Family · Past", writer._describe_record(changed))
        self.assertNotIn("private-", left)
        measured = item.model_copy(deep=True)
        measured.value.values, measured.value.attribute_id = [], str(OW.EpisodeDuration)
        measured.value.measurement = ExpectedValue(kind="interval", lower=1.0, upper=2.0, unit="month", upper_unit="year", upper_inclusive=False)
        self.assertIn("[1 month, 2 years)", writer._describe_record(measured))
        s = state("Education", True)
        s.case.put("S.hpi", item)
        measured.id, measured.value.episode_id = "another-record", "another-private-episode"
        s.case.put("S.hpi", measured)
        writer.build_soap(s)
        rendered = s.interaction.submission_payload["note"]["S"]["hpi"]
        self.assertIn("Episode 1", rendered)
        self.assertIn("Episode 2", rendered)

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
        record(s)
        for i in range(7):
            ident = str(OW[f"Alternative{i}"])
            k._graph.add((URIRef(ident), RDFS.label, Literal(f"대안{i}", lang="ko")))
            s.differential.hypotheses.append(Hypothesis(disease_id=ident, evidence_score=0.25, chief_coverage=1, evidence_ids=["chief"]))
        writer.build_soap(s)
        lines = s.interaction.submission_payload["note"]["A"]["differential"].splitlines()
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(line.startswith(f"r/o 대안{i}: ") and "가상증상 (+)" in line for i, line in enumerate(lines)))



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


    def test_d17_shared_pattern_cache_and_correction_invalidation(self):
        k, s = knowledge(), state("DifferentialDiagnosis", True)
        record(s)
        r = ClinicalReasoner(k)
        r.retrieve_candidates(s)
        self.assertEqual(s.differential.pattern_evaluations, 2)
        evaluations, refreshes = s.differential.pattern_evaluations, s.differential.refreshes
        r.refresh_hypotheses(s)
        self.assertEqual((s.differential.pattern_evaluations, s.differential.refreshes), (evaluations, refreshes))
        record(s, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        r.refresh_hypotheses(s)
        expected = [h.model_dump() for h in s.differential.hypotheses]
        self.assertEqual(s.differential.pattern_evaluations, evaluations + 2)
        r.refresh_hypotheses(s, force=True)
        self.assertEqual([h.model_dump() for h in s.differential.hypotheses], expected)
        s.case.get("location").value.status = "absent"
        r.refresh_hypotheses(s)
        self.assertEqual(s.differential.hypotheses[0].evidence_score, 1)

    def test_d17_bounded_typicality_absence_and_episode_isolation(self):
        k, s = knowledge(), state("DifferentialDiagnosis", True)
        record(s)
        for index in range(5):
            target = OW[f"Denied{index}"]
            k._graph.add((target, RDF.type, OW.Symptom))
            association, _ = add_v5_pattern(k, f"denied{index}", target, [], label="high")
            k._graph.add((association, OW.typicality, Literal("very_high")))
            record(s, f"denied-{index}", target=target, field="S.ros", status="absent")
        k.validate_graph()
        r = ClinicalReasoner(k)
        r.retrieve_candidates(s)
        alpha = next(h for h in s.differential.hypotheses if h.disease_id == str(OW.Alpha))
        self.assertEqual(alpha.contradiction_penalty, 2)
        for index in range(5):
            s.case.get(f"denied-{index}").value.episode_id = "different-episode"
        r.refresh_hypotheses(s)
        self.assertTrue(all(h.contradiction_penalty == 0 for h in s.differential.hypotheses))
        for index in range(5):
            s.case.get(f"denied-{index}").value.status = "unknown"
            s.case.get(f"denied-{index}").value.episode_id = "episode1"
        r.refresh_hypotheses(s)
        self.assertTrue(all(h.contradiction_penalty == 0 for h in s.differential.hypotheses))

    def test_d17_partial_facts_and_atomic_correction_dependencies(self):
        s, gateway = state(), make_interpreter(CONFIG)
        independent = fact("S.ros", "symptom", OW.Other, "별도증상")
        invalid = fact("S.cc", "symptom", OW.Complaint, "인용에 없음")
        invalid["value"].update(observation_id="new", episode_id="new")
        dependent = fact("S.hpi", "attribute", OW.Complaint, "부위", attribute=OW.Location, values=[OW.Here])
        dependent["value"].update(observation_id="new", episode_id="new")
        parsed = gateway._validate_facts({"facts": [independent, invalid, dependent, {"record_id": []}]}, s, knowledge(), "별도증상 부위")
        self.assertEqual([f.value.concept_ids for f in parsed.accepted_facts], [[str(OW.Other)]])
        self.assertEqual(len(parsed.rejected_facts), 3)
        record(s)
        correction = fact("S.cc", "symptom", OW.Complaint, "없어요", status="absent")
        correction["record_id"] = "chief"
        invalid["record_id"] = "chief"
        parsed = gateway._validate_facts({"facts": [correction, invalid]}, s, knowledge(), "없어요")
        self.assertFalse(parsed.accepted_facts)
        gateway._apply_facts(s, parsed, "new-source")
        self.assertEqual(s.case.get("chief").value.status, "present")

    def test_d17_context_is_bounded_and_retains_old_episode_source(self):
        s, w = state("ChiefComplaint", True), make_consultation()
        record(s)
        s.case.get("chief").source_refs = ["past-0"]
        for index in range(50):
            s.interaction.history.append(InteractionEntry(id=f"past-{index}", kind="SAY", delivered=True,
                request={"content": "어느 부위인가요?"}, response={"content": "원문" * 400}))
        q = question(s, target=OW.Complaint, attribute=OW.Location, purpose="hpi", field="S.hpi")
        q.observation_id, q.episode_id = "obs1", "episode1"
        projected = w.interactions.project_context(s, q, [str(OW.Complaint)])
        self.assertLessEqual(len(projected["records"]), 24)
        self.assertLessEqual(len(projected["dialogue"]), 6)
        self.assertLessEqual(len(json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode()), 16384)
        self.assertIn("past-0", [turn["id"] for turn in projected["dialogue"]])
        self.assertEqual(len(s.interaction.dialogue()), 50)

    def test_d17_absent_target_attributes_and_reconsideration(self):
        k, s = knowledge(), state("DifferentialDiagnosis", True)
        k._graph.add((OW.Other, OW.hasAttribute, OW.Quality))
        add_v5_pattern(k, "otherQuality", OW.Other, [(OW.Quality, {"kind": "concept", "concept": str(OW.Dull)})], disease=OW.Beta)
        record(s)
        record(s, "other", OW.Other, status="absent", field="S.ros")
        w = make_consultation(prepared=resources(k))
        w.reasoner.retrieve_candidates(s)
        w.planner.replan(s)
        self.assertFalse(any(q.target_id == str(OW.Other) and q.attribute_id for q in s.questions.questions))
        s.case.get("other").value.status = "present"
        w.reasoner.refresh_hypotheses(s)
        w.planner.replan(s)
        selected = next(q for q in s.questions.questions if q.target_id == str(OW.Other) and q.attribute_id == str(OW.Quality))
        w.questions.discard_unasked(s, {selected.item_id})
        w.planner.replan(s)
        self.assertIsNone(s.case.get(selected.item_id))
        record(s, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        w.reasoner.refresh_hypotheses(s)
        w.planner.replan(s)
        self.assertIsNotNone(s.case.get(selected.item_id))
        w.planner.select_question(s)
        self.assertEqual(s.interaction.selected.question.target_id, str(OW.Other))

    def test_session_cap_and_shared_response_window(self):
        s, w = state("DifferentialDiagnosis", True, turns=20), make_consultation()
        s.session.usage["DifferentialDiagnosis"].actions = 9
        q = question(s)
        self.assertFalse(w.budget.evaluate(s).finalize)
        self.assertNotIn(q.item_id, w.budget.evaluate(s).discard)
        s.session.turns_remaining = 3
        self.assertNotIn(q.item_id, w.budget.evaluate(s).discard)
        self.assertIn(q.item_id, BudgetPolicy(education_enabled=True).evaluate(s).discard)
        s.session.usage["DifferentialDiagnosis"].actions = 10
        self.assertIn(q.item_id, w.budget.evaluate(s).discard)
        self.assertFalse(w.budget.evaluate(s).finalize)
        s.session.current = "Education"
        self.assertEqual(w.budget.action_capacity(s), 0)
        self.assertEqual(BudgetPolicy(education_enabled=True).action_capacity(s), 3)
        now = datetime.now(timezone.utc)
        s.session.deadline = now + timedelta(seconds=200)
        self.assertTrue(w.budget.evaluate(s).finalize)
        self.assertGreater(w.budget.model_allowance(s.session), 0)
        client = FakeSDK()
        timeouts = []
        w.doctor.executor.execute(s, client, lambda: timeouts.append(client.timeout), {}, [])
        self.assertGreater(timeouts[0], 0)
        self.assertLessEqual(timeouts[0], 80)
        with self.assertRaises(NovaError):
            w.doctor.executor.execute(s, client, lambda: None, {}, [], action=True)

    def test_d17_composite_guard_and_exact_duration_reply(self):
        k, s = knowledge(), state("ChiefComplaint", True)
        from rdflib import RDFS
        k._graph.add((OW.Composite, RDF.type, OW.Symptom))
        k._graph.add((OW.Composite, RDFS.label, Literal("종양에 의한 두통", lang="ko")))
        k.questions[str(OW.Composite)] = QuestionTemplate(text="종양에 의한 두통 있나요?", answer_type="presence",
                                                       interviewable=False, reason="diagnosis_qualified_target")
        k.validate_graph()
        self.assertEqual(k.question(str(OW.Composite), str(OW.Composite)), "")
        for status in ("present", "uncertain"):
            bad = fact("S.cc", "symptom", OW.Composite, "두통 있어요", status=status)
            parsed = make_interpreter(CONFIG)._validate_facts({"facts": [bad]}, s, k, "두통 있어요")
            self.assertFalse(parsed.accepted_facts)
        s.session.gateway_successes = s.session.doctor_successes = 1
        q = question(s, target=OW.Complaint, attribute=OW.TimeSinceOnset)
        q.answer_type = "duration"
        pending(s, q)

    def test_d17_primary_requires_current_chief_explanation(self):
        s, r = state("Education", True), ClinicalReasoner(knowledge())
        record(s, target=OW.Other)
        record(s, "secondary", target=OW.Complaint, field="S.ros")
        r.select_diagnosis(s)
        self.assertTrue(any(h.evidence_score > 0 for h in s.differential.hypotheses))
        self.assertEqual(s.case.diagnosis_kind, "symptom")
        self.assertEqual(s.case.diagnosis, "별도증상")

    def test_d17_uncertain_chief_confirmation_keeps_its_episode(self):
        k, s, client = knowledge(), state("DifferentialDiagnosis", True), FakeSDK()
        record(s, status="uncertain")
        s.session.gateway_successes = s.session.doctor_successes = 1
        w = make_consultation(client, resources(k))
        w.reasoner.retrieve_candidates(s)
        w.planner.replan(s)
        confirmation = next(q for q in s.questions.questions if q.target_id == str(OW.Complaint) and q.attribute_id is None)
        self.assertEqual((confirmation.observation_id, confirmation.episode_id, confirmation.field), ("obs1", "episode1", "S.cc"))
        pending(s, confirmation)
        s.interaction.incoming = {"content": "네"}
        w.interpreter.process_input(s, k, client)
        w.reasoner.select_diagnosis(s)
        self.assertEqual(s.case.diagnosis_kind, "disease")
        k._graph.add((OW.Other, OW.hasAttribute, OW.Quality))
        k.validate_graph()
        unanchored = fact("S.hpi", "attribute", OW.Other, "다른 양상", attribute=OW.Quality, values=[OW.Dull])
        result = w.interpreter._validate_facts({"facts": [unanchored]}, s, k, "다른 양상")
        self.assertFalse(result.accepted_facts)



    def test_education_exhaustion_preserves_the_complete_plan(self):
        s, client = state("Education", True, turns=3), FakeSDK()
        s.session.gateway_successes = s.session.doctor_successes = 1
        client.remaining = 3
        record(s)
        w = make_consultation(client, resources(config=CONFIG.model_copy(update={"education_enabled": True})))
        w.prepare_education(s)
        result = WorkflowState.model_validate(build_graph(w, w.planner.knowledge).invoke(s.model_dump()))
        self.assertEqual(result.session.turns_remaining, 0)
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(sum(item.status == "delivered" for item in result.questions.education), 3)
        self.assertEqual(sum(item.status == "undelivered" for item in result.questions.education), 2)
        self.assertTrue(all(client.submissions[0]["note"]["P"].values()))

    def test_education_pass_keeps_full_diagnostic_budget_and_empty_education(self):
        self.assertFalse(prepare().config.education_enabled)
        for client in (FakeSDK(), FakeSDK(no_candidate=True)):
            result, client = self.run_flow(client)
            self.assertEqual(result.interaction.termination, "submitted")
            self.assertEqual(result.session.usage["Education"].actions, 0)
            self.assertEqual(result.session.usage["Education"].calls, 0)
            self.assertIn("education_skipped", result.interaction.issues)
            self.assertFalse(any(entry.question and entry.question.purpose == "education"
                                 for entry in result.interaction.history))
            self.assertEqual(client.submissions[0]["note"]["P"]["education"], "")
            self.assertFalse(any(item.value and item.value.kind == "education" for _, item in result.case.entries()))
        s = state("DifferentialDiagnosis", True, turns=1)
        self.assertEqual(BudgetPolicy().action_capacity(s), 1)
        with patch.dict(os.environ, {"ONTOWARD_EDUCATION_ENABLED": "true"}):
            self.assertTrue(TextConfig.load().education_enabled)
        with patch.dict(os.environ, {"ONTOWARD_EDUCATION_ENABLED": "invalid"}):
            with self.assertRaises(ValueError):
                TextConfig.load()






    def test_gateway_exposes_source_aliases_and_filters_chief_retrieval_by_type(self):
        from rdflib import RDFS, SKOS
        k = knowledge()
        k._graph.add((OW.Complaint, RDFS.label, Literal("Reported discomfort", lang="en")))
        k._graph.add((OW.Complaint, SKOS.altLabel, Literal("Current concern", lang="en")))
        k._graph.add((OW.Alpha, RDFS.label, Literal("Current concern", lang="en")))
        k.validate_graph()
        before = frozenset(k._graph)
        concept = k.concepts([str(OW.Complaint)])[0]
        self.assertEqual(concept["label"], "가상증상")
        self.assertTrue({"Reported discomfort", "Current concern"} <= set(concept["aliases"]))
        self.assertIn(str(OW.Alpha), k.search_concepts("Current concern"))
        self.assertNotIn(str(OW.Alpha), k.search_concepts("Current concern", kind="Symptom"))
        self.assertIn(str(OW.Complaint), k.search_concepts("Current concern", kind="Symptom"))
        self.assertEqual(frozenset(k._graph), before)





    def test_gateway_lookup_hints_have_a_finite_size(self):
        s, k, interpreter = state(), knowledge(), make_interpreter(CONFIG)
        for terms in (["x"] * 9, ["x" * 81], [" "], "not a list"):
            self.assertIsNone(interpreter._validate_facts({"facts": [], "lookup_terms": terms}, s, k, "reported"))
        parsed = interpreter._validate_facts({"facts": [], "lookup_terms": ["Current concern", "Current concern"]}, s, k, "reported")
        self.assertEqual(parsed.lookup_terms, ["Current concern"])

    def test_context_cannot_starve_more_valuable_diagnostic_acquisition(self):
        k, s = knowledge(), state("ContextFactor", True, turns=4)
        record(s)
        complete_common_history(s)
        s.questions.context_coverage.append(str(OW.Context0))
        for i in range(40):
            target = OW[f"Context{i}"]
            k._graph.add((target, RDF.type, OW.ContextFactor))
            k._graph.add((target, OW.contextType, Literal("past_medical_history")))
            for disease in (OW.Alpha, OW.Beta):
                k._graph.add((disease, OW.hasSupportingContext, target))
            k.questions[str(target)] = QuestionTemplate(text=f"가상 병력 {i}이 있나요?", answer_type="presence", affirmative=True)
        k.validate_graph()
        w = make_consultation(prepared=resources(k))
        w.reasoner.retrieve_candidates(s)
        w.prepare_session(s)
        self.assertFalse(s.case.unasked("ContextFactor"))
        w.advance_session(s)
        w.enter_session(s)
        w.planner.select_question(s)
        self.assertEqual(s.interaction.selected.question.kind, "EXAM")
        self.assertEqual(s.interaction.selected.question.target_id, str(OW.ExamX))

    def test_saturated_supporting_context_has_no_remaining_bonus_utility(self):
        k, s = knowledge(), state("DifferentialDiagnosis", True)
        record(s)
        record(s, "history", OW.Context, kind="context", field="S.pmh")
        k._graph.add((OW.MoreContext, RDF.type, OW.ContextFactor))
        k._graph.add((OW.MoreContext, OW.contextType, Literal("past_medical_history")))
        k._graph.add((OW.Alpha, OW.hasSupportingContext, OW.MoreContext))
        k.questions[str(OW.MoreContext)] = QuestionTemplate(text="다른 병력이 있나요?", answer_type="presence", affirmative=True)
        k.validate_graph()
        w = make_consultation(prepared=resources(k))
        w.reasoner.retrieve_candidates(s)
        w.planner.replan(s)
        self.assertFalse(any(q.target_id == str(OW.MoreContext) for q in s.questions.questions))

    def test_primary_anchor_does_not_require_a_single_disease_for_additional_reports(self):
        s, k = state("Education", True), knowledge()
        record(s)
        s.case.get("chief").value.primary_concern = True
        record(s, "second-chief", OW.Other, episode="episode2")
        reasoner = ClinicalReasoner(k)
        reasoner.select_diagnosis(s)
        self.assertEqual(s.case.diagnosis_kind, "disease")
        self.assertTrue(reasoner.supported_hypotheses(s))
        self.assertTrue(all(h.chief_coverage == 1 for h in reasoner.supported_hypotheses(s)))
        make_writer(FakeSDK(), k, CONFIG).build_soap(s)
        self.assertNotIn(k.label(str(OW.Other)), s.interaction.submission_payload["note"]["S"]["cc"])
        self.assertIn(k.label(str(OW.Other)), s.interaction.submission_payload["note"]["S"]["ros"])

    def test_assessment_includes_acquired_positive_and_negative_reasoning_evidence(self):
        k, s = knowledge(), state("Education", True)
        record(s)
        record(s, "negative", OW.Other, field="S.ros", status="absent")
        reasoner = ClinicalReasoner(k)
        reasoner.select_diagnosis(s)
        chosen = s.differential.selected_id
        selected = next(h for h in s.differential.hypotheses if h.disease_id == chosen)
        selected.contradiction_ids = ["negative"]
        with patch.object(reasoner, "refresh_hypotheses"):
            reasoner.select_diagnosis(s)
        self.assertIn("negative", s.case.diagnosis_evidence)
        alternative = next(h for h in s.differential.hypotheses if h.disease_id != chosen)
        alternative.contradiction_ids = ["negative"]
        make_writer(FakeSDK(), k, CONFIG).build_soap(s)
        assessment = s.interaction.submission_payload["note"]["A"]
        self.assertIn("별도증상 (-)", assessment["evidence"])
        self.assertTrue(assessment["evidence"].startswith("Diagnosis: #1. "))
        self.assertIn("\nEvidence: ", assessment["evidence"])
        self.assertTrue(assessment["differential"].startswith("r/o "))
        self.assertIn("별도증상 (-)", assessment["differential"])
        self.assertNotIn("urn:", json.dumps(assessment))

    def test_session_hard_caps_stop_actions_without_borrowing(self):
        for scope, maximum in (("Initiation", 7), ("ChiefComplaint", 14), ("ContextFactor", 9),
                               ("DifferentialDiagnosis", 10), ("Education", 0)):
            with self.subTest(scope=scope):
                s, client = state(scope, True), FakeSDK()
                w = make_consultation(client)
                s.session.questions_prepared = True
                s.session.usage[scope].actions = max(0, maximum - 1)
                q = question(s, target=None, purpose="chief", field="S.cc", text=CONFIG.texts.greeting)
                w.interactions.select_question(s, q)
                w.doctor.validate_action(s)
                w.doctor.execute_action(s, client)
                self.assertEqual(len(client.actions), int(maximum > 0))
                self.assertEqual(s.session.usage[scope].actions, maximum)
                if maximum:
                    w.interpreter.process_input(s, knowledge(), client)
                    q = question(s, ident="over-cap", target=None, purpose="chief", field="S.cc")
                    w.interactions.select_question(s, q)
                    w.doctor.validate_action(s)
                    w.doctor.execute_action(s, client)
                    self.assertEqual(len(client.actions), 1)
                w.check_budget(s)
                self.assertFalse(s.session.finalizing)
                self.assertEqual(route_budget(s), "advance_session")

    def test_usefulness_and_capacity_are_checked_without_new_clinical_revision(self):
        s, w = state("DifferentialDiagnosis", True), make_consultation()
        low = question(s, ident="conditional", order=0)
        low.assessment = {"complete": True, "utility": 0.125}
        zero = question(s, ident="zero", order=1)
        zero.assessment = {"complete": True, "utility": 0}
        for actions in (2, 3):
            s.session.usage[s.session.current].actions = actions
            w.planner.select_question(s)
            self.assertEqual(s.interaction.selected.question.item_id, low.item_id)
            self.assertIsNone(s.case.get(zero.item_id))
            w.interactions.clear_selected(s)
        s.session.usage[s.session.current].actions = 12
        w.check_budget(s)
        self.assertFalse(s.pending_questions())

    def test_conditional_value_survives_target_and_zero_utility_does_not_fill_minimum(self):
        s, w = state("DifferentialDiagnosis", True), make_consultation()
        s.session.usage[s.session.current].actions = 3
        q = question(s)
        q.assessment = {"complete": True, "utility": 0.125}
        w.planner.select_question(s)
        self.assertEqual(s.interaction.selected.question.item_id, q.item_id)
        s, w = state("ContextFactor", True), make_consultation()
        q = question(s, purpose="context")
        q.assessment = {"complete": True, "utility": 0}
        w.planner.select_question(s)
        self.assertEqual(route_budget(s), "advance_session")
        result, _ = self.run_flow()
        self.assertLess(result.session.usage["ChiefComplaint"].actions, 7)

    def test_multiple_reports_require_primary_then_only_its_full_attributes(self):
        k, s = knowledge(), state("ChiefComplaint", True)
        attrs = [OW.Location, OW.Laterality, OW.Quality, OW.TimeSinceOnset, OW.EpisodeDuration, OW.Severity]
        for index in range(3):
            target = OW[f"Chief{index}"]
            k._graph.add((target, RDF.type, OW.Symptom))
            k.questions[str(target)] = QuestionTemplate(text=f"증상{index} 있나요?", answer_type="presence", affirmative=True)
            for attr in attrs:
                k._graph.add((attr, RDF.type, OW.FindingAttribute))
                k._graph.add((target, OW.hasAttribute, attr))
                k.questions[str(target) + "|" + str(attr)] = QuestionTemplate(text="증상을 알려주세요", answer_type="free_text")
            record(s, ident=f"chief-{index}", target=target)
        k.validate_graph()
        w = make_consultation(prepared=resources(k))
        w.planner.prepare_chief_complaint(s)
        w.check_budget(s)
        questions = sorted(s.questions.questions, key=lambda q: q.order)
        self.assertEqual(len(questions), 1)
        self.assertTrue(questions[0].primary_choice)
        s.case.get("chief-1").value.primary_concern = True
        w.planner.prepare_chief_complaint(s)
        questions = sorted(s.pending_questions(), key=lambda q: q.order)
        self.assertEqual(len(questions), 7)
        self.assertEqual(questions[-1].purpose, "open_inquiry")
        self.assertTrue(all(q.target_id == str(OW.Chief1) for q in questions[:-1]))
        self.assertEqual({q.attribute_id for q in questions[:-1]}, set(map(str, attrs)))

    def test_empathy_bypasses_session_caps_but_uses_shared_turns_and_model_budget(self):
        for scope, maximum in (("Initiation", 7), ("ChiefComplaint", 14), ("ContextFactor", 9),
                               ("DifferentialDiagnosis", 10)):
            with self.subTest(scope=scope):
                s, client = state(scope, True), FakeSDK()
                record(s)
                complete_common_history(s)
                s.session.usage[scope].actions = maximum
                w = make_consultation(client)
                q = question(s, purpose="empathy", target=None, text="많이 힘드셨겠어요")
                w.planner.replan(s, force=True)
                w.check_budget(s)
                self.assertIsNotNone(s.case.get(q.item_id))
                w.planner.select_question(s)
                w.doctor.validate_action(s)
                w.doctor.execute_action(s, client)
                w.interpreter.process_input(s, knowledge(), client)
                self.assertEqual(s.session.turns_remaining, 49)
                self.assertEqual(s.session.usage[scope].actions, maximum + 1)
                self.assertEqual(s.session.usage[scope].empathy_actions, 1)
                self.assertEqual(w.budget.interview_actions(s), maximum)
                self.assertEqual(w.budget.action_capacity(s), 0)
                self.assertGreater(s.session.doctor_calls, 0)
                self.assertIsNone(s.interaction.pending)
                self.assertIsNone(s.case.get(q.item_id))
        s, client = state("ChiefComplaint", True), FakeSDK()
        s.session.call_limit = 1
        client.chat = Mock(return_value=client.completion("많이 힘드셨겠어요"))
        w = make_consultation(client)
        self.assertEqual(w.interpreter.model.complete(s, client, role="empathy", messages=[]), "많이 힘드셨겠어요")
        self.assertEqual((s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens), (1, 20, 10))
        self.assertEqual(s.session.doctor_successes, 1)
        self.assertEqual(s.session.gateway_successes, 0)
        q = question(s, purpose="empathy", target=None)
        w.interactions.select_question(s, q)
        w.doctor.validate_action(s)
        w.doctor.execute_action(s, client)
        self.assertTrue(s.session.finalizing)
        self.assertFalse(client.actions)


    def test_exhausted_transient_gateway_stops_without_actions_or_submission(self):
        client, requests = FakeSDK(), []
        def chat(**kwargs):
            requests.append(copy.deepcopy(kwargs))
            raise NovaError("REQUEST_PENDING")
        client.chat = chat
        with patch("workflow.io.request_executor.time.sleep") as sleep:
            result, _ = self.run_flow(client)
        self.assertEqual(result.interaction.termination, "unknown")
        self.assertEqual(requests, [requests[0]] * 2)
        sleep.assert_called_once_with(2)
        self.assertEqual(result.session.doctor_calls, 1)
        self.assertFalse(client.actions)
        self.assertFalse(client.submissions)

    def test_transient_does_not_replay_without_delay_and_phase_reserve(self):
        clock = datetime(2026, 10, 17, tzinfo=timezone.utc)
        s, client, attempts = state(), FakeSDK(), []
        s.session.deadline = clock + timedelta(seconds=241)
        w = assemble_consultation(client, resources(), now=lambda: clock, sleep=Mock())
        call = Mock(side_effect=NovaError("API_UNAVAILABLE"))
        with self.assertRaises(NovaError):
            w.doctor.executor.execute(s, client, call, {}, attempts, action=True)
        call.assert_called_once()
        w.doctor.executor.sleep.assert_not_called()
        self.assertEqual(client.timeout, 120)


    def test_pain_assessment_uses_reported_scale_and_same_episode_only(self):
        from rdflib import RDFS
        k, s = knowledge(), state("Education", True)
        for concept, label in ((OW.Pain, "Chest pain"), (OW.Here, "Chest"), (OW.Dull, "Dull")):
            k._graph.add((concept, RDFS.label, Literal(label, lang="en")))
        k._graph.add((OW.Pain, RDF.type, OW.Symptom))
        record(s, target=OW.Pain)
        for ident, attribute, values, measurement in (
            ("location", OW.Location, [OW.Here], None), ("quality", OW.PainQuality, [OW.Dull], None),
            ("duration", OW.EpisodeDuration, [], ExpectedValue(kind="quantity", value=30, unit="min")),
            ("score", OW.Severity, [], ExpectedValue(kind="quantity", value=6, unit="NRS"))):
            record(s, ident, OW.Pain, kind="attribute", field="S.hpi", attribute=attribute, values=values)
            s.case.get(ident).value.measurement = measurement
        record(s, "old-score", OW.Pain, kind="attribute", field="S.hpi", attribute=OW.Severity, episode="old")
        s.case.get("old-score").value.measurement = ExpectedValue(kind="quantity", value=9, unit="NRS")
        s.case.get("old-score").value.time_context = "past"
        writer = make_writer(FakeSDK(), k, CONFIG)
        writer.build_soap(s)
        note = s.interaction.submission_payload["note"]["S"]
        self.assertTrue(note["cc"].startswith("C.C: Chest pain"))
        self.assertNotIn("Pain assessment:", note["cc"])
        self.assertIn("Pain assessment: Location: Chest; Quality: Dull; Duration: 30 min; Severity: NRS 6", note["hpi"])
        self.assertNotIn("NRS 9", note["hpi"].split("\n")[1])
        s.case.get("score").value.measurement = ExpectedValue(kind="quantity", value=6, unit="score")
        writer.build_soap(s)
        self.assertNotIn("NRS 6", s.interaction.submission_payload["note"]["S"]["hpi"])
        s.case.remove({"score", "location", "quality", "duration"})
        writer.build_soap(s)
        self.assertIn("Pain assessment: Unknown", s.interaction.submission_payload["note"]["S"]["hpi"])

    def test_history_english_source_terms_negatives_unknowns_and_unasked(self):
        from rdflib import RDFS
        k, s = knowledge(), state("Education", True)
        for concept, label in ((OW.DM, "Diabetes mellitus"), (OW.FamilyDM, "Family history of diabetes")):
            k._graph.add((concept, RDFS.label, Literal(label, lang="en")))
        record(s, "dm", OW.DM, kind="context", field="S.pmh", status="absent")
        record(s, "family-dm", OW.FamilyDM, kind="context", field="S.fh", status="present")
        s.case.get("family-dm").value.subject = "family"
        record(s, "allergy", OW.Context, kind="context", field="S.pmh", status="unknown")
        s.case.get("allergy").value.concept_ids = []
        s.case.get("allergy").value.record_category = "allergy"
        s.case.put("S.pmh", RecordItem(id="unasked-htn", scope="ContextFactor"))
        make_writer(FakeSDK(), k, CONFIG).build_soap(s)
        note = s.interaction.submission_payload["note"]["S"]
        self.assertIn("DM: (-)", note["pmh"])
        self.assertNotIn("Allergy: (Unknown)", note["pmh"])
        self.assertNotIn("Allergy: (-)", note["pmh"])
        self.assertNotIn("HTN", note["pmh"])
        self.assertTrue(note["fh"].startswith("DM: (+)"))
        self.assertEqual(note["sh"], "")

    def test_record_keywords_require_quotes_categories_and_explicit_nrs(self):
        k, s = knowledge(), state("ChiefComplaint", True)
        gateway = make_interpreter(CONFIG)
        raw = {"field":"S.sh", "quote":"술은 주 2회 마셔요.", "value":{"kind":"text", "text":"술은 주 2회 마셔요.",
            "status":"present", "record_category":"alcohol", "record_details":[{"quote":"주 2회", "english":"Twice/week"}]}}
        parsed = gateway._validate_facts({"facts":[raw]}, s, k, raw["quote"])
        self.assertEqual(len(parsed.accepted_facts), 1)
        gateway._apply_facts(s, parsed, "reported")
        make_writer(FakeSDK(), k, CONFIG).build_soap(s)
        self.assertEqual(s.interaction.submission_payload["note"]["S"]["sh"], "")
        forged = copy.deepcopy(raw)
        forged["value"]["record_details"][0]["quote"] = "주 3회"
        self.assertTrue(gateway._validate_facts({"facts":[forged]}, s, k, raw["quote"]).rejected_facts)
        forged = copy.deepcopy(raw)
        forged["value"]["record_category"] = "allergy"
        routed = gateway._validate_facts({"facts":[forged]}, s, k, raw["quote"])
        self.assertEqual(routed.accepted_facts[0].field, "S.pmh")
        forged = copy.deepcopy(raw)
        del forged["value"]["record_category"]
        self.assertTrue(gateway._validate_facts({"facts":[forged]}, s, k, raw["quote"]).rejected_facts)
        record(s)
        k._graph.add((OW.Complaint, OW.hasAttribute, OW.Severity))
        k._graph.add((OW.Severity, RDF.type, OW.FindingAttribute))
        score = fact("S.hpi", "attribute", OW.Complaint, "6점", attribute=OW.Severity, values=[])
        score["value"]["measurement"] = {"kind":"quantity", "value":6, "unit":"NRS"}
        self.assertTrue(gateway._validate_facts({"facts":[score]}, s, k, "6점").rejected_facts)
        score["quote"] = score["value"]["text"] = "NRS 6점"
        self.assertEqual(len(gateway._validate_facts({"facts":[score]}, s, k, "NRS 6점").accepted_facts), 1)
        raw_onset = {"field":"S.hpi", "quote":"3일 전부터", "value":{"kind":"text", "text":"3일 전부터",
            "status":"present", "record_category":"onset", "observation_id":"obs1", "episode_id":"episode1",
            "record_details":[{"quote":"3일 전부터", "english":"3 days before presentation"}]}}
        parsed = gateway._validate_facts({"facts":[raw_onset]}, s, k, raw_onset["quote"])
        self.assertEqual(len(parsed.accepted_facts), 1)
        gateway._apply_facts(s, parsed, "reported-onset")
        make_writer(FakeSDK(), k, CONFIG).build_soap(s)
        note = s.interaction.submission_payload["note"]["S"]
        self.assertNotIn("Onset:", note["cc"])
        self.assertNotIn("3 days before presentation", note["hpi"])

    def test_record_keywords_preserve_reasoning_and_multiple_chief_hpi_links(self):
        k, s = knowledge(), state("DifferentialDiagnosis", True)
        record(s)
        reasoner = ClinicalReasoner(k)
        reasoner.retrieve_candidates(s)
        before = (s.differential.clinical_revision, s.differential.refreshes, s.differential.model_dump())
        s.case.get("chief").value.record_details = [{"quote":"synthetic", "english":"Reported symptom"}]
        reasoner.refresh_hypotheses(s)
        self.assertEqual((s.differential.clinical_revision, s.differential.refreshes, s.differential.model_dump()), before)
        record(s, "other-chief", OW.Other)
        record(s, "first-location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        record(s, "other-location", OW.Other, kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Elsewhere])
        make_writer(FakeSDK(), k, CONFIG).build_soap(s)
        note = s.interaction.submission_payload["note"]["S"]
        self.assertIn("Location: 가상증상 - 가상부위", note["hpi"])
        self.assertIn("Location: 별도증상 - 다른부위", note["hpi"])
        self.assertNotIn("Episode", note["cc"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Verification)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"tests": result.testsRun, "failures": [str(t) for t, _ in result.failures],
              "errors": [str(t) for t, _ in result.errors], "successful": result.wasSuccessful(),
              "dependencies": {name: version(name) for name in ("langgraph", "pydantic", "rdflib")},
              "runtime_assets": str(COPY / "knowledge"), "network": "none", "real_doctor": "not_run", "official_sdk": "not_run"}
    (HERE / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
