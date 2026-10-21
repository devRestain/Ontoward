import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity, configuration, main
from ontoward_extraction.build import accept_response, phase_schema, question_input, run_phase, transmit
from ontoward_extraction.inputs import discover, index
from ontoward_extraction.jobs import Jobs, PauseRequested
from ontoward_extraction.llm import Provider, kst_day
from ontoward_extraction.models import canonical, digest
from ontoward_extraction.recovery import recover_questions
from support import inputs, nodes, ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


class QuestionOutputTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.config=configuration(ROOT/'config.json')

    def test_compact_questions_preserve_large_registered_clinical_fields(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        node=nodes()[1];node['aliases']=['Alias '+str(i) for i in range(300)]
        ids=[jobs.add('questions',dict(concept=copy.deepcopy(node),linked_concepts=[],number=i)) for i in range(10)]
        provider=ScriptedProvider();send=provider.send;wire=[]
        def respond(payload):
            inputs=json.loads(payload['messages'][-1]['content'])['jobs']
            self.assertEqual(len(inputs),10)
            self.assertNotIn('aliases',inputs[0]['input']['concept'])
            response=send(payload);wire.append(response['content']);return response
        provider.send=respond
        with patch('sys.stdout',new=io.StringIO()):run_phase(jobs,'questions',self.config,provider)
        self.assertEqual(set(provider.calls),set(ids))
        self.assertNotIn('Alias 299',wire[0])
        for result in jobs.results('questions'):
            restored=result['concepts'][0]
            for field in ('id','kind','name','korean','aliases','attributes','values','systems'):
                self.assertEqual(restored[field],node[field])
        schema=phase_schema('questions')['$defs']
        self.assertNotIn('aliases',schema['Concept']['properties'])
        self.assertIn('aliases',schema['NewConcept']['properties'])

    def test_question_input_preserves_labels_roles_values_units_and_method_without_mutation(self):
        node=nodes()[1];linked=nodes()[-1]
        linked['aliases']=['search alias'];linked['attributes']=['unrelated nested taxonomy']
        linked['values']=['nested value'];linked['systems']=['nested system']
        source=dict(concept=node,linked_concepts=[linked]);before=copy.deepcopy(source)
        projected=question_input(source)
        self.assertEqual(source,before)
        self.assertEqual(projected['concept'],{k:v for k,v in node.items() if k!='aliases'})
        self.assertEqual(projected['linked_concepts'],[{k:v for k,v in linked.items() if k not in {'aliases','attributes','values','systems'}}])

    def test_sol_input_repair_preserves_failed_attempt_and_requires_changed_input_builder(self):
        work,luna_id,_,assets,pending=self.checkpoint()
        identity=build_identity(discover(assets),configuration(ROOT/'config.sol.json'),assets)
        previous=copy.deepcopy(identity);previous['generator']['build.py']='unprojected-question-input'
        source_id=digest(previous)[:32]
        (work/luna_id).rename(work/source_id)
        source=Jobs(work/source_id)
        source.set('identity',previous)
        source.prepare_request('body','nova_dev',dict(model='openai/gpt-6.1-sol',max_tokens=32000),[pending])
        source.request_state('body','failed',error='INVALID_REQUEST_BODY')
        source.set('state','failed');source.set('error','INVALID_REQUEST_BODY');source.close()
        before=(work/source_id/'jobs.sqlite3').read_bytes()
        unchanged=copy.deepcopy(previous);unchanged['generator']['recovery.py']='different recovery only'
        with self.assertRaisesRegex(ValueError,'recovery_requires_luna_source'):
            recover_questions(work,source_id,unchanged,switch_sol=True)
        with patch('sys.stdout',new=io.StringIO()):report=recover_questions(work,source_id,identity,switch_sol=True)
        self.assertEqual(report['reason'],'compact_sol_question_input_preserve_fixed_batch')
        self.assertEqual((work/source_id/'jobs.sqlite3').read_bytes(),before)
        old=Jobs(work/source_id,readonly=True);new=Jobs(work/report['run_id'],readonly=True)
        try:
            for table in ('requests','usage'):
                self.assertEqual([tuple(r) for r in old.db.execute('SELECT * FROM '+table)],
                    [tuple(r) for r in new.db.execute('SELECT * FROM '+table)])
            left=dict(old.db.execute('SELECT * FROM jobs WHERE job_id=?',(pending,)).fetchone())
            right=dict(new.db.execute('SELECT * FROM jobs WHERE job_id=?',(pending,)).fetchone())
            self.assertEqual(dict(left,status='pending'),right)
        finally:old.close();new.close()

    def test_question_patch_rejects_identifier_clinical_field_and_method_changes(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        node=nodes()[1]
        for number,mutate in enumerate([lambda p:p.update(id='different'),lambda p:p.update(aliases=[]),lambda p:p.update(exam_method=[]) ]):
            ident=jobs.add('questions',dict(concept=node,linked_concepts=[],number=number))
            action={key:node[key] for key in ('id','question','exam_text','attribute_role','exam_method')};mutate(action)
            request_id='r'+str(number);jobs.prepare_request(request_id,'nova_dev',{},[ident])
            request=jobs.db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            invalid=accept_response(jobs,request,dict(finish_reason='stop',content=canonical(dict(results=[
                dict(job_id=ident,concepts=[action],new_concepts=[],relations=[],value_matches=[])]))))
            self.assertIn(ident,invalid)

    def test_missing_exam_method_can_be_completed_without_mutating_finding(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        finding=nodes()[-2];finding['exam_method']=None;method=nodes()[-1]
        ident=jobs.add('questions',dict(concept=finding,linked_concepts=[]))
        action={key:finding[key] for key in ('id','question','exam_text','attribute_role','exam_method')};action['exam_method']=method['id']
        jobs.prepare_request('r','nova_dev',{},[ident]);request=jobs.db.execute('SELECT * FROM requests').fetchone()
        invalid=accept_response(jobs,request,dict(finish_reason='stop',content=canonical(dict(results=[
            dict(job_id=ident,concepts=[action],new_concepts=[method],relations=[],value_matches=[])]))))
        self.assertEqual(invalid,{})
        self.assertEqual(jobs.results('questions')[0]['concepts'][0]['name'],finding['name'])

    def checkpoint(self):
        assets=inputs(self.root/'assets');entries=discover(assets)
        identity=build_identity(entries,self.config,assets);previous=copy.deepcopy(identity)
        previous['generator']['build.py']='full-question-output';previous['prompts']['questions.txt']='full-concept-prompt'
        work=self.root/'recover';source_id=digest(previous)[:32];source=Jobs(work/source_id,previous)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        for phase in ('normalize','questions'):
            ident=source.add(phase,dict(completed=True))
            source.prepare_request(phase,'nova_dev',{},[ident]);source.request_state(phase,'received',dict(content='saved'))
            source.accept(phase,{ident:dict(job_id=ident,concepts=nodes(),relations=[],value_matches=[])},{},
                dict(day='2026-10-20',model='openai/gpt-6-luna',input_tokens=1,output_tokens=2))
        pending=source.add('questions',dict(concept=nodes()[1],linked_concepts=[]))
        source.prepare_request('length','nova_dev',{},[pending]);source.request_state('length','received',dict(finish_reason='length',content='{"results":['))
        source.accept('length',{}, {pending:'invalid_json:truncated'},dict(day='2026-10-20',model='openai/gpt-6-luna',input_tokens=1,output_tokens=8000))
        for key,value in dict(state='paused',phase='questions',normalize_frozen=True,questions_frozen=True).items():source.set(key,value)
        source.close();return work,source_id,identity,assets,pending

    def test_luna_recovery_and_explicit_sol_switch_preserve_results_requests_and_counters(self):
        work,source_id,luna,assets,_=self.checkpoint();source_path=work/source_id/'jobs.sqlite3';before=source_path.read_bytes()
        sol=build_identity(discover(assets),configuration(ROOT/'config.sol.json'),assets)
        for identity,switch in [(luna,False),(sol,True)]:
            with patch('sys.stdout',new=io.StringIO()):report=recover_questions(work,source_id,identity,switch_sol=switch)
            self.assertEqual(source_path.read_bytes(),before)
            old=Jobs(work/source_id,readonly=True);new=Jobs(work/report['run_id'],readonly=True)
            try:
                for table in ('jobs','requests','usage','rf2','source_rows'):
                    self.assertEqual([tuple(r) for r in old.db.execute('SELECT * FROM '+table)],
                        [tuple(r) for r in new.db.execute('SELECT * FROM '+table)])
                self.assertEqual(report['model_calls_started'],0)
                self.assertEqual(report['counters_reset'],0)
                self.assertFalse((new.directory/'recovery.json').exists())
            finally:old.close();new.close()

    def test_recovery_refuses_unknown_results_and_unrelated_contract_changes(self):
        work,source_id,identity,_,_=self.checkpoint()
        for field,name in [('inputs',None),('prompts','final.txt'),('generator','models.py'),('runtime_contract','graph.py')]:
            changed=copy.deepcopy(identity)
            if field=='inputs':changed[field][0]['sha256']='changed'
            else:changed[field][name]='changed'
            with self.assertRaises(ValueError):recover_questions(work,source_id,changed)
        source=Jobs(work/source_id);source.request_state('length','outcome_unknown',error='network');source.close()
        with self.assertRaisesRegex(ValueError,'recovery_requires_settled_requests'):recover_questions(work,source_id,identity)

    def test_sol_profile_has_medium_32k_and_one_shared_100_call_quota(self):
        config=configuration(ROOT/'config.sol.json');self.assertEqual(config['batch_size'],40)
        with patch.dict(os.environ,{'NOVA_DEV_KEY':'test-only'}):provider=Provider(config,self.root)
        for final in (False,True):
            payload=provider.payload('r',[],phase_schema('questions'),final)
            self.assertEqual((payload['model'],payload['reasoning_effort'],payload['max_tokens']),('openai/gpt-6.1-sol','medium',32000))
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        with jobs.db:jobs.db.execute('INSERT INTO usage VALUES(?,?,?,?,?)',(kst_day(),'openai/gpt-6.1-sol',100,1,1))
        with patch('ontoward_extraction.build.wait_until',side_effect=PauseRequested),patch.object(provider,'send') as send:
            with self.assertRaises(PauseRequested):transmit(jobs,provider,'r',payload,config)
            send.assert_not_called()

    def test_explicit_sol_switch_accepts_settled_healthy_pause(self):
        work,source_id,_,assets,_=self.checkpoint()
        source=Jobs(work/source_id)
        response=json.loads(source.db.execute("SELECT response FROM requests WHERE request_id='length'").fetchone()[0])
        response['finish_reason']='stop';source.request_state('length','accepted',response);source.close()
        identity=build_identity(discover(assets),configuration(ROOT/'config.sol.json'),assets)
        with patch('sys.stdout',new=io.StringIO()):report=recover_questions(work,source_id,identity,switch_sol=True)
        self.assertEqual(report['model_calls_started'],0)

    def test_context_limit_requires_explicit_sol_and_preserves_failed_request(self):
        work,source_id,luna,assets,pending=self.checkpoint()
        source=Jobs(work/source_id)
        source.prepare_request('context','nova_dev',dict(model='openai/gpt-6-luna',messages=['original']),[pending])
        source.request_state('context','failed',error='CONTEXT_LIMIT_EXCEEDED')
        source.set('state','failed');source.set('error','CONTEXT_LIMIT_EXCEEDED');source.close()
        path=work/source_id/'jobs.sqlite3';before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'recovery_requires_settled_requests'):
            recover_questions(work,source_id,luna)
        sol=build_identity(discover(assets),configuration(ROOT/'config.sol.json'),assets)
        with patch('sys.stdout',new=io.StringIO()):report=recover_questions(work,source_id,sol,switch_sol=True)
        self.assertEqual(path.read_bytes(),before)
        old=Jobs(work/source_id,readonly=True);new=Jobs(work/report['run_id'],readonly=True)
        try:
            for table in ('requests','usage'):
                self.assertEqual([tuple(r) for r in old.db.execute('SELECT * FROM '+table)],
                    [tuple(r) for r in new.db.execute('SELECT * FROM '+table)])
            a=dict(old.db.execute('SELECT * FROM jobs WHERE job_id=?',(pending,)).fetchone())
            b=dict(new.db.execute('SELECT * FROM jobs WHERE job_id=?',(pending,)).fetchone())
            self.assertEqual(a['status'],'running');self.assertEqual(b['status'],'pending')
            self.assertEqual(dict(a,status='pending'),b)
            self.assertEqual(report['counters_reset'],0)
            self.assertEqual(report['model_calls_started'],0)
        finally:old.close();new.close()

    def test_context_switch_rejects_unknown_request_and_unrelated_failure(self):
        work,source_id,_,assets,pending=self.checkpoint()
        source=Jobs(work/source_id)
        source.prepare_request('context','nova_dev',{},[pending])
        source.request_state('context','outcome_unknown',error='CONTEXT_LIMIT_EXCEEDED')
        source.set('state','failed');source.set('error','CONTEXT_LIMIT_EXCEEDED');source.close()
        sol=build_identity(discover(assets),configuration(ROOT/'config.sol.json'),assets)
        with self.assertRaisesRegex(ValueError,'recovery_requires_settled_requests'):
            recover_questions(work,source_id,sol,switch_sol=True)
        source=Jobs(work/source_id)
        source.request_state('context','failed',error='CONTEXT_LIMIT_EXCEEDED')
        source.set('error','authentication_failed');source.close()
        with self.assertRaisesRegex(ValueError,'recovery_requires_failed_or_truncated_luna_questions'):
            recover_questions(work,source_id,sol,switch_sol=True)

    def test_both_recovery_cli_routes_are_keyless(self):
        work,source_id,_,assets,_=self.checkpoint()
        for command,config in [('recover-questions','config.json'),('recover-questions-sol','config.sol.json')]:
            with patch('ontoward_extraction.build.Provider',side_effect=AssertionError('model client')),patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(main([command,'--work',str(work),'--assets',str(assets),'--config',str(ROOT/config),'--run-id',source_id]),0)
