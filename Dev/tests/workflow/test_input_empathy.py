"""D41 input interpretation and typed empathy boundaries."""
import json
import unittest
from unittest.mock import Mock

from test_workflow import (CONFIG, FakeSDK, OW, fact, knowledge, make_consultation,
                           pending, question, record, resources, state)
from normalization_fixtures import fixture_chat
from workflow.rules.budget import BudgetPolicy
from workflow.state.models import EmpathySignal, InteractionEntry


class Verification(unittest.TestCase):
    def setUp(self):
        self.k, self.client = knowledge(), FakeSDK()
        self.agent = make_consultation(self.client, resources(self.k, CONFIG))

    def test_empathy_signal_is_interpreted_with_clinical_facts(self):
        s = state()
        text = "가상증상이 있고 걱정돼요"
        self.client.chat = Mock(side_effect=fixture_chat(self.client, [fact("S.cc", "symptom", OW.Complaint, text)],
            empathy={"quote": "걱정돼요", "intent": "new_distress", "emotion": "anxiety"}))
        s.interaction.incoming = {"initial": {"opening": text}}
        self.agent.interpreter.process_input(s, self.k, self.client)
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertEqual(s.interaction.empathy_events[0].emotion, "anxiety")
        self.assertEqual(self.client.chat.call_count, 2)

    def test_empathy_generation_receives_codes_and_canonical_facts_without_raw_speech(self):
        s = state("ChiefComplaint", True)
        record(s)
        signal = EmpathySignal(quote="SECRET original speech", intent="new_distress", emotion="fear")
        self.agent.interactions.queue_empathy(s, signal, "source")
        self.client.chat = Mock(return_value=self.client.completion('{"text":"걱정되셨겠어요."}'))
        self.agent.doctor.prepare_empathy(s, self.client, s.interaction.empathy_events[0])
        payload = json.loads(self.client.chat.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload["emotion"], "fear")
        self.assertNotIn("SECRET", json.dumps(payload))
        self.assertNotIn("input", payload)
        self.assertTrue(payload["patient"]["facts"])
        self.assertEqual(s.interaction.selected.question.purpose, "empathy")

    def test_repetition_and_acknowledgement_do_not_queue_new_empathy(self):
        s = state()
        for i, intent in enumerate(("new_distress", "repeat", "acknowledgement", "renewed_request")):
            self.agent.interactions.queue_empathy(s, EmpathySignal(quote="걱정돼요", intent=intent), str(i))
        self.assertEqual([e.status for e in s.interaction.empathy_events], ["pending", "skipped", "skipped", "pending"])

    def test_empathy_reserves_context_and_mapping_calls(self):
        s = state("DifferentialDiagnosis", True)
        record(s)
        s.session.call_limit = 2
        self.assertFalse(self.agent.budget.can_empathize(s))
        s.session.call_limit = 3
        self.assertTrue(self.agent.budget.can_empathize(s))
        s.session.output_token_limit = 3 * 4096 - 1
        self.assertFalse(self.agent.budget.can_empathize(s))

    def test_collection_needs_two_calls_but_education_does_not(self):
        s = state("ChiefComplaint", True)
        s.session.call_limit = 1
        self.assertFalse(self.agent.budget.collection_available(s.session))
        s.session.call_limit = 2
        self.assertTrue(self.agent.budget.collection_available(s.session))
        self.agent.budget.education_enabled = True
        s.session.current = "Education"
        s.session.call_limit = 0
        self.assertTrue(self.agent.budget.collection_available(s.session))

    def test_generated_empathy_nfc_and_invalid_output_use_prepared_fallback(self):
        for response, expected in (('{"text":"걱정되셨겠어요."}', "걱정되셨겠어요."),
                                   ('{"text":"질문인가요?"}', CONFIG.texts.empathy_fallback),
                                   ("invalid", CONFIG.texts.empathy_fallback)):
            with self.subTest(response=response):
                s = state()
                self.agent.interactions.queue_empathy(s, EmpathySignal(quote="걱정돼요", intent="new_distress"), "source")
                self.client.chat = Mock(return_value=self.client.completion(response))
                self.agent.doctor.prepare_empathy(s, self.client, s.interaction.empathy_events[0])
                self.assertEqual(s.interaction.selected.content, expected)

    def test_empathy_is_available_in_each_collection_session_only(self):
        for scope in ("Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education"):
            s = state(scope, True)
            record(s)
            self.assertEqual(self.agent.budget.can_empathize(s), scope != "Education")

    def test_last_empathy_reply_is_interpreted_before_submission(self):
        from workflow.graph import build_graph
        from workflow.state.models import WorkflowState
        s = state("DifferentialDiagnosis", True, turns=1)
        record(s)
        s.case.select_primary()
        s.session.usage["DifferentialDiagnosis"].actions = 10
        self.client.remaining = 1
        q = question(s, purpose="empathy", target=None, text="많이 힘드셨겠어요")
        self.agent.interactions.select_question(s, q)
        original = self.client._reply
        self.client._reply = lambda *args, **kwargs: {**original(*args, **kwargs), "content": "별도증상도 있어요"}
        self.client.chat = Mock(side_effect=fixture_chat(self.client, [
            fact("S.ros", "symptom", OW.Other, "별도증상도 있어요")]))
        self.agent.doctor.validate_action(s)
        self.agent.doctor.execute_action(s, self.client)
        result = WorkflowState.model_validate(build_graph(self.agent, self.k).invoke(s.model_dump(), {"recursion_limit": 500}))
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertIsNone(result.interaction.pending)
        self.assertIn("별도증상", self.client.submissions[0]["note"]["S"]["ros"])
        self.assertTrue(all(not i.value.text for i in result.case.S["ros"].values() if i.value))

    def test_invalid_empathy_quote_does_not_erase_valid_facts(self):
        s = state()
        parsed = self.agent.interpreter._validate_facts({"facts": [fact("S.cc", "symptom", OW.Complaint, "가상증상")],
            "empathy": {"quote": "not reported", "intent": "new_distress"}}, s, self.k, "가상증상")
        self.assertEqual(len(parsed.accepted_facts), 1)
        self.assertIsNone(parsed.empathy)
