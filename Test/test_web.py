from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from observe import changes, Trace
from viewer import collect, render
from web import http_server, read, Runs, write


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Runs(self.temp.name)
        self.runs.worker('tick', [])
        self.server = http_server(self.runs, ('127.0.0.1', 0))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path='/api/runs', body=None, headers=None):
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.code, json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw.decode()

    def start(self):
        status, result = self.request(body={'case': 'C10', 'backend': 'scripted', 'maximum': 200})
        self.assertEqual(status, 202)
        return result

    def test_start_status_refresh_and_exclusive_execution(self):
        run = self.start()
        self.assertEqual(self.request('/api/runs/' + run['id'])[1]['id'], run['id'])
        listing = self.request()[1]
        self.assertTrue(listing['busy'])
        self.assertEqual(len(listing['runs']), 1)
        self.assertEqual(self.request(body={'case': 'C01', 'backend': 'nova', 'maximum': 50})[0], 409)
        self.assertEqual(read(self.runs.lock / 'owner'), run['id'])

    def test_cli_lock_blocks_web_start(self):
        self.runs.lock.mkdir()
        write(self.runs.lock / 'owner', 'C10-cli')
        self.assertEqual(self.request(body={'case': 'C10', 'backend': 'scripted', 'maximum': 1})[0], 409)
        self.assertFalse((self.runs.control / 'request').exists())

    def test_worker_disconnection_preserves_partial_run_without_resume(self):
        run = self.start()
        write(self.runs.control / 'heartbeat', '0')
        status = self.request('/api/runs/' + run['id'])[1]
        self.assertEqual(status['state'], 'interrupted')
        self.assertIsNotNone(status['report_url'])
        self.assertEqual(self.request(body={'case': 'C10', 'backend': 'nova', 'maximum': 200})[0], 503)
        self.assertEqual(len(self.runs.listing()), 1)

    def test_invalid_requests_never_reserve_a_run(self):
        good = {'case': 'C10', 'backend': 'nova', 'maximum': 200}
        for body in ([], {}, {**good, 'command': 'docker'}, {**good, 'case': '../C10'},
                     {**good, 'maximum': True}, {**good, 'maximum': 0}, {**good, 'maximum': 1001},
                     {**good, 'maximum': 1.1}, {**good, 'backend': 'remote'}):
            self.assertEqual(self.request(body=body)[0], 400)
        self.assertFalse(self.runs.lock.exists())

    def test_cross_origin_and_arbitrary_paths_are_rejected(self):
        body = {'case': 'C10', 'backend': 'nova', 'maximum': 200}
        self.assertEqual(self.request(body=body, headers={'Origin': 'http://example.com'})[0], 403)
        self.assertEqual(self.request(body=body, headers={'Host': 'example.com'})[0], 403)
        self.assertEqual(self.request('/.env')[0], 404)
        self.assertEqual(self.request('/api/runs/../outside')[0], 400)
        (self.runs.root / 'linked').symlink_to('/tmp')
        self.assertEqual(self.request('/runs/linked/report.html')[0], 400)

    def test_claim_once_complete_and_view_saved_report(self):
        run = self.start()
        output = io.StringIO()
        with redirect_stdout(output):
            self.runs.worker('claim', [])
            self.runs.worker('claim', [])
        self.assertEqual(output.getvalue().splitlines(), [f"{run['id']} C10 scripted 200"])
        path = self.runs.directory(run['id'])
        write(path / 'status', 'completed')
        write(path / 'result.json', json.dumps({'status': 'pass'}))
        self.runs.worker('finish', [run['id']])
        current = self.request('/api/runs/' + run['id'])[1]
        self.assertEqual((current['state'], current['result']), ('completed', 'pass'))
        self.assertEqual(self.request(current['report_url'])[0], 200)
        self.assertFalse(self.request()[1]['busy'])
        self.assertEqual(self.request()[1]['runs'][0]['id'], run['id'])

    def test_start_failure_timeout_and_interrupt_remain_viewable(self):
        for state in ('failed', 'timeout', 'interrupted'):
            run = self.start()
            path = self.runs.directory(run['id'])
            write(path / 'status', state)
            write(path / 'runner.log', 'NOVA_DEV_KEY is required' if state == 'failed' else state)
            self.runs.worker('finish', [run['id']])
            current = self.request('/api/runs/' + run['id'])[1]
            self.assertEqual(current['state'], state)
            self.assertIn('NOVA_DEV_KEY' if state == 'failed' else state, self.request(current['report_url'])[1])

    def test_stop_marks_pending_run_interrupted_and_allows_only_new_explicit_start(self):
        run = self.start()
        self.runs.worker('stop', [])
        self.assertEqual(self.runs.status(run['id'])['state'], 'interrupted')
        self.assertFalse((self.runs.control / 'request').exists())
        self.runs.worker('tick', [])
        self.assertNotEqual(self.start()['id'], run['id'])

    def test_failure_is_published_only_after_the_report_is_written(self):
        run = self.start()
        def finish_report(path):
            current = self.runs.status(run['id'])
            self.assertEqual(current['state'], 'starting')
            self.assertIsNone(current['report_url'])
            return render(path)
        with patch('web.render', side_effect=finish_report):
            self.runs.worker('finish', [run['id']])
        current = self.runs.status(run['id'])
        self.assertEqual(current['state'], 'failed')
        self.assertTrue((self.runs.directory(run['id']) / 'report.html').exists())

    def test_reports_escape_model_html_and_preserve_legacy_inputs(self):
        run = self.start()
        path = self.runs.directory(run['id'])
        (path / 'simulator').mkdir()
        attack = '</script><script>throw new Error("patient HTML")</script> JSON @@JS@@'
        write(path / 'simulator/transcript.json', json.dumps({'initial': {'opening': attack}, 'events': []}))
        packed = render(path)
        html = (path / 'report.html').read_text()
        self.assertNotIn(attack, html)
        raw = re.search(r'id="report-data">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(json.loads(raw)['transcript']['initial']['opening'], attack)
        self.assertEqual(packed['trace']['status'], 'not_collected')

    def test_opening_saved_report_refreshes_note_view_without_running_case(self):
        run = self.start()
        path = self.runs.directory(run['id'])
        self.runs.worker('finish', [run['id']])
        write(path / 'report.html', 'old report')
        (path / 'simulator').mkdir()
        record = {'note': {'S': {'cc': '</script><script>patient()</script>'}}, 'diagnosis': 'saved diagnosis'}
        write(path / 'simulator/record.json', json.dumps(record))
        status_before = (path / 'status').read_bytes()
        status, html = self.request(f"/runs/{run['id']}/report.html")
        self.assertEqual(status, 200)
        packed = json.loads(re.search(r'id="report-data">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(packed['record'], record)
        self.assertEqual(packed['trace']['status'], 'not_collected')
        self.assertNotIn(record['note']['S']['cc'], html)
        self.assertEqual((path / 'status').read_bytes(), status_before)
        self.assertFalse((self.runs.control / 'request').exists())
        self.assertFalse(self.runs.lock.exists())
        self.assertEqual((path / 'report.html').read_text(), html)

    def test_partial_trace_keeps_valid_events_and_marks_missing_tail(self):
        run = self.start()
        path = self.runs.directory(run['id'])
        (path / 'agent').mkdir()
        write(path / 'agent/trace.jsonl', json.dumps({'seq': 1, 'kind': 'initial', 'state': {}}) + '\n{"seq":2')
        data = collect(path)
        self.assertEqual(data['trace']['status'], 'incomplete')
        self.assertEqual(len(data['trace']['events']), 1)
        self.assertTrue(data['warnings'])

    def test_state_patches_reconstruct_nested_values_lists_and_removals(self):
        states = [{'a': [1, {'값': '이전'}, 3], 'removed': True},
                  {'a': [1, {'값': '이후'}, 3, {'new': []}], 'added': 'x'}, {'a': [2]}, {'a': 'replacement'}]
        for before, after in zip(states, states[1:]):
            state = copy.deepcopy(before)
            for item in changes(before, after):
                target = state
                for key in item['path'][:-1]:
                    target = target[key]
                key = item['path'][-1]
                if item['op'] == 'remove':
                    del target[key]
                elif isinstance(target, list) and item['op'] == 'add':
                    target.insert(key, item['value'])
                else:
                    target[key] = item['value']
            self.assertEqual(state, after)

    def test_trace_disk_failure_is_nonfatal(self):
        trace = Trace(Path(self.temp.name) / 'missing' / 'trace.jsonl')
        trace.emit('start')
        trace.emit('end')
        self.assertTrue(trace.failed)
