from collections import deque
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from nova_sdk import Client, empty_record, NovaError
from models import completion, MODEL, NovaModels, ScriptedModels
from report import report
from server import Evaluation, http_server, load_case
from test_web import WebTests


class Replies:
    def __init__(self, *values):
        self.values, self.calls, self.roles = deque(values), 0, []

    def complete(self, role, messages, max_tokens, request_id, *, reasoning_effort='medium'):
        self.calls += 1
        self.roles.append((role, messages))
        value = self.values.popleft()
        if isinstance(value, Exception):
            raise value
        return completion(json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value)


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [1000.0]
        self.case, self.digest = load_case('C10')
        self.models = Replies()
        self.evaluation = Evaluation(self.case, self.models, self.temp.name, case_hash=self.digest, now=lambda: self.clock[0])
        self.evaluation.dispatch('POST', '/_nova/ready', {})

    def request(self, path='/v1/session/actions', request_id=None, **body):
        return self.evaluation.dispatch('POST', path, {'request_id': request_id or str(uuid.uuid4()), **body})

    def chat(self):
        return self.request('/v1/chat/completions', session_id=self.evaluation.session_id,
                            messages=[{'role': 'user', 'content': 'Interpret acquired evidence'}], model=MODEL, max_tokens=2048)

    def record(self):
        note = empty_record()
        note['S']['cc'] = '체중 감소'
        return note

    def test_readiness_deadline_and_initial_only(self):
        self.evaluation.ready = False
        self.assertEqual(self.evaluation.dispatch('GET', '/v1/session')[0], 409)
        self.evaluation.dispatch('POST', '/_nova/ready', {})
        deadline = self.evaluation.deadline
        self.clock[0] += 20
        self.evaluation.dispatch('POST', '/_nova/ready', {})
        self.assertEqual(self.evaluation.deadline, deadline)
        status, session = self.evaluation.dispatch('GET', '/v1/session')
        self.assertEqual(status, 200)
        self.assertEqual(session['initial'], self.case['start_information'])
        text = json.dumps(session, ensure_ascii=False)
        for private in ('patient_script', 'exam_results', 'model_record', 'events'):
            self.assertNotIn(private, text)

    def test_prepare_timeout_and_consult_expiry(self):
        self.evaluation.ready = False
        self.clock[0] += 601
        self.assertEqual(self.evaluation.dispatch('POST', '/_nova/ready', {})[1]['error']['code'], 'PREPARE_TIMEOUT')
        self.evaluation.ready, self.evaluation.status = True, 'active'
        self.clock[0] = self.evaluation.deadline + 1
        self.assertEqual(self.request(action='SAY', content='안녕하세요')[1]['error']['code'], 'SESSION_EXPIRED')

    def test_sdk_http_handshake_and_validation(self):
        server = http_server(self.evaluation, 'test-token', ('127.0.0.1', 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            client = Client(api_base=base, token='test-token', session_id=self.evaluation.session_id)
            self.assertTrue(client.ready()['ready'])
            self.assertEqual(client.session()['turns_remaining'], 50)
            with self.assertRaises(ValueError):
                client.say('가' * 31)
            self.assertEqual(self.evaluation.turns, 0)
            with self.assertRaises(NovaError) as caught:
                Client(api_base=base, token='wrong').session()
            self.assertEqual(caught.exception.code, 'UNAUTHORIZED')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_idempotent_delivery_and_conflicting_payload(self):
        self.models.values.append({'content': '체중이 줄었어요', 'effective_content': '어디가 불편하세요?'})
        request_id = str(uuid.uuid4())
        first = self.request(request_id=request_id, action='SAY', content='어디가 불편하세요?')
        second = self.request(request_id=request_id, action='SAY', content='어디가 불편하세요?')
        conflict = self.request(request_id=request_id, action='SAY', content='아프세요?')
        self.assertEqual(first, second)
        self.assertEqual((self.evaluation.turns, self.models.calls), (1, 1))
        self.assertEqual(conflict[1]['error']['code'], 'REQUEST_ID_CONFLICT')

    def test_pending_request_has_no_duplicate_effect(self):
        entered, release = threading.Event(), threading.Event()
        def blocking(*args, **kwargs):
            entered.set()
            release.wait(2)
            return completion('{"content":"네","effective_content":"괜찮으세요?"}')
        self.models.complete = blocking
        request_id = str(uuid.uuid4())
        call = lambda: self.request(request_id=request_id, action='SAY', content='괜찮으세요?')
        thread = threading.Thread(target=call)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(call()[1]['error']['code'], 'REQUEST_PENDING')
            self.assertEqual(self.request(action='SAY', content='괜찮으세요?')[1]['error']['code'], 'REQUEST_PENDING')
        finally:
            release.set()
            thread.join(2)
        self.assertEqual(self.evaluation.turns, 1)

    def test_raw_invalid_say_uses_turn_but_test_does_not(self):
        for text, error in [('', 'EMPTY_CONTENT'), ('가' * 31, 'CONTENT_TOO_LONG')]:
            self.assertEqual(self.request(action='SAY', content=text)[1]['error']['code'], error)
        self.assertEqual(self.evaluation.turns, 2)
        self.assertEqual(self.request(action='TEST', content='혈액검사')[1]['error']['code'], 'ACTION_NOT_AVAILABLE')
        self.assertEqual((self.evaluation.turns, self.models.calls), (2, 0))

    def test_nfc_normalizes_before_counting(self):
        text = '가' * 30
        self.models.values.append({'content': '네', 'effective_content': text})
        self.assertEqual(self.request(action='SAY', content='가' * 30)[0], 200)
        self.assertEqual(self.evaluation.events[-1]['content'], text)

    def test_invalid_patient_format_retries_twice_without_turn(self):
        self.models.values.extend([{'content': '네', 'effective_content': 'not a quotation'}, 'invalid JSON'])
        result = self.request(action='SAY', content='괜찮으세요?')
        self.assertEqual(result[1]['error']['code'], 'PATIENT_RESPONSE_INVALID')
        self.assertEqual((self.evaluation.turns, self.models.calls), (0, 2))

    def test_patient_has_no_exam_table_or_reference(self):
        self.models.values.append({'content': '네', 'effective_content': '괜찮으세요?'})
        self.request(action='SAY', content='괜찮으세요?')
        prompt = self.models.roles[0][1][0]['content']
        self.assertIn(self.case['patient_script'], json.loads(prompt.split('\n\n')[-1])['script'])
        self.assertNotIn('exam_results', prompt)
        self.assertNotIn('model_record', prompt)

    def test_exam_exact_row_and_refused_turns(self):
        self.models.values.extend([{'id': 'r01'}, {'id': None, 'reason': 'too_broad'}, {'id': None, 'reason': 'not_exam'}])
        result = self.request(action='EXAM', content='전반적 외관 시진')
        self.assertEqual(result[1]['result'], self.case['exam_results'][0]['result'])
        for error in ('EXAM_NOT_SPECIFIC', 'EXAM_NOT_RECOGNIZED'):
            self.assertEqual(self.request(action='EXAM', content='검사 모두')[1]['error']['code'], error)
        self.assertEqual(self.evaluation.turns, 3)
        prompt = self.models.roles[0][1][0]['content']
        self.assertNotIn(self.case['patient_script'], prompt)
        self.assertNotIn(self.case['exam_results'][0]['result'], prompt)

    def test_invalid_exam_does_not_guess_nearest_row(self):
        self.models.values.extend([{'id': 'r999'}, {'id': ['r01', 'r02']}])
        self.assertEqual(self.request(action='EXAM', content='진찰 요청')[1]['error']['code'], 'EXAMINER_RESPONSE_INVALID')
        self.assertEqual(self.evaluation.turns, 0)

    def test_unlisted_finding_is_cached(self):
        classification = {'id': None, 'reason': 'unlisted', 'maneuver': '머피 징후 (Murphy sign)'}
        self.models.values.extend([classification, {'result': '머피 징후(-)'}, classification])
        first = self.request(action='EXAM', content='머피 징후 확인')
        second = self.request(action='EXAM', content='머피 징후 확인')
        self.assertEqual(first[1]['result'], second[1]['result'])
        self.assertEqual((self.evaluation.turns, self.models.calls), (2, 3))

    def test_empty_doctor_counts_call_without_tokens(self):
        self.models.values.append('')
        self.assertEqual(self.chat()[1]['error']['code'], 'PROVIDER_RESPONSE_INVALID')
        self.assertEqual((self.evaluation.doctor_calls, self.evaluation.input_tokens, self.evaluation.output_tokens), (1, 0, 0))

    def test_model_budgets_and_designated_model(self):
        self.evaluation.doctor_calls = 200
        self.assertEqual(self.chat()[1]['error']['code'], 'MODEL_CALL_LIMIT')
        self.evaluation.doctor_calls = 0
        self.assertEqual(self.request('/v1/chat/completions', session_id=self.evaluation.session_id,
                                      model='other')[1]['error']['code'], 'MODEL_NOT_ALLOWED')
        self.assertEqual(self.models.calls, 0)

    def test_education_reasoning_reaches_the_nova_sdk_and_shares_case_usage(self):
        models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 2)
        self.evaluation.models = models
        with patch.object(models.client, '_request', return_value=completion('{"P":{}}')) as remote:
            status, _ = self.request('/v1/chat/completions', session_id=self.evaluation.session_id,
                model=MODEL, reasoning_effort='high', max_tokens=8000,
                messages=[{'role': 'user', 'content': json.dumps({'task': 'education', 'phase': 'direct'})}])
            self.assertEqual(status, 200)
            body = remote.call_args.args[2]
            self.assertEqual(body['reasoning_effort'], 'high')
            self.assertEqual(body['max_tokens'], 8000)
            self.assertNotIn('session_id', body)
        self.assertEqual(self.evaluation.doctor_calls, 1)
        self.assertEqual(self.evaluation.turns, 0)
        row = json.loads((Path(self.temp.name) / 'model-calls.jsonl').read_text().splitlines()[0])
        self.assertEqual(row['role'], 'education')

    def test_missing_process_evidence_is_failure(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(report(self.temp.name), 1)
        result = json.loads((Path(self.temp.name) / 'result.json').read_text())
        self.assertIn('agent/process.json', result['missing_evidence'])
        self.assertFalse(result['checks']['agent_exit_zero'])
        self.assertFalse(result['checks']['no_development_key_in_agent'])

    def test_output_remaining_clips_call_and_blocks_next_call_without_blocking_diagnose(self):
        output_caps = []
        def complete(role, messages, max_tokens, request_id, **options):
            self.models.calls += 1
            output_caps.append(max_tokens)
            return completion('ok', prompt_tokens=20, completion_tokens=7000)
        self.models.complete = complete
        self.evaluation.input_tokens = 490000
        self.evaluation.output_tokens = 93000
        for expected in (200, 429):
            self.assertEqual(self.request('/v1/chat/completions', session_id=self.evaluation.session_id,
                messages=[{'role': 'user', 'content': 'Interpret acquired evidence'}],
                model=MODEL, max_tokens=8000)[0], expected)
        self.assertEqual(output_caps, [7000])
        self.assertEqual((self.evaluation.doctor_successes, self.evaluation.input_tokens,
                          self.evaluation.output_tokens), (1, 490020, 100000))
        snapshot = self.evaluation.snapshot()
        self.assertEqual(snapshot['input_tokens_remaining'], 9980)
        self.assertEqual(snapshot['output_tokens_remaining'], 0)
        self.assertEqual(self.request(action='DIAGNOSE', note=self.record(), diagnosis='Test diagnosis')[0], 200)
        summary = json.loads((Path(self.temp.name) / 'summary.json').read_text())
        self.assertEqual(summary['limits']['input_tokens'], 500000)
        self.assertEqual(summary['limits']['input_tokens_per_call'], 100000)
        self.assertEqual(summary['limits']['output_tokens'], 100000)
        simulator = Path(self.temp.name) / 'simulator'
        simulator.mkdir()
        for name in ('summary.json', 'transcript.json', 'requests.json', 'record.json'):
            (simulator / name).write_bytes((Path(self.temp.name) / name).read_bytes())
        agent = Path(self.temp.name) / 'agent'
        agent.mkdir()
        (agent / 'process.json').write_text(json.dumps(dict(exit_code=0, development_key_present=False,
            samples_visible=False, sandbox=dict(root_read_only=True, submission_read_only=True, output_writable=True))))
        with redirect_stdout(io.StringIO()):
            status = report(self.temp.name)
        result = json.loads((Path(self.temp.name) / 'result.json').read_text())
        self.assertEqual(status, 0, result)
        self.assertTrue(result['checks']['within_model_limits'])
        summary['output_tokens'] = 100001
        (simulator / 'summary.json').write_text(json.dumps(summary))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(report(self.temp.name), 1)
        self.assertFalse(json.loads((Path(self.temp.name) / 'result.json').read_text())['checks']['within_model_limits'])
        summary['output_tokens'] = 100000
        summary['input_tokens'] = 500001
        (simulator / 'summary.json').write_text(json.dumps(summary))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(report(self.temp.name), 1)
        self.assertFalse(json.loads((Path(self.temp.name) / 'result.json').read_text())['checks']['within_model_limits'])

    def test_default_output_and_oversized_output_error_match_supplied_contract(self):
        with patch.object(self.models, 'complete', return_value=completion('ok')) as remote:
            self.assertEqual(self.request('/v1/chat/completions', session_id=self.evaluation.session_id,
                messages=[{'role': 'user', 'content': 'Interpret evidence'}], model=MODEL)[0], 200)
            self.assertEqual(remote.call_args.args[2], 8000)
            response = self.request('/v1/chat/completions', session_id=self.evaluation.session_id,
                messages=[{'role': 'user', 'content': 'Interpret evidence'}], model=MODEL, max_tokens=8001)
            self.assertEqual(response, (400, {'error': {'code': 'TOKEN_LIMIT_EXCEEDED'}}))
            remote.assert_called_once()

    def test_reported_request_input_limit_accounts_usage_and_rejects_oversize(self):
        for count in (100000, 100001):
            with patch.object(self.models, 'complete', return_value=completion('ok', prompt_tokens=count)):
                response = self.chat()
            self.assertEqual(response[0], 200 if count == 100000 else 400)
        self.assertEqual(response[1]['error']['code'], 'CONTEXT_LIMIT_EXCEEDED')
        self.assertEqual((self.evaluation.doctor_calls, self.evaluation.doctor_successes,
                          self.evaluation.input_tokens), (2, 1, 200001))

    def test_total_input_boundary_and_overshoot_stop_further_requests(self):
        with patch.object(self.models, 'complete', return_value=completion('ok', prompt_tokens=20)) as remote:
            self.evaluation.input_tokens = 499980
            self.assertEqual(self.chat()[0], 200)
            self.assertEqual(self.chat()[1]['error']['code'], 'MODEL_TOKEN_BUDGET')
            remote.assert_called_once()
            self.evaluation.input_tokens = 499990
            self.assertEqual(self.chat()[1]['error']['code'], 'MODEL_TOKEN_BUDGET')
            self.assertEqual(self.evaluation.input_tokens, 500010)
            self.assertEqual(self.evaluation.doctor_successes, 1)

    def test_fiftieth_turn_can_submit_and_receipt_can_replay(self):
        self.models.values.append('{"facts":[]}')
        self.assertEqual(self.chat()[0], 200)
        self.evaluation.turns = 50
        self.assertEqual(self.request(action='SAY', content='안녕하세요')[1]['error']['code'], 'TURN_LIMIT_REACHED')
        request_id = str(uuid.uuid4())
        first = self.request(request_id=request_id, action='DIAGNOSE', note=self.record(), diagnosis='체중 감소')
        again = self.request(request_id=request_id, action='DIAGNOSE', note=self.record(), diagnosis='체중 감소')
        self.assertEqual(first, again)
        self.assertEqual(first[1]['status'], 'completed')
        self.assertEqual(first[1]['score_status'], 'not_scored')
        self.assertEqual(self.evaluation.turns, 50)
        saved = json.loads((Path(self.temp.name) / 'record.json').read_text())
        self.assertEqual(saved['note'], self.record())

    def test_record_shape_empty_and_size_fail_without_turn(self):
        note = self.record()
        note['A']['diagnosis'] = 'extra'
        self.assertEqual(self.request(action='DIAGNOSE', note=note, diagnosis='체중 감소')[1]['error']['code'], 'INVALID_RECORD_FIELDS')
        self.assertEqual(self.request(action='DIAGNOSE', note=empty_record(), diagnosis='체중 감소')[1]['error']['code'], 'FINAL_RECORD_REQUIRED')
        note = self.record()
        note['S']['cc'] = '가' * 34000
        self.assertEqual(self.request(action='DIAGNOSE', note=note, diagnosis='체중 감소')[1]['error']['code'], 'RECORD_TOO_LARGE')
        self.assertEqual(self.request(action='DIAGNOSE', note=self.record(), diagnosis='체중 감소')[1]['error']['code'], 'DOCTOR_CALL_REQUIRED')
        self.assertEqual(self.evaluation.turns, 0)

    def test_nova_bridge_omits_session_and_unsupported_options(self):
        with patch.dict('os.environ', {'NOVA_SESSION_ID': self.evaluation.session_id}):
            models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 1)
        self.assertEqual(models.client.session_id, '')
        with patch.object(models.client, '_request', return_value=completion('ok')) as remote:
            models.complete('patient', [{'role': 'user', 'content': 'sample'}], 2048, str(uuid.uuid4()))
            body = remote.call_args.args[2]
            self.assertEqual(remote.call_args.args[:2], ('POST', '/v1/chat/completions'))
            self.assertEqual(body['model'], MODEL)
            self.assertNotIn('session_id', body)
            self.assertNotIn('response_format', body)
            self.assertNotIn('stream', body)
            with self.assertRaises(NovaError):
                models.complete('gateway', [], 2048, str(uuid.uuid4()))
            self.assertEqual(remote.call_count, 1)
        self.assertNotIn('test-key', (Path(self.temp.name) / 'nova-requests.jsonl').read_text())

    def test_nova_failure_preserves_each_reservation_without_global_poisoning(self):
        models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 5)
        with patch.object(models.client, 'chat', side_effect=NovaError('API_UNAVAILABLE')) as remote:
            for _ in range(2):
                with self.assertRaises(NovaError):
                    models.complete('patient', [], 2048, str(uuid.uuid4()))
            self.assertEqual(remote.call_count, 2)
        entries = [json.loads(line) for line in (Path(self.temp.name) / 'nova-requests.jsonl').read_text().splitlines()]
        self.assertEqual([entry['status'] for entry in entries], ['reserved', 'failed_or_unknown', 'reserved', 'failed_or_unknown'])

    def test_nova_education_response_failure_allows_explicit_repair_within_ceiling(self):
        models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 2)
        first, repair = str(uuid.uuid4()), str(uuid.uuid4())
        with patch.object(models.client, 'chat', side_effect=[NovaError('PROVIDER_RESPONSE_INVALID', 503), completion('ok')]) as remote:
            with self.assertRaises(NovaError):
                models.complete('education_doctor', [], 4000, first)
            result = models.complete('education_doctor', [], 8000, repair)
            self.assertEqual(result['choices'][0]['message']['content'], 'ok')
            self.assertEqual([call.kwargs['request_id'] for call in remote.call_args_list], [first, repair])
            with self.assertRaises(NovaError) as caught:
                models.complete('education_doctor', [], 8000, str(uuid.uuid4()))
            self.assertEqual(caught.exception.code, 'MODEL_CALL_LIMIT')
            self.assertEqual(remote.call_count, 2)
        entries = [json.loads(line) for line in (Path(self.temp.name) / 'nova-requests.jsonl').read_text().splitlines()]
        self.assertEqual([entry['status'] for entry in entries], ['reserved', 'failed_or_unknown', 'reserved', 'received'])
        self.assertEqual(entries[1]['error'], 'PROVIDER_RESPONSE_INVALID')

    def test_nova_non_education_response_failure_stays_request_local(self):
        models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 5)
        with patch.object(models.client, 'chat', side_effect=NovaError('PROVIDER_RESPONSE_INVALID', 503)) as remote:
            for _ in range(2):
                with self.assertRaises(NovaError):
                    models.complete('patient', [], 2048, str(uuid.uuid4()))
            self.assertEqual(remote.call_count, 2)

    def test_nova_education_context_error_preserves_reservation_and_allows_later_patient_role(self):
        for role in ('education', 'education_doctor'):
            with self.subTest(role=role):
                models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 2)
                first, later = str(uuid.uuid4()), str(uuid.uuid4())
                with patch.object(models.client, 'chat', side_effect=[NovaError('CONTEXT_LIMIT_EXCEEDED', 400), completion('ok')]) as remote:
                    with self.assertRaises(NovaError) as caught:
                        models.complete(role, [], 8000, first)
                    self.assertEqual(caught.exception.code, 'CONTEXT_LIMIT_EXCEEDED')
                    self.assertIsNone(models.stopped)
                    models.complete('patient', [], 2048, later)
                    self.assertEqual([call.kwargs['request_id'] for call in remote.call_args_list], [first, later])
                    with self.assertRaises(NovaError) as limit:
                        models.complete('patient', [], 2048, str(uuid.uuid4()))
                    self.assertEqual(limit.exception.code, 'MODEL_CALL_LIMIT')
                    self.assertEqual(remote.call_count, 2)
                entries = [json.loads(line) for line in (Path(self.temp.name) / 'nova-requests.jsonl').read_text().splitlines()
                           if json.loads(line)['request_id'] == first]
                self.assertEqual([entry['status'] for entry in entries], ['reserved', 'failed_or_unknown'])
                self.assertEqual(entries[-1]['error'], 'CONTEXT_LIMIT_EXCEEDED')

    def test_nova_non_education_context_error_is_request_local(self):
        for role in ('clinical_rank', 'clinical_decision', 'clinical_action', 'gateway', 'input_context', 'patient'):
            with self.subTest(role=role):
                models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 5)
                with patch.object(models.client, 'chat', side_effect=NovaError('CONTEXT_LIMIT_EXCEEDED', 400)) as remote:
                    for requested_role in (role, 'patient'):
                        with self.assertRaises(NovaError):
                            models.complete(requested_role, [], 4096, str(uuid.uuid4()))
                    self.assertEqual(remote.call_count, 2)
                    self.assertEqual(models.calls, 2)

    def test_nova_independent_roles_reach_provider_after_one_failure(self):
        for role in ('input_context', 'input_mapping', 'clinical_decision', 'education', 'patient', 'examiner'):
            with self.subTest(role=role):
                models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 2)
                with patch.object(models.client, 'chat', side_effect=[NovaError('API_UNAVAILABLE'), completion('ok')]) as remote:
                    with self.assertRaises(NovaError):
                        models.complete(role, [], 2048, str(uuid.uuid4()))
                    result = models.complete('patient', [], 2048, str(uuid.uuid4()))
                    self.assertEqual(result['choices'][0]['message']['content'], 'ok')
                    self.assertEqual((remote.call_count, models.calls), (2, 2))
                    with self.assertRaises(NovaError) as limit:
                        models.complete('patient', [], 2048, str(uuid.uuid4()))
                    self.assertEqual(limit.exception.code, 'MODEL_CALL_LIMIT')
                    self.assertEqual(remote.call_count, 2)

    def test_all_public_cases_are_read_only_inputs(self):
        for case_id in ('C01', 'C03', 'C10'):
            case, digest = load_case(case_id)
            self.assertEqual(case['case_id'], case_id)
            path = Path('/cases') / case_id / 'case.json'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertTrue(case['patient_script'] and case['exam_results'])

    def test_scripted_chief_uses_only_supplied_symptom_names_and_aliases(self):
        model = ScriptedModels({})
        target = 'synthetic:concern'
        payload = {'input': 'Current concern bothers me', 'question': None, 'parser_pass': 'primary',
                   'vocabulary': [{'id': target, 'label': '검토된 증상', 'kind': 'Symptom',
                                   'aliases': ['Current concern']}]}
        result = model.parse_chief(payload)
        self.assertEqual(result['facts'][0]['value']['concept_ids'], [target])
        self.assertIn(result['facts'][0]['quote'], payload['input'])
        self.assertEqual(result['facts'][0]['value']['subject'], 'patient')
        payload['vocabulary'][0]['kind'] = 'Disease'
        self.assertEqual(model.parse_chief(payload)['facts'], [])

    def test_scripted_missing_candidate_preserves_quote_and_expansion_repairs_only_id(self):
        model = ScriptedModels({})
        target = 'synthetic:concern'
        payload = {'input': 'Current concern', 'question': None, 'parser_pass': 'primary', 'vocabulary': []}
        first = model.parse_chief(payload)
        self.assertTrue(first['needs_context'])
        original = {'field': 'S.cc', 'quote': payload['input'], 'value': {'kind': 'symptom',
                    'text': payload['input'], 'status': 'uncertain', 'concept_ids': []}}
        payload.update(parser_pass='expansion', unlinked_facts=[original],
                       vocabulary=[{'id': target, 'kind': 'Symptom', 'label': 'Current concern'}])
        repair = model.parse_chief(payload)['facts'][0]
        self.assertEqual(repair['value']['concept_ids'], [target])
        repair['value']['concept_ids'] = []
        self.assertEqual(repair, original)

    def test_scripted_missing_lexical_match_has_no_case_fallback(self):
        model = ScriptedModels({})
        payload = {'input': 'A completely different report', 'question': None, 'parser_pass': 'primary',
                   'vocabulary': [{'id': 'synthetic:concern', 'kind': 'Symptom', 'label': 'XYZ'}]}
        result = model.parse_chief(payload)
        self.assertTrue(result['needs_context'])
        self.assertEqual(result['facts'], [])

    def test_gateway_audit_retains_actual_candidates_and_empty_mapping_response(self):
        self.models.values.append('{"facts":[]}')
        self.assertEqual(self.chat()[0], 200)
        entries = json.loads((Path(self.temp.name) / 'requests.json').read_text())
        request = next(entry for entry in entries.values() if entry['path'] == '/v1/chat/completions')
        self.assertIn('messages', request['request'])
        self.assertEqual(json.loads(request['outcome'][1]['choices'][0]['message']['content']), {'facts': []})
        self.assertEqual(self.evaluation.doctor_successes, 1)

    def test_d34_roles_share_doctor_budget_and_preserve_audit_role(self):
        for task in ('gateway', 'terminology'):
            self.models.values.append({'facts': []})
            status, _ = self.request('/v1/chat/completions', session_id=self.evaluation.session_id, model=MODEL,
                messages=[{'role': 'user', 'content': json.dumps({'task': task, 'input': 'reported input'})}])
            self.assertEqual(status, 200)
        self.assertEqual([role for role, _ in self.models.roles], ['gateway', 'terminology'])
        self.assertEqual(self.evaluation.doctor_calls, 2)
        self.assertEqual(self.evaluation.turns, 0)

    def test_scripted_d34_task_handles_record_only_without_case_access(self):
        model = ScriptedModels({})
        for task in ('terminology',):
            response = model.complete(task, [{'role': 'user', 'content': json.dumps({'task': task, 'input': 'reported input'})}],
                                      2048, str(uuid.uuid4()))
            result = json.loads(response['choices'][0]['message']['content'])
            self.assertEqual(result, {'facts': [], 'clinical_content': False})

    def test_model_observation_links_actual_messages_and_errors_without_replay(self):
        self.models.values.append(NovaError('PROVIDER_UNAVAILABLE', 503))
        request_id = str(uuid.uuid4())
        for _ in range(2):
            self.assertEqual(self.request(request_id=request_id, action='SAY', content='괜찮으세요?')[0], 503)
        rows = [json.loads(line) for line in (Path(self.temp.name) / 'model-calls.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['parent_request_id'], request_id)
        self.assertEqual(rows[0]['role'], 'patient')
        self.assertIsNone(rows[0]['model'])
        self.assertIsNone(rows[0]['reasoning_effort'])
        self.assertIn('script', rows[0]['messages'][0]['content'])
        self.assertEqual(rows[1]['error'], 'PROVIDER_UNAVAILABLE')
        self.assertEqual(self.models.calls, 1)


class BrainProtocolTests(unittest.TestCase):
    def test_scripted_numeric_mapping_references_context_without_rewriting_numbers(self):
        model = ScriptedModels({})
        row = dict(assertion='present', measurement=dict(kind='interval', lower=6, upper=2, unit='month',
                   upper_unit='year', approximate=True, lower_inclusive=False),
                   candidates=[dict(id='Complaint', attributes=[dict(id='Onset', units=['month', 'year'],
                                   values=[dict(id='Categorical range')])])])
        for units, expected in ((['month', 'year'], {'Complaint': {'Onset': {'use_measurement': True}}}), (['month'], {})):
            row['candidates'][0]['attributes'][0]['units'] = units
            payload = dict(task='input_mapping', statements=[row])
            response = model.complete('gateway', [{'role': 'user', 'content': json.dumps(payload)}], 4096, 'numeric')
            self.assertEqual(json.loads(response['choices'][0]['message']['content']), [expected])

    def test_scripted_brain_supports_rank_and_action_only_contracts(self):
        from models import ScriptedModels
        model=ScriptedModels({})
        payload=dict(task='clinical_decision',required=[],stage='DifferentialDiagnosis',prior_order=['d_2'],
            candidates=[{'ref':'d_1'},{'ref':'d_2'}],questions=[{'ref':'q_1','kind':'EXAM'}])
        result=model.complete('doctor',[{'role':'user','content':json.dumps(payload)}],4096,'rank',reasoning_effort='high')
        value=json.loads(result['choices'][0]['message']['content'])
        self.assertEqual(value['ranked_disease_refs'],['d_2','d_1'])
        self.assertEqual(value['next_action'],{'kind':'ask','question_ref':'q_1'})
        payload.update(task='clinical_action',questions=[])
        result=model.complete('doctor',[{'role':'user','content':json.dumps(payload)}],4096,'action',reasoning_effort='high')
        self.assertEqual(json.loads(result['choices'][0]['message']['content']),{'next_action':{'kind':'finish_collection'}})


if __name__ == '__main__':
    stream = io.StringIO()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in (EvaluatorTests, WebTests, BrainProtocolTests))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    print(stream.getvalue())
    report = {'status': 'pass' if result.wasSuccessful() else 'fail', 'tests': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors), 'actual_nova': 'not_run',
              'official_api': 'not_run', 'evidence': stream.getvalue()}
    Path('/output/verification.json').write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
