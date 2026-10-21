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

    def test_three_scenarios_are_reserved_and_claimed_once_as_one_batch(self):
        status, batch = self.request(body={'case': 'all', 'backend': 'nova', 'maximum': 37})
        self.assertEqual(status, 202)
        self.assertEqual([run['case'] for run in batch['runs']], ['C01', 'C03', 'C10'])
        self.assertEqual(len({run['id'] for run in batch['runs']}), 3)
        self.assertTrue(all(run['maximum'] == 37 for run in batch['runs']))
        output = io.StringIO()
        with redirect_stdout(output):
            self.runs.worker('claim', [])
            self.runs.worker('claim', [])
        self.assertEqual(output.getvalue().splitlines(), [
            f"{run['id']} {run['case']} nova 37" for run in batch['runs']])
        self.assertEqual(read(self.runs.control / 'active').splitlines(), [run['id'] for run in batch['runs']])
        self.assertEqual(self.request(body={'case': 'all', 'backend': 'scripted', 'maximum': 1})[0], 409)

    def test_batch_failure_releases_only_its_member_until_all_runs_finish(self):
        _, batch = self.request(body={'case': 'all', 'backend': 'scripted', 'maximum': 1})
        with redirect_stdout(io.StringIO()):
            self.runs.worker('claim', [])
        for index, run in enumerate(batch['runs']):
            path = self.runs.directory(run['id'])
            (self.runs.lock / 'members' / run['id'] / 'started').mkdir()
            write(path / 'status', 'failed' if index == 0 else 'completed')
            self.runs.worker('finish', [run['id']])
            self.assertTrue((path / 'report.html').exists())
            self.assertEqual(self.request()[1]['busy'], index < 2)
            for sibling in batch['runs'][index + 1:]:
                self.assertEqual(self.runs.status(sibling['id'])['state'], 'starting')
        self.assertFalse(read(self.runs.control / 'active'))
        self.assertEqual(len(self.runs.listing()), 3)

    def test_stop_interrupts_every_batch_member_without_resuming(self):
        for claim in (False, True):
            self.runs.worker('tick', [])
            _, batch = self.request(body={'case': 'all', 'backend': 'scripted', 'maximum': 1})
            if claim:
                with redirect_stdout(io.StringIO()):
                    self.runs.worker('claim', [])
            self.runs.worker('stop', [])
            self.assertTrue(all(self.runs.status(run['id'])['state'] == 'interrupted' for run in batch['runs']))
            self.assertFalse(self.runs.lock.exists())
            self.assertFalse((self.runs.control / 'request').exists())
            self.assertFalse(read(self.runs.control / 'active'))

    def test_batch_preparation_failure_never_publishes_partial_launch(self):
        original = write
        def fail_second_metadata(path, value):
            if path.name == 'run.json' and path.parent.name.startswith('C03-'):
                raise OSError('storage unavailable')
            original(path, value)
        with patch('web.write', side_effect=fail_second_metadata):
            self.assertEqual(self.request(body={'case': 'all', 'backend': 'scripted', 'maximum': 1})[0], 500)
        self.assertFalse(self.runs.lock.exists())
        self.assertFalse((self.runs.control / 'request').exists())
        self.assertTrue(all(run['state'] == 'failed' for run in self.runs.listing()))

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

    def test_legacy_creation_time_remains_stable_after_report_refresh(self):
        path = self.runs.root / 'legacy-run'
        path.mkdir()
        write(path / 'run.args', 'C10\nscripted\n200\n')
        write(path / 'started', '12345')
        before = self.runs.status(path.name)['created']
        self.assertEqual(self.request('/runs/legacy-run/report.html')[0], 200)
        self.assertEqual(self.runs.status(path.name)['created'], before)
        self.assertEqual(before, 12345)

    def test_closed_collector_with_open_calls_remains_incomplete(self):
        run = self.start()
        path = self.runs.directory(run['id'])
        (path / 'agent').mkdir()
        rows = [dict(seq=1, kind='initial', state={}),
                dict(seq=2, kind='call_start', call_id=1, parent_call_id=None, owner='DoctorEar', method='process_input'),
                dict(seq=3, kind='end')]
        write(path / 'agent/trace.jsonl', '\n'.join(json.dumps(row) for row in rows))
        data = render(path)
        self.assertEqual(data['trace']['status'], 'incomplete')
        self.assertEqual(data['inspection']['status'], 'fail')
        self.assertEqual(next(c for c in data['inspection']['checks'] if c['id']=='call_boundaries')['status'], 'fail')
        status, inspection = self.request(f"/runs/{run['id']}/inspection.json")
        self.assertEqual(status, 200)
        self.assertEqual(inspection, data['inspection'])
        self.assertEqual(self.request(f"/runs/{run['id']}/agent/trace.jsonl")[0], 404)

    def test_inspection_rejects_frozen_mutation_and_wrong_submission(self):
        from inspection import inspect_run
        case = {'facts': {'f': {'target': 'Headache'}}, 'notes': {}, 'revision': 1, 'chief_fact_id': 'f',
                'assessment': {'frozen': True, 'based_on_case_revision': 1, 'based_on_chief_fact_id': 'f',
                               'differential': [{'name': 'Headache'}]}}
        rows = [dict(seq=1, kind='initial', state={'case': case, 'interview': {'current':'Education'}, 'session': {'termination':'submitted'}}),
                dict(seq=2, kind='node_start', node='process_input'),
                dict(seq=3, kind='node_end', node='process_input', patch=[{'op':'replace','path':['case','facts','f','target'],'value':'Changed'}]),
                dict(seq=4, kind='sdk_request', path='/actions', request_id='submit', body={'action':'DIAGNOSE','diagnosis':'Different','note':{}}),
                dict(seq=5, kind='sdk_response', path='/actions', request_id='submit', response={'status':'completed'}),
                dict(seq=6, kind='end')]
        saved = dict(trace={'events': rows}, warnings=[], summary={'status':'completed','receipt':{'status':'completed'}},
                     record={'note':{},'diagnosis':'Another'})
        before = copy.deepcopy(saved)
        result = inspect_run(saved)
        checks = {c['id']:c['status'] for c in result['checks']}
        self.assertEqual(result['status'], 'fail')
        for key in ('frozen_patient_state','submission_primary','received_soap'):
            self.assertEqual(checks[key], 'fail', key)
        self.assertEqual(checks['confirmed_completion'], 'pass')
        self.assertEqual(saved, before)

    def test_legacy_inspection_reports_missing_provenance_without_invention(self):
        run = self.start()
        path = self.runs.directory(run['id'])
        data = render(path)
        self.assertEqual(data['inspection']['status'], 'not_collected')
        self.assertIsNone(data['inspection']['runtime'])
        self.assertIsNone(data['inspection']['graph'])
        self.assertTrue(all(c['status']=='not_collected' for c in data['inspection']['checks']))

    def test_current_inspection_rejects_missing_observers_and_source_pins(self):
        from inspection import inspect_run
        events = [dict(seq=1, kind='start', format_version=7),
                  dict(seq=2, kind='settings', pipeline=dict(version=2, contract='D59',
                      required_sources=['knowledge/guideline_passages.py']),
                      coverage=[dict(object_id='workflow.education', missing=['source_contexts'])],
                      runtime=dict(source_sha256={})),
                  dict(seq=3, kind='initial', state={'case': {}, 'session': {}}),
                  dict(seq=4, kind='runtime_check', changed_sources=[dict(path='workflow/education.py')]),
                  dict(seq=5, kind='end')]
        saved = dict(trace={'events': events}, warnings=[], summary={}, record={})
        original = copy.deepcopy(saved)
        checks = {row['id']: row['status'] for row in inspect_run(saved)['checks']}
        for key in ('observation_coverage', 'runtime_sources', 'runtime_stability'):
            self.assertEqual(checks[key], 'fail')
        self.assertEqual(saved, original)
        from inspection import inspect_run
        legacy = inspect_run(dict(trace={'events':[{'seq':1,'kind':'initial','state':{'session':{},'interaction':{'termination':'submitted'}}},
                                                  {'seq':2,'kind':'end'}]}, warnings=[], record={},
                                  summary={'status':'completed','receipt':{'status':'completed'}}))
        checks = {c['id']:c['status'] for c in legacy['checks']}
        self.assertEqual(checks['confirmed_completion'], 'pass')
        self.assertEqual(checks['frozen_patient_state'], 'not_collected')

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

    def test_object_observation_keeps_types_and_excludes_service_credentials(self):
        from dataclasses import dataclass
        @dataclass
        class Snapshot:
            values: tuple
        class Service:
            token = 'credential-never-serialized'
        trace = Trace(Path(self.temp.name) / 'objects.jsonl')
        value = trace.value({'snapshot': Snapshot((1, {'id': 'fact-1'})), 'client': Service()})
        self.assertEqual(value['snapshot']['type'], 'Snapshot')
        self.assertEqual(value['snapshot']['data']['values'], {'type': 'tuple', 'data': [1, {'id': 'fact-1'}]})
        self.assertEqual(value['client'], {'type': 'Service', 'reference_only': True})
        self.assertNotIn('credential-never-serialized', json.dumps(value))

    def test_large_return_values_preserve_content_without_repeated_serialization(self):
        path = Path(self.temp.name) / 'values.jsonl'
        trace = Trace(path)
        original = {'candidates': [{'name': str(i), 'evidence': ['Registered evidence ' * 400]} for i in range(8)]}
        first = trace.value(original)
        second = trace.value(copy.deepcopy(original))
        self.assertEqual(first, second)
        self.assertEqual(trace.expanded(first), original)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len({row['value_id'] for row in rows}), len(rows))
        self.assertLess(path.stat().st_size, len(json.dumps(original).encode()) * 1.2)
        self.assertEqual(len(rows), 1)

    def test_mounted_output_preserves_launcher_run_identity(self):
        path = self.runs.root / 'mounted-output'
        path.mkdir()
        write(path / 'run-id', 'actual-run-identity')
        self.assertEqual(collect(path)['run_id'], 'actual-run-identity')

    def test_collaborator_capture_excludes_services_and_preserves_errors(self):
        class DifferentialDiagnosisSession:
            def __init__(self):
                self.last_input, self.error = None, None
                self.client = {'token': 'credential-never-serialized'}
            def decide(self):
                self.last_input = (3, 'chief-1', 'response-2')
                self.error = 'original-failure'
                raise ValueError(self.error)
        path = Path(self.temp.name) / 'collaborator.jsonl'
        trace, session = Trace(path), DifferentialDiagnosisSession()
        call = trace.wrap(session.decide, 'DifferentialDiagnosisSession', 'decide', 'consultation.sessions.DD')
        with self.assertRaisesRegex(ValueError, '^original-failure$'):
            call()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([row['kind'] for row in rows], ['call_start', 'call_error'])
        self.assertEqual(rows[0]['owner_state'], {'last_input': None, 'error': None})
        self.assertEqual(rows[-1]['owner_state']['last_input']['data'], [3, 'chief-1', 'response-2'])
        self.assertEqual(rows[-1]['owner_state']['error'], session.error)
        self.assertNotIn('credential-never-serialized', path.read_text())
        self.assertFalse(trace.stack)
