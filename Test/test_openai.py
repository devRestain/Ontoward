"""Offline adapter/SDK tests. Never contact OpenAI or read a real API key."""
from collections import deque
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch
import uuid

from nova_sdk import Client, NovaError, empty_record
from openai_models import OpenAIModels
from server import Evaluation, http_server, load_case
from version import source_version


def response(text='{"content":"알겠습니다","effective_content":"안내입니다"}', *, truncated=False):
    return dict(id='resp-fixture', model='gpt-6-luna', status='incomplete' if truncated else 'completed',
                incomplete_details={'reason': 'max_output_tokens'} if truncated else None,
                output=[{'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}],
                usage={'input_tokens': 123, 'output_tokens': 8000 if truncated else 30,
                       'input_tokens_details': {'cached_tokens': 20},
                       'output_tokens_details': {'reasoning_tokens': 8000 if truncated else 10}})


class Reply(io.BytesIO):
    headers = {'x-request-id': 'req-fixture'}

    def __init__(self, raw):
        super().__init__(json.dumps(raw).encode())


class FakeOpener:
    def __init__(self, *replies):
        self.replies, self.requests = deque(replies), []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        raw = self.replies.popleft()
        if isinstance(raw, Exception):
            raise raw
        return Reply(raw)


class OpenAITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.models = OpenAIModels('offline-secret', self.temp.name, 10)

    def complete(self, role='clinical_rank'):
        return self.models.complete(role, [{'role': 'system', 'content': 'Return JSON'},
            {'role': 'user', 'content': '{"task":"clinical_rank"}'}], 8000, str(uuid.uuid4()), reasoning_effort='high')

    def test_exact_request_and_usage_without_credentials_in_evidence(self):
        self.models.opener = FakeOpener(response('[]'))
        actual = self.complete('input_mapping')
        request, timeout = self.models.opener.requests[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(request.get_header('Authorization'), 'Bearer offline-secret')
        self.assertEqual(timeout, 240)
        self.assertEqual(set(body), {'model', 'input', 'reasoning', 'max_output_tokens', 'store'})
        self.assertEqual((body['model'], body['reasoning'], body['max_output_tokens'], body['store']),
                         ('gpt-6-luna', {'effort': 'high'}, 8000, False))
        self.assertEqual(actual['choices'][0]['message']['content'], '[]')
        self.assertEqual(actual['usage']['completion_tokens'], 30)
        self.assertEqual(actual['usage']['completion_tokens_details']['reasoning_tokens'], 10)
        evidence = (Path(self.temp.name) / 'openai-requests.jsonl').read_text()
        self.assertNotIn('offline-secret', evidence)
        self.assertNotIn('Authorization', evidence)
        entries = [json.loads(row) for row in evidence.splitlines()]
        self.assertEqual(entries[1]['provider_request_id'], 'req-fixture')
        self.assertEqual(request.get_header('X-client-request-id'), entries[0]['request_id'])

    def test_configuration_requires_key_and_explicit_valid_model(self):
        for key, maximum, model in (('', 2, 'gpt-6-luna'), ('key', True, 'gpt-6-luna'),
                                   ('key', 0, 'gpt-6-luna'), ('key', 1001, 'gpt-6-luna'),
                                   ('key', 2, 'openai/gpt-6-luna')):
            with self.assertRaises(ValueError):
                OpenAIModels(key, self.temp.name, maximum, model)
        self.assertEqual(OpenAIModels('key', self.temp.name, 1, 'explicit-model').model, 'explicit-model')

    def test_local_ceiling_is_shared_across_roles(self):
        self.models.maximum = 1
        self.models.opener = FakeOpener(response())
        self.complete('patient')
        with self.assertRaises(NovaError) as caught:
            self.complete('clinical_rank')
        self.assertEqual(caught.exception.code, 'MODEL_CALL_LIMIT')
        self.assertEqual(len(self.models.opener.requests), 1)

    def error(self, code, status=429):
        return urllib.error.HTTPError('https://api.openai.com/v1/responses', status, 'error',
            {'x-request-id': 'req-error'}, io.BytesIO(json.dumps({'error': {'code': code,
                                                   'message': 'Do not log offline-secret'}}).encode()))

    def test_rate_limit_stays_distinct_and_does_not_retry_or_poison_other_roles(self):
        self.models.opener = FakeOpener(self.error('rate_limit_exceeded'), response())
        with self.assertRaises(NovaError) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'OPENAI_RATE_LIMIT')
        self.assertEqual(len(self.models.opener.requests), 1)
        self.complete('patient')
        self.assertEqual(len(self.models.opener.requests), 2)
        self.assertNotIn('offline-secret', (Path(self.temp.name) / 'openai-requests.jsonl').read_text())

    def test_confirmed_quota_or_auth_stops_further_transmissions(self):
        for code, status, expected in (('insufficient_quota', 429, 'REQUEST_BUDGET_EXHAUSTED'),
                                       ('invalid_api_key', 401, 'OPENAI_AUTHENTICATION_ERROR')):
            with self.subTest(code=code):
                self.models.stopped = None
                self.models.opener = FakeOpener(self.error(code, status))
                for role in ('clinical_rank', 'patient'):
                    with self.assertRaises(NovaError) as caught:
                        self.complete(role)
                    self.assertEqual(caught.exception.code, expected)
                self.assertEqual(len(self.models.opener.requests), 1)

    def test_context_error_is_request_local(self):
        self.models.opener = FakeOpener(self.error('context_length_exceeded', 400), response())
        with self.assertRaises(NovaError) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'CONTEXT_LIMIT_EXCEEDED')
        self.complete('patient')

    def test_timeout_is_unknown_and_never_automatically_retransmitted(self):
        self.models.opener = FakeOpener(TimeoutError())
        with self.assertRaises(NovaError) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'OPENAI_OUTCOME_UNKNOWN')
        self.assertEqual(len(self.models.opener.requests), 1)
        entries = [json.loads(row) for row in (Path(self.temp.name) / 'openai-requests.jsonl').read_text().splitlines()]
        self.assertEqual(entries[-1]['status'], 'outcome_unknown')

    def test_incomplete_reasoning_only_usage_reaches_sdk_without_double_counting(self):
        self.models.opener = FakeOpener(response('', truncated=True))
        case, digest = load_case('C10')
        evaluation = Evaluation(case, self.models, self.temp.name, backend='openai_api', case_hash=digest)
        evaluation.dispatch('POST', '/_nova/ready', {})
        status, result = evaluation.dispatch('POST', '/v1/chat/completions', {
            'request_id': str(uuid.uuid4()), 'session_id': evaluation.session_id,
            'messages': [{'role': 'user', 'content': 'Interpret evidence'}], 'max_tokens': 8000})
        self.assertEqual(status, 200)
        self.assertEqual(result['choices'][0]['finish_reason'], 'length')
        self.assertEqual((evaluation.doctor_calls, evaluation.input_tokens, evaluation.output_tokens), (1, 123, 8000))
        self.assertEqual(evaluation.doctor_successes, 0)

    def test_malformed_response_is_saved_and_never_retried(self):
        self.models.opener = FakeOpener({'status': 'completed'})
        with self.assertRaises(NovaError) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'PROVIDER_RESPONSE_INVALID')
        self.assertEqual(len(self.models.opener.requests), 1)
        self.assertIn('"response": {"status": "completed"}',
                      (Path(self.temp.name) / 'openai-requests.jsonl').read_text())

    def test_original_sdk_doctor_patient_idempotency_and_receipt(self):
        self.models.opener = FakeOpener(response('{"result":1}'), response())
        case, digest = load_case('C10')
        evaluation = Evaluation(case, self.models, self.temp.name, backend='openai_api', case_hash=digest)
        server = http_server(evaluation, 'local-token', ('127.0.0.1', 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = Client(api_base=f'http://127.0.0.1:{server.server_port}', token='local-token',
                            session_id=evaluation.session_id)
            client.ready()
            answer = client.chat([{'role': 'user', 'content': 'Interpret evidence'}], max_tokens=8000)
            self.assertEqual(answer['usage']['prompt_tokens'], 123)
            identity = str(uuid.uuid4())
            first = client.say('안내입니다', request_id=identity)
            self.assertEqual(client.say('안내입니다', request_id=identity), first)
            note = empty_record(); note['S']['cc'] = 'Protocol fixture'
            self.assertEqual(client.diagnose(note=note, diagnosis='Protocol fixture')['status'], 'completed')
            self.assertEqual(len(self.models.opener.requests), 2)
            summary = json.loads((Path(self.temp.name) / 'summary.json').read_text())
            self.assertEqual((summary['backend'], summary['provider_model']), ('openai_api', 'gpt-6-luna'))
            self.assertEqual(summary['limits']['output_tokens'], 100000)
            self.assertEqual(summary['provider_usage']['input_tokens'], 246)
            self.assertEqual(summary['provider_usage']['output_tokens'], 60)
            self.assertTrue(summary['test_runtime']['source_sha256'])
            self.assertEqual(summary['official_api'], 'not_run')
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_source_version_rejects_old_image_and_ignores_credentials(self):
        root = Path(self.temp.name)
        (root / 'server.py').write_text('first')
        first = source_version(root)
        (root / '.env').write_text('OPENAI_API_KEY=offline-secret')
        self.assertEqual(source_version(root), first)
        (root / 'server.py').write_text('second')
        self.assertNotEqual(source_version(root)['sha256'], first['sha256'])
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('version.py')),
                                 '--check', str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'fail')
        self.assertIn('Test image is stale', result.stderr)


if __name__ == '__main__':
    unittest.main()
