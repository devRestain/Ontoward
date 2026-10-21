import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity,configuration,main
from ontoward_extraction.inputs import discover,index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.llm import Provider
from ontoward_extraction.models import canonical,digest
from ontoward_extraction.recovery import recover_draft
from support import inputs,nodes


class ProviderSwitchTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        assets=inputs(self.root/'assets');entries=discover(assets)
        config=configuration(Path(__file__).resolve().parents[1]/'config.sol.json')
        self.old=build_identity(entries,config,assets);self.old['generator']['recovery.py']='previous'
        self.source_id=digest(self.old)[:32];self.work=self.root/'work'
        source=Jobs(self.work/self.source_id,self.old)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        for phase in ('normalize','questions'):
            ident=source.add(phase,dict(complete=True));source.prepare_request(phase,'nova_dev',{},[ident])
            source.request_state(phase,'received',dict(content='saved'))
            source.accept(phase,{ident:dict(job_id=ident,concepts=nodes(),relations=[],value_matches=[])},{},
                dict(day='2026-10-20',model='openai/gpt-6.1-sol',input_tokens=1,output_tokens=1))
        vocabulary=nodes()
        ident=source.add('draft',dict(disease=vocabulary[0],available_targets=vocabulary[1:],attributes_and_values=[]))
        source.prepare_request('rejected','nova_dev',dict(messages=[]),[ident])
        source.request_state('rejected','failed',error='INVALID_REQUEST_BODY')
        for key,value in dict(state='failed',phase='draft',error='INVALID_REQUEST_BODY',normalize_frozen=True,
            questions_frozen=True,draft_frozen=True).items():source.set(key,value)
        source.close()
        self.identity=build_identity(entries,configuration(Path(__file__).resolve().parents[1]/'config.api-luna.json'),assets)

    def test_explicit_api_and_subscription_copies_preserve_history_and_completed_bytes(self):
        path=self.work/self.source_id/'jobs.sqlite3';before=path.read_bytes()
        for provider in ('openai_api','codex_subscription'):
            identity=copy.deepcopy(self.identity);identity['config']['provider']=provider
            if provider=='codex_subscription':identity['config']['models']={'draft':'gpt-6.1-sol','final':'gpt-6.1-sol'}
            with patch('sys.stdout',new=io.StringIO()):report=recover_draft(self.work,self.source_id,identity,switch_provider=True)
            self.assertEqual(path.read_bytes(),before)
            old=Jobs(self.work/self.source_id,readonly=True);new=Jobs(self.work/report['run_id'],readonly=True)
            try:
                for table in ('jobs','requests','usage'):
                    left=[dict(r) for r in old.db.execute('SELECT * FROM '+table)]
                    right=[dict(r) for r in new.db.execute('SELECT * FROM '+table)]
                    for row in left:
                        if table=='jobs' and row['status']=='running':row['status']='pending'
                    self.assertEqual(left,right)
                self.assertEqual(new.get('identity'),identity)
                self.assertEqual(report['target_provider'],provider)
                self.assertEqual(report['model_calls_started'],0)
            finally:old.close();new.close()

    def test_switch_rejects_unknown_and_unrelated_clinical_configuration_changes(self):
        for key in ('batch_size','effort'):
            identity=copy.deepcopy(self.identity);identity['config'][key]=1 if key=='batch_size' else 'high'
            with self.assertRaisesRegex(ValueError,'explicit_provider_profile'):
                recover_draft(self.work,self.source_id,identity,switch_provider=True)
        identity=copy.deepcopy(self.identity);identity['prompts']['draft.txt']='changed'
        with self.assertRaisesRegex(ValueError,'unrelated_prompt_changed'):
            recover_draft(self.work,self.source_id,identity,switch_provider=True)
        identity=copy.deepcopy(self.identity);identity['generator']['build.py']='changed'
        with self.assertRaisesRegex(ValueError,'not_a_draft_packet_change'):
            recover_draft(self.work,self.source_id,identity,switch_provider=True)
        source=Jobs(self.work/self.source_id);source.request_state('rejected','outcome_unknown');source.close()
        with self.assertRaisesRegex(ValueError,'oversized_settled_request'):
            recover_draft(self.work,self.source_id,self.identity,switch_provider=True)

    def test_cli_requires_provider_before_discovery_or_copy(self):
        with patch('sys.stderr',new=io.StringIO()),patch('ontoward_extraction.__main__.discover') as discover_inputs:
            with self.assertRaises(SystemExit):main(['recover-draft-provider','--run-id',self.source_id])
            discover_inputs.assert_not_called()

    def test_api_profile_uses_luna_medium_for_draft_and_final_without_tools(self):
        import os
        from ontoward_extraction.build import phase_schema
        config=self.identity['config']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only-key'}):client=Provider(config,self.root)
        for phase in ('draft','final'):
            body=client.payload('fixture',[],phase_schema(phase),final=phase=='final')['body']
            self.assertEqual(body['model'],'gpt-6-luna')
            self.assertEqual(body['reasoning'],{'effort':'medium'})
            self.assertEqual(body['max_output_tokens'],32000)
            self.assertNotIn('tools',body)
            self.assertFalse(body['store'])
