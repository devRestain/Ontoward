"""D34 offline behavior using the maintained synthetic submission fixture."""
import copy
import json
import unicodedata
import unittest
from unittest.mock import Mock, patch

from test_workflow import (CONFIG, HERE, FakeSDK, OW, fact, knowledge, make_consultation,
                           pending, question, record, resources, state)
from workflow.graph import build_graph, route_budget
from workflow.rules.input import fixed_reply
from workflow.state.models import EmpathySignal, InteractionEntry, Question, WorkflowState


class Verification(unittest.TestCase):
    def setUp(self):
        self.k, self.client = knowledge(), FakeSDK()
        self.consultation = make_consultation(self.client, resources(self.k, CONFIG))
        self.interpreter = self.consultation.interpreter

    def clinical_reply(self, text, attribute=OW.Location):
        s = state("ChiefComplaint", True)
        s.session.gateway_successes = s.session.doctor_successes = 1
        record(s)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=attribute, field="S.hpi", text="어느 부위인가요?")
        q.observation_id, q.episode_id, q.time_context = "obs1", "episode1", "current"
        pending(s, q)
        s.interaction.incoming = {"content": text}
        return s, q

    def respond(self, responses):
        self.payloads = []
        responses = iter(responses)
        def chat(messages, **kwargs):
            self.payloads.append(json.loads(messages[1]["content"]))
            value = next(responses)
            return self.client.completion(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        self.client.chat = Mock(side_effect=chat)

    @staticmethod
    def greeting(s):
        q = Question(item_id="Initiation:chief", field="S.cc", purpose="chief", text=CONFIG.texts.chief_question, order=0, priority=1)
        s.interaction.history.append(InteractionEntry(id="greeting", kind="SAY", delivered=True, question=q,
            request={"content": q.text}, response={"content": "네"}, turn=1))

    def test_expected_attribute_aliases_and_transmitted_value_enum(self):
        from rdflib import SKOS, Literal
        self.k._graph.add((OW.Here, SKOS.altLabel, Literal("source alias", lang="en")))
        self.k._label_index = self.k._concept_cache = None
        s, q = self.clinical_reply("source alias 부위예요")
        answer = fact("S.hpi", "attribute", OW.Complaint, s.interaction.incoming["content"],
                      q=q.model_dump(), attribute=OW.Location, values=[OW.Here])
        self.respond([{"facts": [answer]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 1)
        payload = self.payloads[0]
        binding = payload["binding_contract"]
        self.assertEqual(binding["target_id"], str(OW.Complaint))
        self.assertEqual(binding["attribute_id"], str(OW.Location))
        self.assertEqual(set(binding["value_ids"]), {str(OW.Here), str(OW.Elsewhere)})
        current = payload["schema"]["properties"]["facts"]["items"]["allOf"][0]["then"]
        self.assertEqual(set(current["properties"]["value"]["properties"]["values"]["items"]["enum"]), set(binding["value_ids"]))
        self.assertEqual(s.case.get(q.item_id).value.values, [str(OW.Here)])
        bad = copy.deepcopy(answer)
        bad["value"]["values"] = [str(OW.Dull)]
        self.assertTrue(self.interpreter._validate_facts({"facts": [bad]}, s, self.k, bad["quote"]).rejected_facts)

    def test_exact_categorical_alias_keeps_fixed_path(self):
        s, _ = self.clinical_reply("가상부위")
        result = fixed_reply(CONFIG, s, "가상부위", self.k)
        self.assertEqual(result.facts[0].value.values, [str(OW.Here)])

    def test_current_question_reference_survives_optional_record_trimming(self):
        text = "가상부위 쪽이에요"
        s, q = self.clinical_reply(text)
        answer = fact("S.hpi", "attribute", OW.Complaint, text, q=q.model_dump(), attribute=OW.Location, values=[OW.Here])
        self.respond([{"facts": [answer]}])
        with patch.object(self.consultation.interactions, "project_context", return_value={"records": [], "dialogue": []}):
            self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 1)
        self.assertEqual(s.case.get(q.item_id).value.values, [str(OW.Here)])
        self.assertFalse(s.interaction.parse_rejections)

    def test_empty_nonchief_answer_recovers_instead_of_silently_finishing(self):
        text = "가상부위 쪽이에요"
        s, q = self.clinical_reply(text)
        answer = fact("S.hpi", "attribute", OW.Complaint, text, q=q.model_dump(), attribute=OW.Location, values=[OW.Here])
        self.respond([{"facts": []}, {"facts": [answer]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertEqual(s.case.get(q.item_id).value.values, [str(OW.Here)])
        self.assertFalse(s.interaction.needs_clarification)

    def test_attribute_without_value_is_rejected_and_repaired(self):
        text = "가상부위 쪽이에요"
        s, q = self.clinical_reply(text)
        empty = fact("S.hpi", "attribute", OW.Complaint, text, q=q.model_dump(), attribute=OW.Location, values=[])
        repaired = copy.deepcopy(empty)
        repaired["repair_of"] = 0
        repaired["value"]["values"] = [str(OW.Here)]
        self.respond([{"facts": [empty]}, {"facts": [repaired]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertEqual(s.case.get(q.item_id).value.values, [str(OW.Here)])
        self.assertTrue(any("Substantive attribute" in item["reason"] for item in s.interaction.parse_rejections))

    def height_input(self):
        text = "엄마가 집에서 키를 재보니, 일 년 전에는 백 센티미터였고 지금은 백오 센티미터 정도였다."
        bad = {"field": "S.hpi", "value": {"kind": "finding", "text": text, "status": "present", "subject": "patient",
            "time_context": "current", "measurement": {"kind": "quantity", "value": 105, "operator": "eq", "unit": "cm"}},
            "quote": text, "context_refs": []}
        preserved = {"field": "S.hpi", "repair_of": 1, "quote": text, "value": {"kind": "text", "text": text,
            "status": "present", "subject": "patient", "time_context": "unspecified", "record_category": "other",
            "record_details": [{"quote": text, "english": "Mother measured height at home: 100 cm one year ago; approximately 105 cm currently"}]}}
        s = state()
        s.interaction.incoming = {"initial": {"opening": "가상증상이 있어요. " + text}}
        chief = fact("S.cc", "symptom", OW.Complaint, "가상증상이 있어요")
        return s, bad, preserved, chief

    def test_reported_heights_use_three_calls_and_remain_subjective_record_only(self):
        s, bad, preserved, chief = self.height_input()
        before = frozenset(self.k._graph)
        self.respond([{"facts": [chief, bad]}, {"facts": []}, {"facts": [preserved]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual([entry["role"] for entry in s.interaction.model_history], ["gateway", "gateway", "terminology"])
        reports = [item for item in s.case.S["hpi"].values() if item.value and item.value.record_details]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].value.kind, "text")
        self.assertIsNone(reports[0].value.measurement)
        self.assertEqual(reports[0].value.concept_ids, [])
        self.assertIn("100 cm one year ago", reports[0].value.record_details[0].english)
        self.assertIn("approximately 105 cm currently", reports[0].value.record_details[0].english)
        self.assertFalse(s.case.O["exam"])
        self.assertEqual(s.case.chief_complaints()[0].value.concept_ids, [str(OW.Complaint)])
        self.assertEqual(frozenset(self.k._graph), before)
        self.assertTrue(any("numeric attribute value" in item["reason"] for item in s.interaction.parse_rejections))
        self.assertEqual([step["pass"] for step in s.interaction.parse_recoveries], ["primary", "expansion", "terminology"])
        for entry in s.interaction.model_history:
            metrics = entry["parser_payload"]
            actual = len(json.dumps(entry["request"]["messages"], ensure_ascii=False, separators=(",", ":")).encode())
            self.assertEqual(actual, metrics["request_bytes"])
            self.assertLessEqual(actual, metrics["request_byte_limit"])

    def test_recovery_can_correct_finding_type_without_rewriting_frozen_chief(self):
        s, bad, preserved, chief = self.height_input()
        self.respond([{"facts": [chief, bad]}, {"facts": [preserved]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertFalse(s.interaction.needs_clarification)
        self.assertTrue(any(item.value and item.value.record_details for item in s.case.S["hpi"].values()))
        self.assertTrue(s.interaction.parse_rejections)
        self.assertNotIn("invalid_gateway_expansion", s.interaction.issues)

    def test_final_fallback_cannot_create_ontology_or_measurement_evidence(self):
        s, bad, preserved, chief = self.height_input()
        preserved["value"]["concept_ids"] = [str(OW.Complaint)]
        self.respond([{"facts": [chief, bad]}, {"facts": []}, {"facts": [preserved]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 3)
        self.assertFalse(any(item.value and item.value.record_details for item in s.case.S["hpi"].values()))
        self.assertTrue(s.interaction.parse_rejections)

    def test_clinical_recovery_and_empathy_share_a_four_request_ceiling(self):
        s, bad, preserved, chief = self.height_input()
        s.interaction.incoming["initial"]["opening"] += " 걱정돼요."
        self.respond([{"facts": [chief, bad], "empathy": {"quote": "걱정돼요", "intent": "new_distress"}},
                      {"facts": []}, {"facts": [preserved]}, {"text": "걱정되셨겠어요. 곁에서 들을게요."}])
        self.interpreter.process_input(s, self.k, self.client)
        self.greeting(s)
        self.consultation.select_action(s)
        self.assertEqual(self.client.chat.call_count, 4)
        self.assertEqual([entry["role"] for entry in s.interaction.model_history], ["gateway", "gateway", "terminology", "empathy"])
        self.assertEqual(s.session.gateway_successes, 2)
        self.consultation.doctor.validate_action(s)
        self.consultation.doctor.execute_action(s, self.client)
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 4)

    def test_repaired_attribute_can_use_a_frozen_same_response_anchor(self):
        s = state()
        text = "가상증상이고 가상부위예요"
        s.interaction.incoming = {"initial": {"opening": text}}
        chief = fact("S.cc", "symptom", OW.Complaint, "가상증상")
        empty = fact("S.hpi", "attribute", OW.Complaint, "가상부위", attribute=OW.Location, values=[])
        repaired = copy.deepcopy(empty)
        repaired["repair_of"] = 1
        repaired["value"]["values"] = [str(OW.Here)]
        self.respond([{"facts": [chief, empty]}, {"facts": [repaired]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertTrue(any(item.value and item.value.values == [str(OW.Here)] for item in s.case.S["hpi"].values()))

    def test_record_only_fallback_does_not_resolve_a_pending_clinical_slot(self):
        text = "정확한 부위 대신 낯선 감각만 설명해요"
        s, q = self.clinical_reply(text)
        report = {"field": "S.hpi", "quote": text, "value": {"kind": "text", "text": text, "status": "present",
            "record_category": "other", "record_details": [{"quote": text, "english": "Unlocalized reported sensation"}]}}
        self.respond([{"facts": []}, {"facts": []}, {"facts": [report]}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 3)
        self.assertTrue(s.interaction.needs_clarification)
        self.assertEqual(s.case.get(q.item_id).value.status, "unknown")
        self.assertTrue(any(item.value and item.value.record_details for item in s.case.S["hpi"].values()))

    def test_exhausted_call_budget_preserves_report_without_more_requests(self):
        s, _, _, chief = self.height_input()
        s.session.call_limit = 1
        unlinked = copy.deepcopy(chief)
        unlinked["value"]["concept_ids"] = []
        self.respond([{"facts": [unlinked], "needs_context": True}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 1)
        self.assertEqual(s.case.chief_complaints()[0].value.text, chief["quote"])
        self.assertTrue(s.interaction.needs_clarification)

    def test_empathy_success_cannot_replace_first_gateway_interpretation(self):
        s, q = self.clinical_reply("네", attribute=None)
        s.session.doctor_successes = s.session.gateway_successes = 0
        self.respond([{"text": "걱정되셨겠어요."}, {"facts": [fact("S.hpi", "symptom", OW.Complaint, "네", q=q.model_dump())]}])
        self.consultation.doctor.model.complete(s, self.client, role="empathy", messages=[{"role": "user", "content": "{}"}, {"role": "user", "content": "{}"}])
        self.assertEqual(s.session.gateway_successes, 0)
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual([entry["role"] for entry in s.interaction.model_history], ["empathy", "gateway"])
        self.assertEqual(s.session.gateway_successes, 1)

    def test_empathy_is_available_in_all_five_sessions_without_education(self):
        for scope in ("Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education"):
            with self.subTest(scope=scope):
                self.setUp()
                s = state(scope, True)
                s.session.gateway_successes = s.session.doctor_successes = 1
                record(s)
                self.greeting(s)
                q = question(s, target=None, text="말씀해 주세요", field="S.ros")
                pending(s, q)
                text = "너무 무서워요. 제 마음을 알아주세요."
                s.interaction.incoming = {"content": text}
                self.respond([{"facts": [], "clinical_content": False, "empathy": {"quote": text, "intent": "new_distress"}},
                              {"text": "무서운 마음이 드셨군요. 곁에서 들을게요."}])
                self.interpreter.process_input(s, self.k, self.client)
                self.assertFalse(s.interaction.needs_clarification)
                self.assertEqual(route_budget(s), "select_question")
                self.consultation.select_action(s)
                action = s.interaction.selected
                self.assertEqual(action.question.purpose, "empathy")
                self.assertIsNone(s.case.get(action.question.item_id))
                self.consultation.doctor.validate_action(s)
                self.consultation.check_budget(s)
                self.consultation.doctor.execute_action(s, self.client)
                self.interpreter.process_input(s, self.k, self.client)
                self.assertEqual(s.interaction.empathy_events[0].status, "delivered")
                self.assertEqual(s.session.turns_remaining, 49)
                self.assertEqual(len(self.client.actions), 1)
                self.assertEqual(s.case.P["education"], {})
                self.assertEqual(self.client.chat.call_count, 2)
                self.assertIn(action.content, [turn.get("doctor") for turn in s.interaction.dialogue()])

    def test_repetition_acknowledgement_and_explicit_renewed_requests(self):
        s = state("ChiefComplaint", True)
        lifecycle = self.consultation.interactions
        signal = EmpathySignal(quote="걱정돼요", intent="new_distress")
        lifecycle.queue_empathy(s, signal, "first")
        s.interaction.empathy_events[0].status = "delivered"
        for source, quote, intent in (("second", "걱정돼요", "new_distress"), ("third", "여전히 걱정이 나요", "repeat"),
                                      ("fourth", "감사합니다", "acknowledgement")):
            lifecycle.queue_empathy(s, EmpathySignal(quote=quote, intent=intent), source)
        self.assertIsNone(lifecycle.pending_empathy(s))
        lifecycle.queue_empathy(s, EmpathySignal(quote="다시 한번 위로해 주세요", intent="renewed_request"), "renewed")
        lifecycle.queue_empathy(s, signal, "renewed")
        self.assertEqual(lifecycle.pending_empathy(s).source_id, "renewed")
        self.assertEqual(len(s.interaction.empathy_events), 5)

    def test_generated_empathy_preserves_exhausted_interview_caps_in_every_session(self):
        for scope, maximum in (("Initiation", 1), ("ChiefComplaint", 16), ("ContextFactor", 7),
                               ("DifferentialDiagnosis", 12), ("Education", 0)):
            with self.subTest(scope=scope):
                self.setUp()
                s = state(scope, True)
                record(s)
                self.greeting(s)
                s.session.doctor_successes = s.session.gateway_successes = 1
                s.session.usage[scope].actions = maximum
                self.consultation.interactions.queue_empathy(s, EmpathySignal(quote="걱정돼요", intent="new_distress"), "cap-event")
                self.respond([{"text": "걱정되셨겠어요. 곁에서 들을게요."}])
                self.consultation.select_action(s)
                self.assertEqual(s.interaction.selected.question.purpose, "empathy")
                self.consultation.doctor.validate_action(s)
                self.consultation.doctor.execute_action(s, self.client)
                self.interpreter.process_input(s, self.k, self.client)
                self.assertEqual(s.interaction.empathy_events[0].status, "delivered")
                self.assertEqual(s.session.usage[scope].actions, maximum + 1)
                self.assertEqual(s.session.usage[scope].empathy_actions, 1)
                self.assertEqual(self.consultation.budget.interview_actions(s), maximum)
                self.assertEqual(self.consultation.budget.action_capacity(s), 0)
                self.assertEqual(s.session.turns_remaining, 49)

    def test_invalid_empathy_quote_never_discards_valid_clinical_fact(self):
        s = state()
        reported = fact("S.cc", "symptom", OW.Complaint, "가상증상")
        result = self.interpreter._validate_facts({"facts": [reported], "empathy": {"quote": "not in input", "intent": "new_distress"}},
                                                 s, self.k, "가상증상")
        self.assertEqual(len(result.accepted_facts), 1)
        self.assertIsNone(result.empathy)
        q = question(s, kind="EXAM", target=OW.ExamX, field="O.exam")
        pending(s, q)
        result = self.interpreter._validate_facts({"facts": [], "empathy": {"quote": "무서워요", "intent": "new_distress"}}, s, self.k, "무서워요")
        self.assertIsNone(result.empathy)

    def test_invalid_empathy_generation_uses_one_prepared_fallback(self):
        for generated in ("", "not json", {"text": "I understand"}, {"text": "가" * 31}, {"text": "어떻게 느끼세요?"}, {"extra": "value"}):
            with self.subTest(generated=generated):
                self.setUp()
                s = state("ChiefComplaint", True)
                self.consultation.interactions.queue_empathy(s, EmpathySignal(quote="걱정돼요", intent="new_distress"), "source")
                self.respond([generated])
                self.consultation.select_action(s)
                self.assertEqual(self.client.chat.call_count, 1)
                self.assertEqual(s.interaction.selected.content, CONFIG.texts.empathy_fallback)
                self.assertIn("empathy_prepared_fallback", s.interaction.issues)
                self.consultation.doctor.validate_action(s)
                self.assertTrue(s.interaction.selected.ready)

    def test_empathy_is_nfc_normalized_without_truncation(self):
        s = state("ChiefComplaint", True)
        self.consultation.interactions.queue_empathy(s, EmpathySignal(quote="걱정돼요", intent="new_distress"), "source")
        text = "걱정되셨겠어요. 곁에서 들을게요."
        self.respond([{"text": unicodedata.normalize("NFD", text)}])
        self.consultation.select_action(s)
        self.assertEqual(s.interaction.selected.content, text)
        self.assertLessEqual(len(text), 30)

    def test_recovered_emotional_reply_does_not_request_medical_terminology(self):
        text = "걱정되는 마음을 알아주세요"
        s, _ = self.clinical_reply(text)
        self.respond(["{invalid", {"facts": [], "clinical_content": False,
                      "empathy": {"quote": text, "intent": "new_distress"}}, {"text": "걱정되셨겠어요. 곁에서 들을게요."}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.client.chat.call_count, 2)
        self.assertFalse(s.interaction.needs_clarification)
        self.consultation.select_action(s)
        self.assertEqual([entry["role"] for entry in s.interaction.model_history], ["gateway", "gateway", "empathy"])

    def test_acknowledgement_keeps_last_actual_empathy_context(self):
        s, _ = self.clinical_reply("여전히 걱정돼요")
        lifecycle = self.consultation.interactions
        lifecycle.queue_empathy(s, EmpathySignal(quote="너무 걱정돼요", intent="new_distress"), "earlier")
        s.interaction.empathy_events[-1].status = "delivered"
        lifecycle.queue_empathy(s, EmpathySignal(quote="감사합니다", intent="acknowledgement"), "ack")
        self.respond([{"facts": [], "clinical_content": False, "empathy": {"quote": "여전히 걱정돼요", "intent": "repeat"}}])
        self.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(self.payloads[0]["last_empathy"]["quote"], "너무 걱정돼요")
        self.assertIsNone(lifecycle.pending_empathy(s))

    def test_empathy_budget_does_not_consume_reply_or_finalization_reserve(self):
        for constraint in ("calls", "turns", "time", "finalizing", "not_allowed"):
            with self.subTest(constraint=constraint):
                self.setUp()
                s = state("ChiefComplaint", True)
                self.consultation.interactions.queue_empathy(s, EmpathySignal(quote="걱정돼요", intent="new_distress"), "source")
                if constraint == "calls": s.session.call_limit = 1
                if constraint == "turns": s.session.turns_remaining = 0
                if constraint == "finalizing": s.session.finalizing = True
                if constraint == "not_allowed": s.session.allowed_actions = ["EXAM", "DIAGNOSE"]
                self.client.chat = Mock()
                with patch.object(self.consultation.budget, "seconds_left", return_value=200 if constraint == "time" else 1500):
                    self.consultation.select_action(s)
                self.client.chat.assert_not_called()
                self.assertIsNone(s.interaction.selected)
                self.assertEqual(s.interaction.empathy_events[0].status, "skipped")

    def test_initial_empathy_follows_greeting_and_new_reply_reaches_confirmed_submission(self):
        prepared = resources(self.k, CONFIG.model_copy(update={"education_enabled": False}))
        self.consultation = make_consultation(self.client, prepared)
        original_chat, original_say, original_session = self.client.chat, self.client.say, self.client.session
        first = True
        def session():
            result = original_session()
            result["initial"]["opening"] = "가상증상이 있어요. 너무 걱정돼요."
            return result
        def chat(messages, **kwargs):
            nonlocal first
            payload = json.loads(messages[1]["content"])
            if payload.get("question") and payload["question"]["purpose"] == "empathy":
                return self.client.completion(json.dumps({"facts": [fact("S.ros", "symptom", OW.Other, payload["input"])]}, ensure_ascii=False))
            response = original_chat(messages, **kwargs)
            if first:
                first = False
                parsed = json.loads(response["choices"][0]["message"]["content"])
                parsed["empathy"] = {"quote": "너무 걱정돼요", "intent": "new_distress"}
                response["choices"][0]["message"]["content"] = json.dumps(parsed, ensure_ascii=False)
            return response
        def say(content, request_id):
            response = original_say(content, request_id)
            if content == CONFIG.texts.empathy_fallback:
                response["content"] = "별도증상도 있어요"
            return response
        self.client.session, self.client.chat, self.client.say = session, chat, say
        initial = self.consultation.nova_session.initialize_case(self.client)
        result = WorkflowState.model_validate(build_graph(self.consultation, self.k).invoke(initial.model_dump(), {"recursion_limit": 1500}))
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(self.client.actions[0]["content"], CONFIG.texts.chief_question)
        self.assertEqual(self.client.actions[1]["content"], CONFIG.texts.empathy_fallback)
        self.assertEqual(sum(event.status == "delivered" for event in result.interaction.empathy_events), 1)
        self.assertTrue(any(item.value and item.value.text == "별도증상도 있어요" for item in result.case.S["ros"].values()))
        self.assertEqual(result.interaction.submission_payload["note"]["P"]["education"], "")
        self.assertEqual(len(self.client.submissions), 1)
        self.assertEqual(sum(len(fields) for fields in self.client.submissions[0]["note"].values()), 15)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Verification))
    (HERE / "input-empathy-verification.json").write_text(json.dumps({"tests": result.testsRun,
        "failures": [str(test) for test, _ in result.failures], "errors": [str(test) for test, _ in result.errors],
        "successful": result.wasSuccessful(), "network": "none", "real_model_calls": 0}, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
