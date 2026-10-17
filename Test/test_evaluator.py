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


class Replies:
    def __init__(self, *values):
        self.values, self.calls, self.roles = deque(values), 0, []

    def complete(self, role, messages, max_tokens, request_id):
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
        def blocking(*args):
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
        self.evaluation.doctor_calls, self.evaluation.output_tokens = 0, 100000
        self.assertEqual(self.chat()[1]['error']['code'], 'MODEL_TOKEN_BUDGET')
        self.assertEqual(self.request('/v1/chat/completions', session_id=self.evaluation.session_id,
                                      model='other')[1]['error']['code'], 'MODEL_NOT_ALLOWED')
        self.assertEqual(self.models.calls, 0)

    def test_missing_process_evidence_is_failure(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(report(self.temp.name), 1)
        result = json.loads((Path(self.temp.name) / 'result.json').read_text())
        self.assertIn('agent/process.json', result['missing_evidence'])
        self.assertFalse(result['checks']['agent_exit_zero'])
        self.assertFalse(result['checks']['no_development_key_in_agent'])

    def test_returned_usage_over_budget_is_not_success(self):
        self.models.complete = lambda *args: completion('ok', prompt_tokens=500001)
        self.assertEqual(self.chat()[1]['error']['code'], 'MODEL_TOKEN_BUDGET')
        self.assertEqual(self.evaluation.doctor_successes, 0)
        self.assertEqual(self.evaluation.input_tokens, 500001)

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

    def test_nova_failure_stops_new_calls_and_preserves_reservation(self):
        models = NovaModels('https://nova.snubhai.org', 'test-key', self.temp.name, 5)
        with patch.object(models.client, 'chat', side_effect=NovaError('API_UNAVAILABLE')) as remote:
            for _ in range(2):
                with self.assertRaises(NovaError):
                    models.complete('patient', [], 2048, str(uuid.uuid4()))
            self.assertEqual(remote.call_count, 1)
        entries = [json.loads(line) for line in (Path(self.temp.name) / 'nova-requests.jsonl').read_text().splitlines()]
        self.assertEqual([entry['status'] for entry in entries], ['reserved', 'failed_or_unknown'])

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


if __name__ == '__main__':
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EvaluatorTests))
    print(stream.getvalue())
    report = {'status': 'pass' if result.wasSuccessful() else 'fail', 'tests': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors), 'actual_nova': 'not_run',
              'official_api': 'not_run', 'evidence': stream.getvalue()}
    Path('/output/verification.json').write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
