import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import configuration
from ontoward_extraction.build import run_pipeline, run_phase, accept_response
from ontoward_extraction.compile import compile_bundle
from ontoward_extraction.inputs import discover, index, source_records
from ontoward_extraction.install import install
from ontoward_extraction.jobs import Jobs, PauseRequested, OutcomeUnknown
from ontoward_extraction.llm import Provider, ProviderError
from ontoward_extraction.models import canonical, digest, response_schema
from ontoward_extraction.verify import verify
from knowledge.graph import ClinicalKnowledge
from support import nodes, relation, inputs, ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.config=configuration(ROOT/'config.json')
        self.jobs=Jobs(self.root/'work',{'config':self.config});self.addCleanup(self.jobs.close)

    def test_compile_without_old_policy_sources_and_keep_neutral_done_only(self):
        report=compile_bundle(self.root/'bundle','fixture',nodes(),[relation(),relation('neutral',status='absent')])
        self.assertEqual(report['effects']['neutral'],1)
        self.assertEqual(len(ClinicalKnowledge.load(self.root/'bundle/manifest.json').get_disease_patterns(
            next(iter(ClinicalKnowledge.load(self.root/'bundle/manifest.json')._disease_profiles)))),1)
        self.assertEqual({p.name for p in (self.root/'bundle').iterdir()},
            {'schema.ttl','vocabulary.ttl','clinical.ttl','questions.ko.json','guideline-index.json','manifest.json'})
        self.assertEqual(verify(self.root/'bundle/manifest.json')['status'],'pass')

    def test_manifest_escape_digest_and_legacy_contract_are_rejected(self):
        compile_bundle(self.root/'bundle','fixture',nodes(),[relation()])
        path=self.root/'bundle/manifest.json';original=json.loads(path.read_text())
        for mutation in ('escape','digest','legacy'):
            data=copy.deepcopy(original)
            if mutation=='escape': data['clinical']['path']='../clinical.ttl'
            elif mutation=='digest': data['clinical']['sha256']='0'*64
            else: data['knowledge_contract']='old'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): ClinicalKnowledge.load(path)

    def test_discover_and_index_all_four_inputs_without_old_database(self):
        root=inputs(self.root/'assets');entries=discover(root)
        index(self.jobs,entries,1)
        self.assertTrue(self.jobs.db.execute('SELECT COUNT(*) FROM rf2').fetchone()[0])
        row=source_records(self.jobs,'astra')[0]
        self.assertNotIn('prior_policy',row);self.assertNotIn('snapshot',row)
        self.assertEqual(len({entry['role'] for entry in entries}),12)

    def test_index_pause_restores_committed_cursor_and_done_files(self):
        entries=discover(inputs(self.root/'assets'))
        calls=[0]
        def boundary():
            calls[0]+=1
            if calls[0]==2: raise PauseRequested()
        with patch.object(self.jobs,'boundary',side_effect=boundary):
            with self.assertRaises(PauseRequested): index(self.jobs,entries,1)
        before=self.jobs.db.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0]
        index(self.jobs,entries,1)
        after=self.jobs.db.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0]
        index(self.jobs,entries,1)
        self.assertEqual(after,self.jobs.db.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0])
        self.assertGreaterEqual(after,before)

    def test_end_to_end_fixture_pause_resume_never_recalls_done_jobs(self):
        entries=discover(inputs(self.root/'assets'));provider=ScriptedProvider(self.jobs.pause)
        with self.jobs.worker(): run_pipeline(self.jobs,entries,self.config,self.root/'output',provider=provider)
        self.assertEqual(self.jobs.get('state'),'paused')
        done={row[0] for row in self.jobs.db.execute("SELECT job_id FROM jobs WHERE status='done'")}
        provider.after_send=None;provider.calls.clear()
        with self.jobs.worker(): run_pipeline(self.jobs,entries,self.config,self.root/'output',provider=provider)
        self.assertEqual(self.jobs.get('state'),'complete')
        self.assertFalse(done.intersection(provider.calls))
        self.assertEqual(verify(self.root/'output/work/manifest.json')['status'],'pass')

    def test_single_worker_lock_and_keyless_pause_status(self):
        other=Jobs(self.root/'work');self.addCleanup(other.close)
        with self.jobs.worker():
            with self.assertRaisesRegex(RuntimeError,'worker_already_running'):
                with other.worker(): pass
            other.pause()
            with self.assertRaises(PauseRequested): self.jobs.boundary()
        self.assertEqual(other.status()['state'],'pausing')

    def test_provider_change_rejects_same_checkpoint(self):
        with self.assertRaisesRegex(ValueError,'checkpoint_fingerprint_mismatch'):
            Jobs(self.root/'work',{'config':dict(self.config,provider='openai_api')})

    def test_unknown_openai_request_requires_explicit_retry(self):
        job=self.jobs.add('normalize',{'value':'x'})
        self.jobs.prepare_request('interrupted','openai_api',{},[job]);self.jobs.request_state('interrupted','sent')
        provider=ScriptedProvider();provider.name='openai_api'
        with self.assertRaises(OutcomeUnknown): run_phase(self.jobs,'normalize',self.config,provider)
        self.assertEqual(provider.calls,[])
        run_phase(self.jobs,'normalize',self.config,provider,retry_unknown=True)
        self.assertEqual(self.jobs.status()['jobs'],{'done':1})
        self.assertEqual(self.jobs.status()['requests']['superseded'],1)

    def test_received_response_recovers_without_second_call_and_counts_success_once(self):
        job=self.jobs.add('normalize',{'value':'x'})
        self.jobs.prepare_request('received','nova_dev',{},[job])
        response=dict(content=json.dumps({'results':[dict(job_id=job,concepts=nodes(),relations=[],value_matches=[])]}),
            finish_reason='stop',usage=dict(day='2026-10-19',model='luna',input_tokens=1,output_tokens=2))
        self.jobs.request_state('received','received',response)
        provider=ScriptedProvider();run_phase(self.jobs,'normalize',self.config,provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(self.jobs.status()['usage'][0]['calls'],1)

    def test_pause_after_request_preparation_sends_nothing_then_resumes_once(self):
        self.jobs.add('normalize',{'value':'fixture'});provider=ScriptedProvider()
        original=self.jobs.prepare_request
        def prepare(*args):
            original(*args);self.jobs.interrupted=True
        with patch.object(self.jobs,'prepare_request',side_effect=prepare):
            with self.jobs.worker(): run_phase(self.jobs,'normalize',self.config,provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(self.jobs.status()['requests'],{'prepared':1})
        self.jobs.interrupted=False
        with self.jobs.worker(): run_phase(self.jobs,'normalize',self.config,provider)
        self.assertEqual(len(provider.calls),1)

    def test_partial_response_commits_valid_rows_and_retries_missing_only(self):
        ids=[self.jobs.add('normalize',{'value':x}) for x in ('one','two')]
        self.jobs.prepare_request('partial','nova_dev',{},ids)
        request=self.jobs.db.execute('SELECT * FROM requests WHERE request_id=?',('partial',)).fetchone()
        response=dict(content=json.dumps({'results':[dict(job_id=ids[0],concepts=nodes(),relations=[],value_matches=[])]}),finish_reason='stop')
        accept_response(self.jobs,request,response)
        self.assertEqual([row['job_id'] for row in self.jobs.pending('normalize')],[ids[1]])

    def test_atomic_install_pause_and_interruption_never_mix_bundles(self):
        for name in ('old','new'): compile_bundle(self.root/name,name,nodes(),[relation()])
        target=self.root/'target';install(self.root/'old/manifest.json',target)
        original=(target/'manifest.json').read_bytes()
        def pause(): raise PauseRequested()
        with self.assertRaises(PauseRequested): install(self.root/'new/manifest.json',target,pause)
        self.assertEqual(original,(target/'manifest.json').read_bytes())
        def interrupted(): raise RuntimeError('forced_boundary')
        with self.assertRaises(RuntimeError): install(self.root/'new/manifest.json',target,after_replace=interrupted)
        self.assertEqual(json.loads((target/'manifest.json').read_text())['build_id'],'new')
        self.assertEqual(verify(target/'manifest.json')['status'],'pass')
        install(self.root/'new/manifest.json',target)
        self.assertFalse((target/'builds/old').exists())

    def test_recompile_same_checkpoint_produces_identical_install_bytes(self):
        for name in ('one','two'):
            compile_bundle(self.root/name,'same',nodes(),[relation()])
        self.assertEqual({p.name:p.read_bytes() for p in (self.root/'one').iterdir()},
            {p.name:p.read_bytes() for p in (self.root/'two').iterdir()})
        install(self.root/'one/manifest.json',self.root/'target')
        install(self.root/'two/manifest.json',self.root/'target')

    def test_final_acceptance_keeps_draft_concepts_when_not_repeated(self):
        material=nodes();self.jobs.set('vocabulary',material)
        job=self.jobs.add('final',{'proposed_concepts':material,'concepts':material})
        self.jobs.prepare_request('final','nova_dev',{},[job])
        request=self.jobs.db.execute("SELECT * FROM requests WHERE request_id='final'").fetchone()
        response=dict(content=canonical({'results':[dict(job_id=job,concepts=[],relations=[relation()],value_matches=[])]}),finish_reason='stop')
        self.assertEqual(accept_response(self.jobs,request,response),{})
        self.assertEqual(len(self.jobs.results('final')[0]['concepts']),len(material))

    def test_pause_at_compile_and_manifest_commit_recovers_without_model_recall(self):
        entries=discover(inputs(self.root/'assets'));provider=ScriptedProvider()
        original=compile_bundle
        def compile_and_pause(*args,**kwargs):
            result=original(*args,**kwargs);self.jobs.pause();return result
        with patch('ontoward_extraction.build.compile_bundle',side_effect=compile_and_pause):
            with self.jobs.worker(): run_pipeline(self.jobs,entries,self.config,self.root/'output',provider=provider)
        self.assertEqual(self.jobs.get('state'),'paused');provider.calls.clear()
        real_install=install
        def install_and_pause(manifest,target,boundary):
            return real_install(manifest,target,boundary,after_replace=self.jobs.pause)
        with patch('ontoward_extraction.build.install',side_effect=install_and_pause):
            with self.jobs.worker(): run_pipeline(self.jobs,entries,self.config,self.root/'output',self.root/'target',provider=provider)
        self.assertEqual(self.jobs.get('state'),'paused')
        self.assertEqual(verify(self.root/'target/manifest.json')['status'],'pass')
        with self.jobs.worker(): run_pipeline(self.jobs,entries,self.config,self.root/'output',self.root/'target',provider=provider)
        self.assertEqual(self.jobs.get('state'),'complete');self.assertEqual(provider.calls,[])

    def test_pause_immediately_before_manifest_swap_keeps_old_manifest(self):
        for name in ('old','new'): compile_bundle(self.root/name,name,nodes(),[relation()])
        target=self.root/'target';install(self.root/'old/manifest.json',target)
        before=(target/'manifest.json').read_bytes();calls=[0]
        def boundary():
            calls[0]+=1
            if calls[0]==6: raise PauseRequested()
        with self.assertRaises(PauseRequested): install(self.root/'new/manifest.json',target,boundary)
        self.assertEqual((target/'manifest.json').read_bytes(),before)
        install(self.root/'new/manifest.json',target)
        self.assertEqual(verify(target/'manifest.json')['status'],'pass')

    def test_three_payloads_keep_models_medium_and_authentication_separate(self):
        with patch.dict(os.environ,{'NOVA_DEV_KEY':'synthetic-nova','OPENAI_API_KEY':'synthetic-openai'}):
            for name in ('nova_dev','openai_api','codex_subscription'):
                client=Provider(dict(self.config,provider=name),self.root)
                payload=client.payload('request',[dict(role='user',content='fixture')],response_schema(),True)
                self.assertNotIn('synthetic',canonical(payload))
                if name=='nova_dev':
                    self.assertEqual(payload['reasoning_effort'],'medium');self.assertEqual(payload['max_tokens'],32000)
                elif name=='openai_api':
                    self.assertEqual(payload['body']['reasoning']['effort'],'medium');self.assertFalse(payload['body']['store'])
                else:
                    self.assertIn('features.shell_tool=false',payload['argv']);self.assertIn('agents.enabled=false',payload['argv'])
                    self.assertEqual(payload['output_limit_enforcement'],'unavailable')


if __name__=='__main__': unittest.main()
