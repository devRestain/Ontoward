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
    for slot in HISTORY:
        state.case.put(CATEGORY_FIELDS[slot], RecordItem(id="history:" + slot, scope="ContextFactor", status="done",
            source_refs=["initial"], acquisition="initial", value=ClinicalValue(kind="text", text="denied",
                status="absent", record_category=slot, evidence_use="record_only")))


class IntakeSOAP(unittest.TestCase):
    def setUp(self):
        self.client = f.FakeSDK()
        self.k = f.knowledge()
        self.agent = f.make_consultation(self.client, f.resources(self.k))

    def initial(self, text, payload):
        s = f.state()
        self.client.chat = Mock(return_value=self.client.completion(json.dumps(payload, ensure_ascii=False)))
        s.interaction.incoming = {"initial": {"opening": text}}
        self.agent.interpreter.process_input(s, self.k, self.client)
        return s

    def test_c03_compact_facts_preserve_patient_reporter_all_four_measurements_and_time(self):
        root = f.PROJECT / "Tmp/test-evaluator/C03-20261017T123828Z-bad389c34d/simulator/transcript.json"
        text = json.loads(root.read_text())["initial"]["opening"] if root.exists() else C03_OPENING
        payload = {"patient_context": [
            {"key": "age", "value": "6 years", "quote": "여섯 살 남자아이"},
            {"key": "sex", "value": "male", "quote": "여섯 살 남자아이"},
            {"key": "reporter", "value": "mother", "quote": "엄마 김지영"}], "facts": [
            {"field": "S.cc", "quote": "키가 또래에 비해 많이 작은 것 같아", "value": {
                "kind": "symptom", "status": "present", "concept_ids": [str(f.OW.Complaint)], "reported_by": "mother"}},
            {"quote": "일 년 전부터", "value": {"kind": "text", "status": "present", "record_category": "onset",
                "record_details": ["One year before presentation"], "evidence_use": "record_only"}},
            {"quote": "최근 육 개월에서 일 년 사이에 키가 별로 크지 않은 것 같다고 느꼈다", "value": {
                "kind": "text", "status": "present", "record_category": "course",
                "record_details": ["Perceived slow growth over the past 6-12 months"], "evidence_use": "record_only"}},
            {"quote": "일 년 전에는 백 센티미터였고 지금은 백오 센티미터 정도였다", "value": {
                "kind": "text", "status": "present", "record_category": "measurement", "reported_by": "mother",
                "quantities": [{"name": "Height", "value": 100, "unit": "cm", "when": "one year ago"},
                    {"name": "Height", "value": 105, "unit": "cm", "when": "current", "approximate": True}], "evidence_use": "record_only"}},
            {"quote": "일 년 전 십오 키로그람에서 지금은 십육 점 오 키로그람", "value": {
                "kind": "text", "status": "present", "record_category": "measurement", "reported_by": "mother",
                "quantities": [{"name": "Weight", "value": 15, "unit": "kg", "when": "one year ago"},
                    {"name": "Weight", "value": 16.5, "unit": "kg", "when": "current"}], "evidence_use": "record_only"}}]}
        s = self.initial(text, payload)
        self.assertEqual(len([i for _, i in s.case.entries()]), 5)
        self.assertEqual(s.case.patient_context["age"].value, "6 years")
        self.assertEqual(s.case.patient_context["reporter"].source_refs, ["initial"])
        self.assertEqual(s.case.chief().value.subject, "patient")
        self.agent.writer.build_soap(s)
        note = s.interaction.submission_payload["note"]
        for expected in ("6 years", "male", "mother", "100 cm", "105 cm", "15 kg", "16.5 kg", "one year ago", "6-12 months"):
            self.assertIn(expected, note["S"]["hpi"])
        self.assertEqual(note["O"]["exam"], "")
        self.assertEqual(len(EvidenceIndex.from_case(s.case).entries), 1)
        self.agent.planner.prepare_initiation(s)
        slots = {q.record_category for q in s.pending_questions()}
        self.assertNotIn("onset", slots)
        self.assertNotIn("course", slots)
        self.assertIn("recurrence", slots)

    def test_truncated_historical_c03_responses_use_one_larger_recovery_and_no_terminology(self):
        source = f.PROJECT / "Tmp/test-evaluator/C03-20261017T123828Z-bad389c34d/simulator/requests.json"
        requests = json.loads(source.read_text()) if source.exists() else {}
        ids = ["6420f224-98cb-4e52-bd11-129f8b3b79a8", "e7be2743-a979-4911-90cd-d927c44b63d8"]
        fallback = self.client.completion('{"facts":[')
        fallback["choices"][0]["finish_reason"] = "length"
        self.client.chat = Mock(side_effect=[requests[i]["outcome"][1] if i in requests else copy.deepcopy(fallback) for i in ids])
        s = f.state(); text = "가상증상이 있어요"
        s.interaction.incoming = {"initial": {"opening": text}}
        self.agent.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertEqual([c.kwargs["max_tokens"] for c in self.client.chat.call_args_list], [4096, 8000])
        self.assertEqual(s.session.doctor_successes, 0)
        self.assertEqual(s.session.gateway_successes, 0)
        self.assertFalse(s.case.chief_complaints())
        self.assertEqual(s.interaction.patient_reports[0].text, text)
        self.assertTrue(s.interaction.needs_clarification)

    def test_lookup_recovery_preserves_distinct_record_only_categories_and_measurements(self):
        raw = {"facts": [
            {"field": "S.cc", "quote": "가상증상", "value": {"kind": "symptom", "status": "present",
                "concept_ids": [str(f.OW.Complaint)]}},
            {"quote": "어제부터", "value": {"kind": "text", "status": "present", "record_category": "onset",
                "record_details": ["Since yesterday"], "evidence_use": "record_only"}},
            *[{"quote": quote, "value": {"kind": "text", "status": "present", "record_category": "measurement",
                "quantities": [{"name": name, "value": number, "unit": unit}], "evidence_use": "record_only"}}
              for quote, name, number, unit in (("키 100cm", "Height", 100, "cm"), ("몸무게 15kg", "Weight", 15, "kg"))]]}
        self.client.chat = Mock(side_effect=[self.client.completion(json.dumps(response, ensure_ascii=False))
            for response in ({"facts": [], "needs_context": True, "lookup_terms": ["가상증상"]}, raw)])
        s = f.state()
        s.interaction.incoming = {"initial": {"opening": "가상증상. 어제부터. 키 100cm. 몸무게 15kg."}}
        self.agent.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertEqual(len(list(s.case.entries())), 4)
        self.agent.writer.build_soap(s)
        hpi = s.interaction.submission_payload["note"]["S"]["hpi"]
        self.assertIn("Since yesterday", hpi)
        self.assertIn("100 cm", hpi)
        self.assertIn("15 kg", hpi)
        self.assertEqual(len(EvidenceIndex.from_case(s.case).entries), 1)

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
        self.assertTrue(s.interaction.patient_reports[0].uncovered_spans)
        self.assertFalse(s.interaction.patient_reports[0].clinical_spans)
        self.agent.writer.build_soap(s)
        self.assertEqual(s.interaction.submission_payload["note"]["S"]["hpi"], "")

    def test_patient_context_survives_required_request_fitting(self):
        s = f.state("ChiefComplaint", True); f.record(s); s.case.select_primary()
        s.case.patient_context["age"] = PatientContextEntry(value="6 years", quote="여섯 살", source_refs=["initial"])
        q = f.question(s, target=f.OW.Complaint, attribute=f.OW.Location, purpose="hpi", field="S.hpi")
        f.pending(s, q)
        self.agent.interpreter._request_parse(s, self.k, self.client, "가상부위예요")
        payload = json.loads(self.client.calls[0]["messages"][1]["content"])
        self.assertEqual(payload["patient_context"]["age"]["value"], "6 years")
        self.assertIn(str(f.OW.Complaint), {c["id"] for c in payload["vocabulary"]})
        self.assertNotIn("text", parser_schema()["$defs"]["ClinicalValue"]["properties"])

    def test_semantic_routing_preserves_incidental_medication_in_cc(self):
        s = self.initial("약은 복용하지 않아요", {"facts": [{"field": "S.sh", "quote": "약은 복용하지 않아요",
            "value": {"kind": "text", "status": "absent", "record_category": "medication", "evidence_use": "record_only"}}]})
        self.agent.writer.build_soap(s)
        self.assertIn(f.CONFIG.texts.record_labels["medication"], s.interaction.submission_payload["note"]["S"]["pmh"])
        self.assertEqual(s.interaction.submission_payload["note"]["S"]["sh"], "")

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
        s.case.put("S.hpi", RecordItem(id="care:not-applicable", scope="Initiation", status="done", source_refs=["initial"],
            value=ClinicalValue(kind="text", text="No relevant treatment", status="unknown", not_applicable=True,
                record_category="previous_care", evidence_use="record_only")))
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
