import copy
from datetime import timedelta
import unittest
from unittest.mock import Mock

import fixtures as f
from workflow.state.models import Question


class OfficialBudgetTests(unittest.TestCase):
    def test_input_repairs_cannot_spend_final_judgment_and_enabled_delivery_reserves(self):
        from workflow.rules.limits import LIMITS
        for enabled,protected in ((False,2),(True,4)):
            c=f.consultation(prepared=f.resources(education=enabled));s=f.chief(f.state('DifferentialDiagnosis'))
            s.session.doctor_calls=s.session.call_limit-protected
            c.client.chat=Mock(return_value=f.FakeSDK.completion('{}'))
            result=c.ear.model.complete(s,c.client,role='gateway',messages=[])
            self.assertEqual(result.error,'MODEL_UNAVAILABLE');c.client.chat.assert_not_called()
            for _ in range(2):
                self.assertIsNone(c.brain.complete(s,c.client,role='clinical',messages=[]).error)
            if enabled:
                self.assertIsNone(c.brain.complete(s,c.client,role='education',messages=[]).error)
                self.assertIsNone(c.mouth.model.complete(s,c.client,role='education_doctor',messages=[]).error)
            self.assertEqual(c.budget.calls_left(s.session),0)
            s.session.doctor_calls=0
            reserve=LIMITS.gateway_tokens+LIMITS.gateway_recovery_tokens+(16000 if enabled else 0)
            s.session.output_tokens=s.session.output_token_limit-reserve
            self.assertEqual(c.budget.model_allowance(s.session,'gateway',state=s),0)

    def test_empathy_preserves_response_judgment_repair_and_optional_delivery(self):
        for enabled in (False,True):
            c=f.consultation(prepared=f.resources(education=enabled));s=f.chief(f.state('DifferentialDiagnosis'))
            s.session.doctor_calls=s.session.call_limit-c.budget.collection_calls(s)
            self.assertFalse(c.budget.can_empathize(s))
            s.session.doctor_calls-=1
            self.assertTrue(c.budget.can_empathize(s))

    def ready_action(self, *, kind='SAY', purpose='feature', turns=50, education=False):
        c = f.consultation(prepared=f.resources(education=education))
        s = f.chief(f.state('Education' if education else 'DifferentialDiagnosis', turns=turns, initialized=True))
        if education:
            f.freeze(s)
        c.client.remaining = turns
        q = Question(item_id='budget-action', kind=kind, purpose=purpose,
                     text='증상이 있나요?' if kind == 'SAY' else '복부 청진하겠습니다')
        c.questions.register(s, q)
        c.interactions.select_question(s, q)
        c.mouth.validate_action(s)
        return c, s

    def test_budget_checkpoint_uses_session_remaining_without_charging_reads(self):
        c, s = f.consultation(), f.state()
        c.client.remaining = 37
        c.client.session = Mock(wraps=c.client.session)
        for _ in range(3):
            c.check_budget(s)
        self.assertEqual(c.client.session.call_count, 3)
        self.assertEqual(s.session.turns_remaining, 37)
        self.assertEqual(sum(u.actions for u in s.session.usage.values()), 0)
        self.assertEqual(s.session.doctor_calls, 0)
        self.assertFalse(c.client.actions)

    def test_model_calls_and_internal_session_changes_leave_action_turns_unchanged(self):
        c, s = f.consultation(), f.chief(f.state())
        f.freeze(s)
        c.client.chat = Mock(return_value=f.FakeSDK.completion('{}'))
        for _ in range(3):
            result = c.ear.model.complete(s, c.client, role='gateway', messages=[])
            self.assertIsNone(result.error)
        for _ in range(4):
            c.advance_session(s)
            c.check_budget(s)
        self.assertEqual(s.interview.current, 'Education')
        self.assertEqual((s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens), (3, 60, 30))
        self.assertEqual((s.session.turns_remaining, c.client.remaining), (50, 50))
        self.assertEqual(sum(u.actions for u in s.session.usage.values()), 0)

    def test_server_model_limits_remain_separate_from_turns(self):
        c, s = f.consultation(), f.chief(f.state())
        snapshot = c.client.session()
        snapshot.update(turns_remaining=41, doctor_calls_remaining=0,
                        input_tokens_remaining=100, output_tokens_remaining=100)
        c.client.session = Mock(return_value=snapshot)
        c.check_budget(s)
        self.assertEqual(s.session.turns_remaining, 41)
        self.assertEqual(c.budget.calls_left(s.session), 0)
        self.assertTrue(s.session.finalizing)
        self.assertFalse(c.client.actions)

    def test_exhausted_official_snapshot_stops_new_actions(self):
        c, s = self.ready_action()
        c.client.remaining = 0
        c.check_budget(s)
        self.assertEqual(s.session.turns_remaining, 0)
        self.assertTrue(s.session.finalizing)
        self.assertIsNone(s.turn)
        self.assertFalse(c.client.actions)

    def test_invalid_or_unavailable_snapshot_stops_without_guessing_turns(self):
        for response in ({'turns_remaining': 49}, f.NovaError('API_UNAVAILABLE')):
            with self.subTest(response=response):
                c, s = self.ready_action()
                c.client.session = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
                c.check_budget(s)
                self.assertEqual(s.session.termination, 'unknown')
                self.assertEqual(s.session.turns_remaining, 50)
                self.assertFalse(c.client.actions)

    def test_refreshed_closed_and_expired_sessions_stop_before_actions(self):
        for status, expected in (('closed', 'closed'), ('expired', 'expired')):
            with self.subTest(status=status):
                c, s = self.ready_action()
                c.client.status = status
                c.check_budget(s)
                self.assertEqual(s.session.termination, expected)
                self.assertFalse(c.client.actions)

    def test_time_reserve_finalizes_without_spending_it_on_collection_refresh(self):
        c, s = self.ready_action()
        s.session.deadline = f.FIXED + timedelta(seconds=200)
        c.client.session = Mock(wraps=c.client.session)
        c.check_budget(s)
        c.client.session.assert_not_called()
        self.assertTrue(s.session.finalizing)
        self.assertEqual(s.session.turns_remaining, 50)
        self.assertFalse(c.client.actions)

    def test_successful_say_and_exam_charge_one_server_turn(self):
        for kind in ('SAY', 'EXAM'):
            with self.subTest(kind=kind):
                c, s = self.ready_action(kind=kind)
                c.mouth.execute_action(s, c.client)
                for _ in range(2):
                    c.nova_session.refresh_snapshot(s, c.client)
                self.assertEqual(s.session.turns_remaining, 49)
                self.assertEqual(s.session.usage['DifferentialDiagnosis'].actions, 1)
                self.assertEqual(s.turn.stage, 'received')

    def test_refusal_cost_comes_from_session_including_free_unavailable_actions(self):
        for code, cost, kind in (('EXAM_NOT_SPECIFIC', 1, 'EXAM'), ('EXAM_NOT_RECOGNIZED', 1, 'EXAM'),
                                 ('EMPTY_CONTENT', 1, 'SAY'), ('CONTENT_TOO_LONG', 1, 'SAY'),
                                 ('ACTION_NOT_AVAILABLE', 0, 'EXAM')):
            with self.subTest(code=code):
                c, s = self.ready_action(kind=kind)
                def refuse(**request):
                    c.client.remaining -= cost
                    raise f.NovaError(code)
                setattr(c.client, 'say' if kind == 'SAY' else 'exam', Mock(side_effect=refuse))
                c.mouth.execute_action(s, c.client)
                self.assertEqual(s.session.turns_remaining, 50 - cost)
                self.assertEqual(s.session.usage['DifferentialDiagnosis'].actions, cost)
                self.assertEqual(s.turn.response, {'error': code})
                self.assertEqual(s.turn.stage, 'received')
                self.assertIsNone(s.session.termination)

    def test_server_response_errors_are_free_and_not_reissued(self):
        for code in ('PATIENT_RESPONSE_INVALID', 'EXAMINER_RESPONSE_INVALID', 'PROVIDER_RESPONSE_INVALID'):
            with self.subTest(code=code):
                c, s = self.ready_action()
                c.client.say = Mock(side_effect=f.NovaError(code))
                c.mouth.execute_action(s, c.client)
                c.client.say.assert_called_once()
                self.assertEqual(s.session.turns_remaining, 50)
                self.assertEqual(s.session.usage['DifferentialDiagnosis'].actions, 0)
                self.assertEqual(s.turn.response, {'error': code})

    def test_empathy_charges_a_turn_separately_from_interview_capacity(self):
        c, s = self.ready_action(purpose='empathy')
        c.mouth.execute_action(s, c.client)
        self.assertEqual(s.session.turns_remaining, 49)
        self.assertEqual((s.session.usage['DifferentialDiagnosis'].actions,
                          s.session.usage['DifferentialDiagnosis'].empathy_actions), (1, 1))
        self.assertEqual(c.budget.interview_actions(s), 0)

    def test_lost_response_replays_same_request_and_charges_once(self):
        c, s = self.ready_action()
        original, attempts, saved = c.client.say, [], []
        def say(**request):
            attempts.append(copy.deepcopy(request))
            if len(attempts) == 1:
                saved.append(original(**request))
                raise f.NovaError('INVALID_API_RESPONSE')
            return saved[0]
        c.client.say = say
        c.mouth.execute_action(s, c.client)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(len(c.client.actions), 1)
        self.assertEqual(s.session.turns_remaining, 49)
        self.assertEqual(s.session.usage['DifferentialDiagnosis'].actions, 1)

    def test_unresolved_transport_accounts_server_effect_then_stops_unknown(self):
        c, s = self.ready_action()
        original, attempts = c.client.say, []
        def unavailable(**request):
            attempts.append(copy.deepcopy(request))
            if len(attempts) == 1:
                original(**request)
            raise f.NovaError('API_UNAVAILABLE')
        c.client.say = unavailable
        c.mouth.execute_action(s, c.client)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(s.session.termination, 'unknown')
        self.assertEqual(s.session.turns_remaining, 49)
        self.assertEqual(s.session.usage['DifferentialDiagnosis'].actions, 1)

    def test_malformed_action_reconciles_real_cost_without_duplicate_accounting(self):
        for field, cost in (('content', 1), ('turns_remaining', 1), ('content', 0)):
            with self.subTest(field=field, cost=cost):
                c, s = self.ready_action()
                original = c.client.say
                def malformed(**request):
                    result = original(**request)
                    result.pop(field)
                    if not cost:
                        c.client.remaining += 1
                    return result
                c.client.say = Mock(side_effect=malformed)
                c.mouth.execute_action(s, c.client)
                c.client.say.assert_called_once()
                self.assertEqual(s.session.termination, 'unknown')
                self.assertEqual(s.session.turns_remaining, 50 - cost)
                self.assertEqual(s.session.usage['DifferentialDiagnosis'].actions, cost)

    def test_fiftieth_reply_is_processed_and_diagnose_is_free(self):
        c, s = self.ready_action(turns=1, purpose='education', education=True)
        c.client.chat = Mock(return_value=f.FakeSDK.completion('{}'))
        c.ear.model.complete(s, c.client, role='gateway', messages=[])
        c.mouth.execute_action(s, c.client)
        self.assertEqual(s.session.turns_remaining, 0)
        c.ear.process_input(s, c.knowledge, c.client)
        self.assertIsNone(s.turn)
        c.check_budget(s)
        self.assertTrue(s.session.finalizing)
        c.close_collection(s)
        c.writer.build_soap(s)
        c.writer.submit_diagnosis(s)
        c.writer.confirm_submission(s)
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(len(c.client.actions), 1)
        self.assertEqual(len(c.client.submissions), 1)
        self.assertEqual((s.session.turns_remaining, c.client.remaining), (0, 0))
        self.assertEqual(s.session.usage['Education'].actions, 1)


if __name__ == '__main__':
    unittest.main()
