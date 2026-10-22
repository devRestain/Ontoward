"""Fixed social SAY ordering, reply disposal and shared turn accounting."""
import json
from datetime import timedelta
from pathlib import Path
import tempfile
import unicodedata
import unittest
from unittest.mock import Mock, patch
import uuid

import fixtures as f
from workflow.rules.limits import FIXED_UTTERANCES, SESSION_INTERVIEW_LIMITS


class FixedUtteranceTests(unittest.TestCase):
    def test_full_consultation_orders_fixed_lines_and_never_retains_their_replies(self):
        client = f.FakeSDK()
        c = f.consultation(client, f.resources(education=True))
        state = c.nova_session.initialize_case(client)
        private = 'PRIVATE_SOCIAL_REPLY_새로운_증상_열이_납니다'
        fixed = {text for lines in FIXED_UTTERANCES.values() for text in lines}
        original = client.say
        def say(**request):
            if request['content'] == FIXED_UTTERANCES['opening'][0]:
                self.assertTrue(state.case.chief())
                self.assertFalse(client.actions)
            response = original(**request)
            if request['content'] in fixed:
                response['content'] = private
            return response
        client.say = say
        submitted = client.diagnose
        def diagnose(**request):
            self.assertEqual([row['content'] for row in client.actions[-2:]], list(FIXED_UTTERANCES['closing']))
            return submitted(**request)
        client.diagnose = diagnose
        c.run(state)
        contents = [row['content'] for row in client.actions]
        self.assertEqual(contents[:2], list(FIXED_UTTERANCES['opening']))
        self.assertEqual(contents[2], c.config.texts.intake_questions['onset'])
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual(state.session.termination, 'submitted')
        self.assertEqual(state.session.fixed_actions, 4)
        self.assertEqual(sum(u.actions for u in state.session.usage.values()) + 4, len(client.actions))
        self.assertEqual(state.session.turns_remaining, 50 - len(client.actions))
        for saved in (state.model_dump_json(), json.dumps(c.ear.dialogue), json.dumps(client.requests), json.dumps(client.submissions)):
            self.assertNotIn(private, saved)
        before = len(client.actions)
        c.deliver_fixed(state, 'opening')
        c.deliver_fixed(state, 'closing')
        self.assertEqual(len(client.actions), before)

    def test_approved_text_lengths_and_existing_session_limits(self):
        texts = [text for lines in FIXED_UTTERANCES.values() for text in lines]
        self.assertEqual([len(text) for text in texts], [28, 27, 28, 28])
        self.assertTrue(all(unicodedata.normalize('NFC', text) == text for text in texts))
        self.assertEqual(SESSION_INTERVIEW_LIMITS, {'Initiation': (5, 7), 'ChiefComplaint': (5, 10),
            'ContextFactor': (7, 9), 'DifferentialDiagnosis': (15, 20), 'Education': (5, 10)})

    def test_last_two_turns_deliver_closing_then_submit_without_a_model(self):
        c = f.consultation(prepared=f.resources(education=True))
        state = f.chief(f.state('Education', turns=2))
        f.freeze(state)
        state.interview.education_status = 'complete'
        state.session.models_available = False
        state.session.deadline = c.client.deadline = f.FIXED + timedelta(seconds=200)
        c.client.remaining = 2
        c.client.chat = Mock(side_effect=AssertionError('Fixed lines need no model'))
        self.assertEqual(c.budget.action_capacity(state), 0)
        self.assertFalse(c.budget.can_start_action(state))
        c.run(state)
        self.assertEqual([row['content'] for row in c.client.actions], list(FIXED_UTTERANCES['closing']))
        self.assertEqual(state.session.turns_remaining, 0)
        self.assertEqual(state.session.termination, 'submitted')
        c.client.chat.assert_not_called()

    def test_fixed_failure_reuses_only_the_same_request_and_counts_confirmed_cost(self):
        c, state = f.consultation(), f.state()
        calls = []
        def failed(**request):
            calls.append(request)
            if len(calls) == 1:
                c.client.remaining -= 1
            raise f.NovaError('REQUEST_PENDING')
        c.client.say = failed
        c.mouth.execute_fixed(state, c.client, 'opening:0', FIXED_UTTERANCES['opening'][0])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(state.session.fixed_actions, 1)
        self.assertEqual(state.session.turns_remaining, 49)
        self.assertEqual(state.session.fixed_utterances['opening:0'].outcome, 'REQUEST_PENDING')
        c.mouth.execute_fixed(state, c.client, 'opening:0', FIXED_UTTERANCES['opening'][0])
        self.assertEqual(len(calls), 2)
        self.assertFalse(state.interview.answers)
        self.assertFalse(c.ear.dialogue)

    def test_forbidden_closed_or_exhausted_sessions_do_not_send_fixed_lines(self):
        for mode in ('forbidden', 'closed', 'empty', 'sync'):
            c, state = f.consultation(), f.state()
            if mode == 'forbidden':
                state.session.allowed_actions = ['DIAGNOSE']
            elif mode == 'closed':
                state.stop('closed', 'session_closed')
            elif mode == 'sync':
                state.session.budget_sync_required = True
            else:
                state.session.turns_remaining = 0
            c.deliver_fixed(state, 'closing')
            self.assertFalse(c.client.actions)
            self.assertFalse(state.session.fixed_utterances)

    def test_later_budget_sync_accounts_unknown_fixed_cost_once(self):
        c, state = f.consultation(), f.state()
        def unknown(**request):
            c.client.remaining = 49
            raise f.NovaError('REQUEST_PENDING')
        c.client.say = unknown
        with patch.object(c.nova_session, 'refresh_snapshot', side_effect=f.NovaError('API_UNAVAILABLE')):
            c.deliver_fixed(state, 'opening')
        self.assertEqual(state.session.fixed_pending_turns, 50)
        self.assertTrue(state.session.budget_sync_required)
        self.assertEqual(len(state.session.fixed_utterances), 1)
        c.nova_session.refresh_snapshot(state, c.client)
        self.assertEqual(state.session.fixed_actions, 1)
        self.assertIsNone(state.session.fixed_pending_turns)
        self.assertFalse(state.session.budget_sync_required)
        c.nova_session.refresh_snapshot(state, c.client)
        self.assertEqual(state.session.fixed_actions, 1)


