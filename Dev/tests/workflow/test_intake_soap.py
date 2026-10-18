"""D40 input, collection and record integrity through the consultation consumer."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_workflow as f
from workflow.input_interpreter import parser_schema
from workflow.rules.collection import HISTORY, CATEGORY_FIELDS
from workflow.rules.limits import LIMITS, SESSION_INTERVIEW_LIMITS
from workflow.state.evidence import EvidenceIndex
from workflow.state.models import ClinicalValue, PatientContextEntry, RecordItem, InteractionEntry


C03_OPENING = '이름은 김도현이고, 여섯 살 남자아이이다. 엄마 김지영, 서른일곱 살이 보호자로 함께 왔다. 엄마는 도현이 키가 또래에 비해 많이 작은 것 같아 걱정이 된다고 말했다. 어린이집에서 같은 반 친구들보다 도현이 키가 확실히 작아 보인다고 한다. 엄마는 일 년 전부터 주변에서 도현이가 또래보다 작다는 말을 듣기 시작했다고 했다. 특히 최근 육 개월에서 일 년 사이에 키가 별로 크지 않은 것 같다고 느꼈다. 엄마가 집에서 키를 재보니, 일 년 전에는 백 센티미터였고 지금은 백오 센티미터 정도였다. 일 년 동안 오 센티미터 정도 자랐다. 몸무게는 일 년 전 십오 키로그람에서 지금은 십육 점 오 키로그람으로 일 점 오 키로그람 늘었다.'


def history(state):
    from workflow.state.models import InputOutcome
    for slot in HISTORY:
        state.case.outcomes.append(InputOutcome(source_ref="initial", statement_id="history:" + slot,
            state="unsupported", record_category=slot))


class IntakeSOAP(unittest.TestCase):
    def setUp(self):
        self.client = f.FakeSDK()
        self.k = f.knowledge()
        self.agent = f.make_consultation(self.client, f.resources(self.k))

    def initial(self, text, payload):
        s = f.state()
        from normalization_fixtures import fixture_chat
        self.client.chat = Mock(side_effect=fixture_chat(self.client, payload.get("facts", []), empathy=payload.get("empathy")))
        s.interaction.incoming = {"initial": {"opening": text}}
        self.agent.interpreter.process_input(s, self.k, self.client)
        return s




    def test_invalid_json_does_not_trigger_terminology_or_unstructured_soap(self):
        self.client.chat = Mock(return_value=self.client.completion('{'))
        s = f.state()
        s.interaction.incoming = {"initial": {"opening": "안녕하세요. 검사를 받으러 오겠습니다."}}
        self.agent.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertEqual({entry["role"] for entry in s.interaction.model_history}, {"gateway"})
        self.assertEqual(s.interaction.patient_reports[0].text, "안녕하세요. 검사를 받으러 오겠습니다.")
        self.assertFalse(s.interaction.patient_reports[0].clinical_spans)
        self.agent.writer.build_soap(s)
        self.assertTrue(all(not value for value in s.interaction.submission_payload["note"]["S"].values()))

    def test_unclassified_raw_speech_remains_in_history_without_hpi_fallback(self):
        s = self.initial("감사합니다. 다음에 또 오겠습니다.", {"facts": [], "clinical_content": False})
        self.assertEqual(s.interaction.patient_reports[0].text, "감사합니다. 다음에 또 오겠습니다.")
        self.assertFalse(s.interaction.patient_reports[0].clinical_spans)
        self.agent.writer.build_soap(s)
        self.assertEqual(s.interaction.submission_payload["note"]["S"]["hpi"], "")



    def test_nonclinical_spans_do_not_hide_a_mixed_new_symptom(self):
        text = "네, 그런데 다른 증상도 있어요. 두통이 생기면 오겠습니다."
        payload = {"facts": [f.fact("S.ros", "symptom", f.OW.Other, "다른 증상도 있어요")],
            "spans": [{"quote": "네, 그런데", "role": "nonclinical"}, {"quote": "두통이 생기면 오겠습니다.", "role": "conditional"}]}
        s = self.initial(text, payload)
        self.agent.writer.build_soap(s)
        wire = json.dumps(s.interaction.submission_payload, ensure_ascii=False)
        self.assertNotIn("오겠습니다", wire)
        self.assertNotIn("네, 그런데", wire)
        self.assertIn(str(f.OW.Other), EvidenceIndex.from_case(s.case).entries[0][1].value.concept_ids)

    def test_linked_clarification_has_one_shared_current_representative(self):
        s = f.state("ChiefComplaint", True); f.record(s, status="uncertain"); s.case.select_primary()
        self.agent.planner.prepare_chief_complaint(s)
        q = next(q for q in s.pending_questions() if q.purpose == "clarification")
        f.pending(s, q); s.interaction.incoming = {"content": "네"}; s.session.gateway_successes = 1
        self.agent.interpreter.process_input(s, self.k, self.client)
        self.agent.reasoner.refresh_hypotheses(s)
        self.agent.writer.build_soap(s)
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertNotIn("Uncertain", s.interaction.submission_payload["note"]["S"]["cc"])
        self.assertNotIn("chief", [i.id for _, i in s.case.current_entries()])

    def test_distinct_family_members_never_conflict(self):
        s = f.state()
        for member, amount in (("mother", 165), ("father", 178)):
            s.case.put("S.fh", RecordItem(id=member, scope="ContextFactor", status="done", source_refs=["initial"],
                value=ClinicalValue(kind="context", text="reported height", status="present", subject="family",
                    subject_member=member, concept_ids=[str(f.OW.Context)], evidence_use="record_only")))
        self.assertEqual([i.value.status for _, i in s.case.current_entries()], ["present", "present"])

    def test_greeting_then_all_common_slots_without_graph_attributes(self):
        s = f.state(); f.record(s); s.case.select_primary()
        self.k._graph.remove((f.OW.Complaint, f.OW.hasAttribute, None))
        self.agent.planner.prepare_initiation(s)
        questions = sorted(s.pending_questions(), key=lambda q:q.order)
        self.assertEqual(questions[0].text, f.CONFIG.texts.greeting)
        self.assertEqual([q.record_category for q in questions[1:]], ["onset", "course", "recurrence", "previous_care"])
        self.assertTrue(all(q.target_id is None for q in questions))
        from workflow.state.models import InputOutcome
        s.case.outcomes.append(InputOutcome(source_ref="initial", statement_id="care:not-applicable",
            state="not_applicable", record_category="previous_care"))
        self.agent.planner.prepare_initiation(s)
        self.assertNotIn("previous_care", {q.record_category for q in s.pending_questions()})
        self.assertEqual(s.questions.intake["previous_care"], "not_applicable")

    def test_context_zero_utility_cannot_skip_basic_or_graph_coverage(self):
        s = f.state("ContextFactor", True); f.record(s); s.case.select_primary()
        self.agent.planner.prepare_context_questions(s)
        self.assertEqual({q.record_category for q in s.pending_questions()}, set(HISTORY))
        history(s)
        self.k._graph.add((f.OW.ContextTwo, f.RDF.type, f.OW.ContextFactor))
        self.k._graph.add((f.OW.ContextTwo, f.OW.contextType, f.Literal("family_history")))
        self.k._graph.add((f.OW.Beta, f.OW.hasSupportingContext, f.OW.ContextTwo))
        self.k.questions[str(f.OW.ContextTwo)] = f.QuestionTemplate(text="가족 중 관련 병력이 있나요?", answer_type="presence", affirmative=True)
        def zeros(_, specs, paths):
            return {key:{"utility":0.0,"complete":True} for key in specs}
        with patch("workflow.interview_planner.QuestionEvaluation.assess", zeros):
            self.agent.planner.replan(s, force=True)
        q = next(q for q in s.pending_questions() if q.purpose == "context")
        self.assertTrue(q.coverage)
        self.assertEqual(q.assessment["utility"], 0)
        self.agent.planner.select_question(s)
        self.assertEqual(s.interaction.selected.question.item_id, q.item_id)
        self.assertFalse(any(i.value and i.value.kind == "context" for _,i in s.case.entries()))

    def test_future_minimums_and_current_required_work_protect_against_empathy(self):
        s = f.state("ChiefComplaint", True, turns=14); f.record(s); s.case.select_primary()
        self.agent.budget.education_enabled = True
        self.assertEqual(self.agent.budget.action_capacity(s), 0)
        self.assertEqual(self.agent.budget.action_capacity(s, purpose="empathy"), 0)
        self.assertEqual(sum(v[1] for v in SESSION_INTERVIEW_LIMITS.values()), 50)

    def test_record_only_observations_never_enter_reasoning(self):
        s = f.state(); f.record(s)
        f.record(s, "observed", f.OW.Other, field="S.ros")
        s.case.get("observed").value.evidence_use = "record_only"
        self.assertEqual([i.id for _,i in EvidenceIndex.from_case(s.case).entries], ["chief"])

    def test_conditional_speech_cannot_establish_a_current_symptom(self):
        s=f.state();text="두통이 생기면 오겠습니다"
        result=self.agent.interpreter._validate_facts({"facts":[f.fact("S.ros","symptom",f.OW.Other,text)],
            "spans":[{"quote":text,"role":"conditional"}]},s,self.k,text)
        self.assertFalse(result.accepted_facts)
        self.assertEqual(result.rejected_facts[0]["reason"],"nonclinical_or_conditional_assertion")

    def test_conflicting_patient_and_caregiver_ages_are_not_last_value_wins(self):
        s=f.state();text="아이는 여섯 살, 엄마는 서른일곱 살"
        result=self.agent.interpreter._validate_facts({"patient_context":[
            {"key":"age","value":"6 years","quote":"아이는 여섯 살"},
            {"key":"age","value":"37 years","quote":"엄마는 서른일곱 살"}]},s,self.k,text)
        self.assertFalse(result.patient_context)
        self.assertTrue(result.needs_context)

    def test_education_reply_is_only_transcript_even_with_injected_facts_and_distress(self):
        s = f.state("Education", True); f.record(s)
        q = f.question(s, ident="education", target=None, purpose="education", field="P.education")
        f.pending(s,q); s.session.gateway_successes=0
        text="네, 다른 증상도 있고 너무 걱정돼요"
        s.interaction.history.append(InteractionEntry(id="request-1", kind="SAY", delivered=True,
            question=q,request={"content":q.text},response={"content":text}))
        before=copy.deepcopy(s.case.model_dump())
        s.interaction.incoming={"content":text,"facts":[f.fact("S.ros","symptom",f.OW.Other,text)],
            "empathy":{"quote":text,"intent":"new_distress"}}
        self.client.chat=Mock(side_effect=AssertionError("Education must not interpret replies"))
        self.agent.interpreter.process_input(s,self.k,self.client)
        self.assertEqual(s.case.model_dump(),before)
        self.assertFalse(s.interaction.empathy_events)
        self.assertFalse(s.interaction.patient_reports)
        self.assertIsNone(s.interaction.pending)
        self.assertEqual(s.interaction.dialogue()[-1]["patient"],text)

    def test_education_atomic_group_is_not_partly_kept_by_budget(self):
        s=f.state("Education",True,turns=2);self.agent.budget.education_enabled=True
        for index in range(3):
            q=f.Question(item_id=f"edu:{index}",purpose="education",field="P.treatment",text="검증된 설명입니다.",
                order=index,priority=0,plan_sentence_id="conditional-treatment")
            self.agent.questions.register(s,q)
        decision=self.agent.budget.evaluate(s)
        self.assertEqual(decision.discard,{f"edu:{i}" for i in range(3)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
