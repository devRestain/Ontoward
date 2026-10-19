import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity, configuration, main
from ontoward_extraction.build import accept_response, collected, empty_bodhi_candidate, run_phase
from ontoward_extraction.inputs import discover, index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical, digest
from ontoward_extraction.recovery import recover_normalization
from support import inputs, nodes, ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


def blank():
    return dict(source='bodhi:nodes_symptom',kind_hint='Symptom',name='',
        raw=dict(uuid='\u200b',name='',root_snomed_id='',child1_name='\t \ufeff'),
        snomed_descriptions=[],snomed_definitions=[])


class EmptySourceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.config=configuration(ROOT/'config.json')

    def test_only_fully_blank_bodhi_nodes_are_excluded(self):
        self.assertTrue(empty_bodhi_candidate(blank()))
        for field,value in [('name','Pain'),('uuid','source-id'),('name','0'),('count',0),('extra',[])]:
            source=blank();source['raw'][field]=value
            with self.subTest(field=field,value=value):self.assertFalse(empty_bodhi_candidate(source))
        for field,value in [('name','Source concept'),('snomed_descriptions',[{'term':'Pain'}]),
            ('snomed_definitions',[{'destinationId':'100001'}]),('source','astra')]:
            self.assertFalse(empty_bodhi_candidate(dict(blank(),**{field:value})))
        self.assertFalse(empty_bodhi_candidate(dict(blank(),raw={})))

    def test_empty_source_uses_no_model_call_and_preserves_attempts_and_raw_input(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        excluded=jobs.add('normalize',blank());valid=jobs.add('normalize',{'name':'Pain'})
        with jobs.db:jobs.db.execute("UPDATE jobs SET attempt_count=6,status='failed',error='missing_generated_concepts' WHERE job_id=?",(excluded,))
        provider=ScriptedProvider()
        with patch('sys.stdout',new=io.StringIO()):run_phase(jobs,'normalize',self.config,provider)
        self.assertEqual(provider.calls,[valid])
        row=jobs.db.execute('SELECT * FROM jobs WHERE job_id=?',(excluded,)).fetchone()
        self.assertEqual(row['attempt_count'],6);self.assertEqual(row['normalized_input'],canonical(blank()))
        self.assertEqual(json.loads(row['result'])['concepts'],[])
        self.assertEqual(jobs.get('excluded:'+excluded)['reason'],'empty_bodhi_source_row')
        self.assertTrue(collected(jobs,['normalize'])[0])
        with patch('sys.stdout',new=io.StringIO()):run_phase(jobs,'normalize',self.config,provider)
        self.assertEqual(provider.calls,[valid])

    def test_nonempty_source_still_rejects_empty_concepts(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        ident=jobs.add('normalize',dict(blank(),name='Pain',raw={'name':'Pain'}))
        jobs.prepare_request('empty','nova_dev',{},[ident])
        request=jobs.db.execute('SELECT * FROM requests').fetchone()
        invalid=accept_response(jobs,request,dict(finish_reason='stop',content=canonical(
            dict(results=[dict(job_id=ident,concepts=[],relations=[],value_matches=[])]))))
        self.assertEqual(invalid,{ident:'missing_generated_concepts'})
        self.assertEqual(jobs.status()['jobs'],{'retry':1})

    def checkpoint(self):
        assets=inputs(self.root/'assets');entries=discover(assets)
        identity=build_identity(entries,self.config,assets);previous=copy.deepcopy(identity)
        previous['generator']['build.py']='before-blank-source-exclusion'
        work=self.root/'recover';source_id=digest(previous)[:32];source=Jobs(work/source_id,previous)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        done=source.add('normalize',{'name':'Completed'});empty=source.add('normalize',blank())
        retry=source.add('normalize',{'name':'Pending clinical meaning'})
        source.prepare_request('first','nova_dev',{},[done])
        source.request_state('first','received',dict(content='saved response'))
        source.accept('first',{done:dict(job_id=done,concepts=nodes(),relations=[],value_matches=[])},{},
            dict(day='2026-10-20',model='openai/gpt-6-luna',input_tokens=3,output_tokens=4))
        for attempt in range(6):
            ident='empty-'+str(attempt);source.prepare_request(ident,'nova_dev',{},[empty])
            source.request_state(ident,'received',dict(content='saved empty response'))
            source.accept(ident,{}, {empty:'missing_generated_concepts'},
                dict(day='2026-10-20',model='openai/gpt-6-luna',input_tokens=3,output_tokens=4))
        with source.db:
            source.db.execute("UPDATE jobs SET status='failed' WHERE job_id=?",(empty,))
            source.db.execute("UPDATE jobs SET status='retry',attempt_count=1,error='missing_result' WHERE job_id=?",(retry,))
        for key,value in dict(state='failed',error='output_contract_failed:normalize',phase='normalize',normalize_frozen=True).items():source.set(key,value)
        source.close()
        return work,source_id,identity,assets,empty

    def test_recovery_excludes_only_empty_row_without_recalling_or_resetting_other_jobs(self):
        work,source_id,identity,_,empty=self.checkpoint();path=work/source_id/'jobs.sqlite3';before=path.read_bytes()
        with patch('sys.stdout',new=io.StringIO()):report=recover_normalization(work,source_id,identity,repair='empty')
        self.assertEqual(path.read_bytes(),before)
        source=Jobs(work/source_id,readonly=True);target=Jobs(work/report['run_id'],readonly=True)
        self.addCleanup(source.close);self.addCleanup(target.close)
        for table in ('requests','usage','source_rows','rf2'):
            self.assertEqual([tuple(row) for row in source.db.execute('SELECT * FROM '+table)],
                [tuple(row) for row in target.db.execute('SELECT * FROM '+table)])
        for row in source.db.execute('SELECT * FROM jobs WHERE job_id!=?',(empty,)):
            self.assertEqual(tuple(row),tuple(target.db.execute('SELECT * FROM jobs WHERE job_id=?',(row['job_id'],)).fetchone()))
        self.assertEqual(target.get('recovery')['jobs_reset'],0)
        self.assertEqual(target.get('excluded:'+empty)['attempt_count'],6)
        self.assertEqual(report['model_calls_started'],0)
        self.assertEqual(report['jobs_pending'],1)
        self.assertFalse((target.directory/'recovery.json').exists())

    def test_recovery_rejects_nonempty_exhausted_input_and_unknown_outcome(self):
        work,source_id,identity,_,empty=self.checkpoint()
        source=Jobs(work/source_id)
        with source.db:source.db.execute('UPDATE jobs SET normalized_input=? WHERE job_id=?',
            (canonical(dict(blank(),name='Pain')),empty))
        source.close()
        with self.assertRaisesRegex(ValueError,'recovery_requires_empty_source_exhaustion_only'):
            recover_normalization(work,source_id,identity,repair='empty')
        source=Jobs(work/source_id)
        with source.db:source.db.execute('UPDATE jobs SET normalized_input=? WHERE job_id=?',(canonical(blank()),empty))
        source.request_state('empty-5','outcome_unknown',error='network');source.close()
        with self.assertRaisesRegex(ValueError,'recovery_requires_settled_requests'):
            recover_normalization(work,source_id,identity,repair='empty')

    def test_recovery_cli_never_constructs_model_client(self):
        work,source_id,_,assets,_=self.checkpoint()
        with patch('ontoward_extraction.build.Provider',side_effect=AssertionError('model client')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(['recover-normalize-empty','--work',str(work),'--assets',str(assets),
                '--config',str(ROOT/'config.json'),'--run-id',source_id]),0)
