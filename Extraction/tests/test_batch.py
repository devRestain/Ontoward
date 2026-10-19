import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity, configuration, main
from ontoward_extraction.build import run_phase
from ontoward_extraction.inputs import discover, index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical, digest
from ontoward_extraction.recovery import recover_normalization
from support import inputs, nodes, ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


class FixedBatchTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.config=configuration(ROOT/'config.json')

    def test_missing_rows_and_length_never_shrink_later_batches_or_recall_done(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        for number in range(35):jobs.add('normalize',{'number':number})
        provider=ScriptedProvider();send=provider.send;sizes=[];accepted=set()
        def respond(payload):
            ids=[row['job_id'] for row in json.loads(payload['messages'][-1]['content'])['jobs']]
            self.assertFalse(accepted.intersection(ids));sizes.append(len(ids))
            response=send(payload);packet=json.loads(response['content'])
            if len(sizes)<=2:
                packet['results'].pop(0)
                response['finish_reason']='length' if len(sizes)==2 else 'stop'
            accepted.update(row['job_id'] for row in packet['results'])
            response['content']=canonical(packet)
            return response
        provider.send=respond
        with patch('sys.stdout',new=io.StringIO()):run_phase(jobs,'normalize',self.config,provider)
        self.assertEqual(sizes,[10,10,10,7])
        self.assertEqual(jobs.status()['jobs'],{'done':35})
        self.assertEqual(jobs.db.execute('SELECT MAX(attempt_count) FROM jobs').fetchone()[0],3)

    def test_prior_attempts_do_not_shrink_batch_and_exhaustion_still_stops(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        for number in range(20):jobs.add('normalize',{'number':number})
        with jobs.db:jobs.db.execute('UPDATE jobs SET attempt_count=3')
        provider=ScriptedProvider();send=provider.send;sizes=[]
        def respond(payload):
            sizes.append(len(json.loads(payload['messages'][-1]['content'])['jobs']))
            return send(payload)
        provider.send=respond
        with patch('sys.stdout',new=io.StringIO()):run_phase(jobs,'normalize',self.config,provider)
        self.assertEqual(sizes,[10,10])
        ident=jobs.add('normalize',{'exhausted':True})
        with jobs.db:jobs.db.execute('UPDATE jobs SET attempt_count=6 WHERE job_id=?',(ident,))
        with self.assertRaisesRegex(RuntimeError,'output_contract_failed:normalize'):
            run_phase(jobs,'normalize',self.config,provider)
        self.assertEqual(sizes,[10,10])

    def checkpoint(self):
        assets=inputs(self.root/'assets');entries=discover(assets)
        identity=build_identity(entries,self.config,assets);previous=copy.deepcopy(identity)
        previous['generator']['build.py']='sticky-batch-shrink'
        work=self.root/'recover';source_id=digest(previous)[:32];source=Jobs(work/source_id,previous)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        done=source.add('normalize',{'done':True});pending=source.add('normalize',{'pending':True})
        source.prepare_request('good','nova_dev',{},[done])
        source.request_state('good','received',{'content':'saved'})
        source.accept('good',{done:dict(job_id=done,concepts=nodes(),relations=[],value_matches=[])},{},
            dict(day='2026-10-20',model='openai/gpt-6-luna',input_tokens=3,output_tokens=4))
        source.prepare_request('bad','nova_dev',{},[pending])
        source.request_state('bad','failed',error='PROVIDER_RESPONSE_INVALID')
        with source.db:source.db.execute("UPDATE jobs SET status='pending',attempt_count=3 WHERE job_id=?",(pending,))
        for key,value in dict(state='paused',phase='normalize',normalize_frozen=True).items():source.set(key,value)
        source.close()
        return work,source_id,identity,assets

    def test_batch_recovery_preserves_all_job_rows_requests_usage_and_source_bytes(self):
        work,source_id,identity,_=self.checkpoint();path=work/source_id/'jobs.sqlite3';before=path.read_bytes()
        with patch('sys.stdout',new=io.StringIO()):report=recover_normalization(work,source_id,identity,repair='batch')
        self.assertEqual(path.read_bytes(),before)
        source=Jobs(work/source_id,readonly=True);self.addCleanup(source.close)
        target=Jobs(work/report['run_id'],readonly=True);self.addCleanup(target.close)
        for table in ('jobs','requests','usage','rf2','source_rows'):
            self.assertEqual([tuple(row) for row in source.db.execute('SELECT * FROM '+table)],
                [tuple(row) for row in target.db.execute('SELECT * FROM '+table)])
        self.assertEqual(report['model_calls_started'],0)
        self.assertEqual(target.get('recovery')['jobs_reset'],0)

    def test_batch_recovery_rejects_unsettled_requests_changed_prompts_and_other_code(self):
        work,source_id,identity,_=self.checkpoint()
        for field in ('prompts','generator'):
            changed=copy.deepcopy(identity)
            changed[field]['final.txt' if field=='prompts' else 'llm.py']='changed'
            with self.assertRaisesRegex(ValueError,'recovery_'):
                recover_normalization(work,source_id,changed,repair='batch')
        source=Jobs(work/source_id)
        source.request_state('bad','outcome_unknown',error='network');source.close()
        with self.assertRaisesRegex(ValueError,'recovery_requires_settled_requests'):
            recover_normalization(work,source_id,identity,repair='batch')

    def test_batch_recovery_cli_never_constructs_model_client(self):
        work,source_id,_,assets=self.checkpoint()
        with patch('ontoward_extraction.build.Provider',side_effect=AssertionError('model client')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(['recover-normalize-batch','--work',str(work),'--assets',str(assets),
                '--config',str(ROOT/'config.json'),'--run-id',source_id]),0)
