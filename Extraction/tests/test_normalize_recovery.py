import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ontoward_extraction.__main__ import build_identity, configuration, main
from ontoward_extraction.build import accept_response, run_phase, phase_schema
from ontoward_extraction.inputs import discover, index
from ontoward_extraction.jobs import Jobs, PauseRequested
from ontoward_extraction.llm import Provider
from ontoward_extraction.models import canonical, digest, response_schema
from ontoward_extraction.recovery import recover_normalization
from support import inputs, nodes, ScriptedProvider

ROOT = Path(__file__).resolve().parents[1]


class NormalizationRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root / 'work'
        self.assets = inputs(self.root / 'assets')
        self.config = configuration(ROOT / 'config.json')
        self.entries = discover(self.assets)
        self.identity = build_identity(self.entries,self.config,self.assets)
        self.previous = copy.deepcopy(self.identity)
        self.previous['generator']['llm.py'] = 'before-schema-delivery'
        self.source_id = digest(self.previous)[:32]
        self.source = self.work / self.source_id
        jobs = Jobs(self.source,self.previous)
        with patch('sys.stdout',new=io.StringIO()):
            index(jobs,self.entries,1)
        attempted = jobs.add('normalize',{'value':'bad'})
        jobs.add('normalize',{'value':'untried'})
        for number in range(6):
            request_id = 'old-'+str(number)
            jobs.prepare_request(request_id,'nova_dev',dict(messages=[],model='openai/gpt-6-luna'),[attempted])
            response = dict(content='{"concepts":[]}',finish_reason='stop',
                usage=dict(day='2026-10-19',model='openai/gpt-6-luna',input_tokens=3,output_tokens=4))
            jobs.request_state(request_id,'received',response)
            request = jobs.db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            accept_response(jobs,request,response)
        with jobs.db:
            jobs.db.execute("UPDATE jobs SET status='failed'")
        for key,value in dict(state='failed',phase='normalize',error='output_contract_failed:normalize',normalize_frozen=True).items():
            jobs.set(key,value)
        jobs.close()

    def checksum(self):
        return hashlib.sha256((self.source / 'jobs.sqlite3').read_bytes()).hexdigest()

    def recover(self,identity=None,boundary=lambda:None):
        with patch('sys.stdout',new=io.StringIO()):
            return recover_normalization(self.work,self.source_id,identity or self.identity,boundary)

    def test_nova_sends_exact_schema_without_mutating_messages_or_models(self):
        original = [dict(role='system',content='Task'),dict(role='user',content='Untrusted source')]
        saved = copy.deepcopy(original)
        with patch.dict(os.environ,{'NOVA_DEV_KEY':'test-only'}):
            provider = Provider(self.config,self.root)
        for final,model,maximum in [(False,'openai/gpt-6-luna',8000),(True,'openai/gpt-6.1-sol',32000)]:
            payload = provider.payload('request',original,response_schema(),final)
            self.assertEqual(json.loads(payload['messages'][0]['content'].split('JSON Schema:\n',1)[1]),response_schema())
            self.assertEqual(payload['messages'][-1],original[-1])
            self.assertEqual(payload['model'],model)
            self.assertEqual(payload['max_tokens'],maximum)
            self.assertEqual(payload['reasoning_effort'],'medium')
            self.assertNotIn('response_format',payload)
        self.assertEqual(original,saved)

    def test_recover_preserves_raw_index_requests_usage_and_source_then_uses_real_adapter(self):
        before = self.checksum()
        report = self.recover()
        self.assertEqual(self.checksum(),before)
        self.assertEqual(report['model_calls_started'],0)
        jobs = Jobs(self.work/report['run_id'],self.identity)
        self.addCleanup(jobs.close)
        self.assertEqual(jobs.status()['jobs'],{'pending':2})
        self.assertEqual(jobs.status()['index']['files_completed'],len(self.entries))
        self.assertEqual(jobs.status()['requests'],{'accepted':6})
        self.assertEqual(jobs.status()['usage'][0]['calls'],6)
        self.assertEqual(jobs.get('recovery_source_identity'),self.previous)
        self.assertEqual(jobs.get('recovery')['previous_attempts'][0]['attempt_count'],6)
        self.assertEqual(jobs.db.execute('SELECT COUNT(*) FROM rf2').fetchone()[0],1)
        mock = MagicMock()
        def respond(**payload):
            schema = json.loads(payload['messages'][0]['content'].split('JSON Schema:\n',1)[1])
            self.assertEqual(schema,phase_schema('normalize'))
            packet = json.loads(payload['messages'][-1]['content'])
            results = [dict(job_id=row['job_id'],concepts=nodes(),relations=[],value_matches=[]) for row in packet['jobs']]
            return dict(choices=[dict(message=dict(content=canonical(dict(results=results))),finish_reason='stop')],
                usage=dict(prompt_tokens=5,completion_tokens=7))
        mock.chat.side_effect = respond
        with patch.dict(os.environ,{'NOVA_DEV_KEY':'test-only'}),patch('nova_sdk.Client',return_value=mock),patch('sys.stdout',new=io.StringIO()):
            with jobs.worker():
                run_phase(jobs,'normalize',self.config)
        self.assertEqual(jobs.status()['jobs'],{'done':2})
        self.assertEqual(sum(row['calls'] for row in jobs.status()['usage']),7)
        self.assertEqual(mock.chat.call_count,1)
        self.assertEqual(self.checksum(),before)

    def test_recovery_cli_uses_no_model_client_and_old_run_resume_still_fails(self):
        args = ['--config',str(ROOT/'config.json'),'--assets',str(self.assets),'--work',str(self.work)]
        with patch('ontoward_extraction.build.Provider',side_effect=AssertionError('No model call')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(['recover-normalize',*args,'--run-id',self.source_id]),0)
            with self.assertRaisesRegex(ValueError,'checkpoint_fingerprint_mismatch'):
                main(['run',*args,'--run-id',self.source_id,'--resume'])
        with self.assertRaisesRegex(ValueError,'target_exists'):
            self.recover()

    def test_recovery_rejects_changed_inputs_models_parser_and_runtime(self):
        for key in ('inputs','config','runtime_contract'):
            identity = copy.deepcopy(self.identity)
            if key=='inputs': identity[key][0]['sha256']='different'
            else: identity[key]['changed']='different'
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'identity_mismatch:'+key):
                self.recover(identity)
        identity = copy.deepcopy(self.identity)
        identity['generator']['inputs.py']='different'
        with self.assertRaisesRegex(ValueError,'index_or_semantic_contract_changed:inputs.py'):
            self.recover(identity)

    def test_recovery_rejects_completed_results_incomplete_index_and_unknown_requests(self):
        original = (self.source/'jobs.sqlite3').read_bytes()
        for change,error in [
            ("UPDATE jobs SET result='{}' WHERE attempt_count=6",'zero_accepted_results'),
            ("UPDATE meta SET value='false' WHERE key LIKE 'indexed:%'",'complete_raw_index'),
            ("UPDATE requests SET state='outcome_unknown' WHERE request_id='old-0'",'settled_requests')]:
            jobs = Jobs(self.source)
            try:
                with jobs.db: jobs.db.execute(change)
                jobs.close()
                with self.subTest(error=error),self.assertRaisesRegex(ValueError,error):
                    self.recover()
            finally:
                (self.source/'jobs.sqlite3').write_bytes(original)

    def test_recovery_respects_worker_lock_and_cancel_keeps_source_and_no_target(self):
        jobs = Jobs(self.source)
        try:
            with jobs.worker():
                with self.assertRaisesRegex(RuntimeError,'worker_already_running'):
                    self.recover()
        finally:
            jobs.set('state','failed')
            jobs.set('error','output_contract_failed:normalize')
            jobs.close()
        before = self.checksum()
        def cancel():
            if list(self.work.glob('.recovery-staging/.recover-*')):
                raise PauseRequested()
        with self.assertRaises(PauseRequested):
            self.recover(boundary=cancel)
        self.assertEqual(self.checksum(),before)
        self.assertFalse((self.work/digest(self.identity)[:32]).exists())
        self.assertEqual(list(self.work.glob('.recovery-staging/.recover-*')),[])

    def test_bad_envelopes_and_wrong_fields_have_actionable_errors(self):
        jobs = Jobs(self.root/'validation')
        self.addCleanup(jobs.close)
        job = jobs.add('normalize',{'fixture':True})
        for number,content,expected in [
            (0,'{"concepts":[]}','invalid_batch_envelope'),
            (1,'{"results":{}}','invalid_results_array'),
            (2,'{','invalid_json'),
            (3,canonical(dict(results=[dict(job_id=job,concepts=[dict(uri='x',canonical_name='X')])])),'output_validation_failed'),
            (4,canonical(dict(results=[dict(job_id=job),dict(job_id=job)])),'duplicate_job_id')]:
            ident = 'test-'+str(number)
            jobs.prepare_request(ident,'nova_dev',{},[job])
            request = jobs.db.execute('SELECT * FROM requests WHERE request_id=?',(ident,)).fetchone()
            invalid = accept_response(jobs,request,dict(content=content,finish_reason='stop'))
            self.assertIn(expected,invalid[job])
            self.assertIn(expected,jobs.status()['job_errors'][0]['error'])
        self.assertEqual(jobs.results('normalize'),[])

    def test_attempt_exhaustion_does_not_fail_untried_jobs_and_logs_reason(self):
        jobs = Jobs(self.root/'attempts')
        self.addCleanup(jobs.close)
        ids = [jobs.add('normalize',{'value':number}) for number in range(12)]
        provider = ScriptedProvider()
        provider.send=lambda payload:dict(content='{"concepts":[]}',finish_reason='stop')
        output = io.StringIO()
        with patch('sys.stdout',new=output),self.assertRaisesRegex(RuntimeError,'output_contract_failed:normalize'):
            run_phase(jobs,'normalize',self.config,provider)
        self.assertEqual(jobs.db.execute("SELECT COUNT(*) FROM jobs WHERE status='failed' AND attempt_count=6").fetchone()[0],10)
        self.assertEqual(jobs.db.execute("SELECT COUNT(*) FROM jobs WHERE status='pending'").fetchone()[0],2)
        self.assertEqual(jobs.db.execute("SELECT COUNT(*) FROM jobs WHERE status='pending' AND attempt_count=0").fetchone()[0],2)
        self.assertIn('invalid_batch_envelope',output.getvalue())
        self.assertIn('request_validated',output.getvalue())


if __name__=='__main__': unittest.main()
