import copy
from datetime import timedelta
import unittest
from unittest.mock import Mock, patch

import fixtures as f
from workflow.state.models import Question


class OfficialBudgetTests(unittest.TestCase):
    def test_input_repairs_cannot_spend_final_judgment_and_enabled_delivery_reserves(self):
        for enabled,protected in ((False,2),(True,5)):
            c=f.consultation(prepared=f.resources(education=enabled));s=f.chief(f.state('DifferentialDiagnosis'))
            s.session.doctor_calls=s.session.call_limit-protected
            c.client.chat=Mock(return_value=f.FakeSDK.completion('{}'))
            result=c.ear.model.complete(s,c.client,role='gateway',messages=[])
            self.assertEqual(result.error,'MODEL_UNAVAILABLE');c.client.chat.assert_not_called()
            for _ in range(2):
                self.assertIsNone(c.brain.complete(s,c.client,role='clinical',messages=[]).error)
            if enabled:
                for index in range(2):
                    self.assertIsNone(c.brain.complete(s,c.client,role='education',messages=[], reserve_calls=1-index).error)
                self.assertIsNone(c.mouth.model.complete(s,c.client,role='education_doctor',messages=[]).error)
            self.assertEqual(c.budget.calls_left(s.session),0)

    def test_actual_output_remaining_clips_each_role_and_blocks_at_zero(self):
        from workflow.io.nova_session import SessionInput
        c = f.consultation(prepared=f.resources(education=True))
        s = f.chief(f.state('DifferentialDiagnosis'))
        s.session.input_tokens, s.session.output_tokens = 490_020, 99_880
        snapshot = c.client.session()
        snapshot.update(input_tokens_remaining=9980, output_tokens_remaining=120)
        c.nova_session.apply_snapshot(s, SessionInput.model_validate(snapshot))
        self.assertTrue(c.budget.can_start_action(s))
        c.client.chat = Mock(return_value=f.FakeSDK.completion('{}'))
        for index, role in enumerate(('gateway', 'clinical', 'education', 'education_doctor')):
            with self.subTest(role=role):
                result = c.brain.complete(s, c.client, role=role,
                    messages=[{'role': 'user', 'content': '{}'}])
                self.assertIsNone(result.error)
                self.assertEqual(c.client.chat.call_args.kwargs['max_tokens'], 120 - 10 * index)
        self.assertEqual((s.session.input_tokens, s.session.output_tokens), (490_100, 99_920))
        snapshot['output_tokens_remaining'] = 0
        c.nova_session.apply_snapshot(s, SessionInput.model_validate(snapshot))
        self.assertFalse(c.budget.can_start_action(s))
        result = c.brain.complete(s, c.client, role='gateway', messages=[])
        self.assertEqual(result.error, 'MODEL_UNAVAILABLE')
        self.assertEqual(c.client.chat.call_count, 4)

    def test_education_completes_below_input_and_output_limits_after_dd_reserve(self):
        c = f.consultation(prepared=f.resources(education=True))
        s = f.chief(f.state())
        f.freeze_for_education(c, s)
        s.session.input_tokens, s.session.output_tokens = 490_020, 99_000
        c.run(s)
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.interview.education_status, 'complete')
        self.assertEqual({sentence.field for sentence in s.case.plan},
                         {'tests', 'treatment', 'disposition', 'follow_up', 'education'})
        self.assertTrue(c.client.submissions[-1]['note']['P']['education'])
        self.assertTrue(any(answer.plan_sentence_id and answer.outcome == 'delivered'
                            for answer in s.interview.answers))
        self.assertGreater(s.session.input_tokens, 490_020)
        self.assertLessEqual(s.session.input_tokens, 500_000)
        self.assertGreater(s.session.output_tokens, 99_000)
        self.assertLessEqual(s.session.output_tokens, 100_000)

    def test_optional_server_output_remaining_only_tightens_limit_without_consumption(self):
        from workflow.io.nova_session import SessionInput
        c, s = f.consultation(), f.state()
        raw = c.client.session()
        c.nova_session.apply_snapshot(s, SessionInput.model_validate(raw))
        self.assertEqual(s.session.output_token_limit, 100_000)
        s.session.output_tokens = 400
        for remaining in (120, 100_000, None):
            c.nova_session.apply_snapshot(s, SessionInput.model_validate(dict(raw, output_tokens_remaining=remaining)))
            self.assertEqual(s.session.output_token_limit, 520)
            self.assertEqual(s.session.output_tokens, 400)

    def test_output_boundary_and_overshoot_use_actual_usage_once(self):
        for before in (99_990, 99_991):
            with self.subTest(before=before):
                c, s = f.consultation(), f.state()
                s.session.output_tokens = before
                c.client.chat = Mock(return_value=f.FakeSDK.completion('{}'))
                result = c.brain.complete(s, c.client, role='gateway', messages=[])
                self.assertEqual(s.session.output_tokens, before + 10)
                self.assertEqual(c.client.chat.call_args.kwargs['max_tokens'], 100_000 - before)
                self.assertEqual(result.error, None if before == 99_990 else 'MODEL_TOKEN_BUDGET')
                self.assertEqual(c.budget.calls_left(s.session), 0)
                self.assertEqual(c.brain.complete(s, c.client, role='gateway', messages=[]).error, 'MODEL_UNAVAILABLE')
                c.client.chat.assert_called_once()

    def test_no_output_left_finalizes_existing_assessment_and_writer_without_model(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.close_collection(s)
        s.session.output_tokens = 100_000
        c.client.chat = Mock(side_effect=AssertionError('Output exhausted'))
        for role in ('gateway', 'clinical', 'education', 'education_doctor'):
            self.assertEqual(c.brain.complete(s, c.client, role=role, messages=[]).error, 'MODEL_UNAVAILABLE')
        c.run(s)
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.session.receipt['status'], 'completed')
        self.assertTrue(c.client.submissions[-1]['note']['A']['evidence'])
        self.assertEqual(s.session.output_tokens, 100_000)
        c.client.chat.assert_not_called()

    def test_provider_response_invalid_does_not_invent_usage(self):
        c, s = f.consultation(), f.state()
        c.client.chat = Mock(side_effect=f.NovaError('PROVIDER_RESPONSE_INVALID', 503))
        result = c.brain.complete(s, c.client, role='clinical', messages=[])
        self.assertEqual(result.error, 'PROVIDER_RESPONSE_INVALID')
        self.assertEqual((s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens), (1, 0, 0))

    def test_completion_usage_includes_reasoning_without_double_counting_details(self):
        c, s = f.consultation(), f.state()
        response = f.FakeSDK.completion('{}')
        response['usage'].update(completion_tokens=120, completion_tokens_details={'reasoning_tokens': 100})
        s.session.output_tokens = 99_880
        c.client.chat = Mock(return_value=response)
        self.assertIsNone(c.brain.complete(s, c.client, role='clinical', messages=[]).error)
        self.assertEqual(s.session.output_tokens, 100_000)
        self.assertEqual(c.budget.calls_left(s.session), 0)

    def test_total_input_boundary_and_overshoot_account_once_then_block_models(self):
        for before in (499_980, 499_981):
            with self.subTest(before=before):
                c, s = f.consultation(), f.state()
                s.session.input_tokens = before
                c.client.chat = Mock(return_value=f.FakeSDK.completion('{}'))
                result = c.brain.complete(s, c.client, role='gateway', messages=[])
                self.assertEqual(s.session.input_tokens, before + 20)
                self.assertEqual(result.error, None if before == 499_980 else 'MODEL_TOKEN_BUDGET')
                self.assertEqual(s.session.doctor_successes, 1 if before == 499_980 else 0)
                self.assertEqual(c.budget.calls_left(s.session), 0)
                self.assertEqual(c.brain.complete(s, c.client, role='gateway', messages=[]).error, 'MODEL_UNAVAILABLE')
                c.client.chat.assert_called_once()

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
        s = c.nova_session.initialize_case(c.client)
        for _ in range(3):
            c.check_budget(s)
        self.assertEqual(c.client.session.call_count, 1)
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
        s.session.budget_sync_required = True
        c.check_budget(s)
        self.assertEqual(s.session.turns_remaining, 41)
        self.assertEqual(c.budget.calls_left(s.session), 0)
        self.assertTrue(s.session.finalizing)
        self.assertFalse(c.client.actions)

    def test_exhausted_official_snapshot_stops_new_actions(self):
        c, s = self.ready_action()
        c.client.remaining = 0
        s.session.budget_sync_required = True
        c.check_budget(s)
        self.assertEqual(s.session.turns_remaining, 0)
        self.assertTrue(s.session.finalizing)
        self.assertIsNone(s.turn)
        self.assertFalse(c.client.actions)

    def test_invalid_or_unavailable_snapshot_finalizes_without_guessing_turns(self):
        for response in ({'turns_remaining': 49}, f.NovaError('API_UNAVAILABLE')):
            with self.subTest(response=response):
                c, s = self.ready_action()
                c.client.session = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
                s.session.budget_sync_required = True
                c.check_budget(s)
                self.assertIsNone(s.session.termination)
                self.assertEqual(s.session.turns_remaining, 50)
                self.assertFalse(c.client.actions)

    def test_refreshed_closed_and_expired_sessions_stop_before_actions(self):
        for status, expected in (('closed', 'closed'), ('expired', 'expired')):
            with self.subTest(status=status):
                c, s = self.ready_action()
                c.client.status = status
                s.session.budget_sync_required = True
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
                self.assertIsNone(s.turn)
                self.assertEqual(s.interview.answers[-1].response, {'error': code})
                self.assertEqual(s.interview.answers[-1].outcome, 'undelivered')
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
                self.assertIsNone(s.turn)
                self.assertEqual(s.interview.answers[-1].response, {'error': code})

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

    def test_unresolved_transport_accounts_server_effect_then_passes_unknown(self):
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
        self.assertIsNone(s.session.termination)
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
                self.assertIsNone(s.session.termination)
                self.assertEqual(s.session.turns_remaining, 50 - cost)
                self.assertEqual(s.session.usage['DifferentialDiagnosis'].actions, cost)

    def test_fiftieth_reply_is_processed_and_diagnose_is_free(self):
        c, s = self.ready_action(turns=1, purpose='education', education=True)
        c.client.chat = Mock(return_value=f.FakeSDK.completion('{}'))
        c.ear.model.complete(s, c.client, role='gateway', messages=[])
        # Isolate acceptance of an already-budgeted last reply; normal selection
        # now protects the closing pair (covered by test_fixed_utterances).
        with patch.object(c.budget, 'closing_turns', return_value=0):
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