class FixedReplyPersistenceTests(unittest.TestCase):
    def test_local_simulator_keeps_receipts_and_replays_without_persisting_social_replies(self):
        from models import completion
        from privacy import FIXED_UTTERANCES as recorded
        from server import Evaluation
        expected = {text for lines in FIXED_UTTERANCES.values() for text in lines}
        self.assertEqual(recorded, expected)
        private = 'PRIVATE_FIXED_PATIENT_REPLY'
        calls = []
        class Models:
            calls = 0
            def complete(self, role, messages, *args, **kwargs):
                self.calls += 1
                data = json.loads(messages[-1]['content'])
                calls.append(data)
                return completion(json.dumps({'content': private if data['utterance'] in expected else '알겠습니다',
                    'effective_content': data['utterance']}))
        case = dict(case_id='offline', start_information={'opening': 'Complaint'}, patient_script='', exam_results=[])
        with tempfile.TemporaryDirectory() as folder:
            evaluation = Evaluation(case, Models(), folder, now=lambda: 1000)
            evaluation.dispatch('POST', '/_nova/ready', {})
            body = dict(action='SAY', content=FIXED_UTTERANCES['opening'][0], request_id=str(uuid.uuid4()))
            first = evaluation.dispatch('POST', '/v1/session/actions', body)
            self.assertEqual(first[1]['content'], private)
            self.assertEqual(evaluation.dispatch('POST', '/v1/session/actions', body), first)
            self.assertEqual(evaluation.turns, 1)
            ordinary = dict(action='SAY', content='추가 증상이 있나요?', request_id=str(uuid.uuid4()))
            evaluation.dispatch('POST', '/v1/session/actions', ordinary)
            self.assertEqual(calls[-1]['history'], [])
            for path in Path(folder).glob('*'):
                self.assertNotIn(private, path.read_text())
            transcript = json.loads((Path(folder) / 'transcript.json').read_text())
            self.assertEqual(transcript['events'][-1]['response']['content'], '알겠습니다')

    def test_sdk_trace_discards_fixed_reply_without_modifying_returned_response(self):
        from nova_sdk import Client
        from observe import observing
        private = 'PRIVATE_FIXED_SDK_REPLY'
        raw = dict(status='OK', content=private, turn=1, turns_remaining=49)
        client = Client(api_base='http://offline.invalid', token='fixture', session_id='offline')
        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder) / 'trace.jsonl'
            with patch.object(Client, '_request', return_value=raw), observing(trace):
                returned = client.say(FIXED_UTTERANCES['opening'][0], request_id=str(uuid.uuid4()))
            self.assertIs(returned, raw)
            saved = trace.read_text()
            self.assertNotIn(private, saved)
            self.assertIn('reply_discarded', saved)

    def test_provider_logs_keep_actual_usage_but_discard_fixed_patient_text(self):
        from models import NovaModels, completion
        from openai_models import OpenAIModels
        from test_openai import FakeOpener, response
        private = 'PRIVATE_FIXED_PROVIDER_REPLY'
        messages = [{'role': 'user', 'content': json.dumps({'utterance': FIXED_UTTERANCES['opening'][0]})}]
        for provider in ('nova', 'openai'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as folder:
                if provider == 'nova':
                    model = NovaModels('https://nova.snubhai.org', 'offline', folder, 2)
                    model.client.chat = Mock(return_value=completion(private))
                else:
                    model = OpenAIModels('offline', folder, 2)
                    model.opener = FakeOpener(response(private))
                returned = model.complete('patient', messages, 100, str(uuid.uuid4()))
                self.assertEqual(returned['choices'][0]['message']['content'], private)
                saved = next(Path(folder).glob('*requests.jsonl')).read_text()
                self.assertNotIn(private, saved)
                self.assertIn('reply_discarded', saved)
                self.assertIn('usage', saved)


if __name__ == '__main__':
    unittest.main()
