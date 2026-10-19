import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from nova_sdk import NovaError
from ontoward_extraction.__main__ import build_identity, configuration
from ontoward_extraction.build import run_phase
from ontoward_extraction.inputs import discover, index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.llm import Provider, ProviderError
from ontoward_extraction.models import canonical, digest, response_schema
from ontoward_extraction.recovery import recover_normalization
from support import inputs, nodes, ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


class ProviderRetryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.config=configuration(ROOT/'config.json')
        self.jobs=Jobs(self.root/'work');self.addCleanup(self.jobs.close)
        self.ident=self.jobs.add('normalize',{'fixture':True})

    def phase(self,provider):
        with patch('sys.stdout',new=io.StringIO()),patch('ontoward_extraction.build.wait_until'):
            with self.jobs.worker():run_phase(self.jobs,'normalize',self.config,provider)

    def test_sdk_classifies_only_explicit_server_response_failures_as_new_attempts(self):
        with patch.dict(os.environ,{'NOVA_DEV_KEY':'test-only'}):provider=Provider(self.config,self.root)
        for code,status,new_id,unknown in [('PROVIDER_RESPONSE_INVALID',503,True,False),
            ('PROVIDER_RESPONSE_INVALID',None,False,True),('API_UNAVAILABLE',None,False,True),
            ('PROVIDER_UNAVAILABLE',503,False,False),('PROVIDER_RESPONSE_INVALID',403,False,False)]:
            client=MagicMock();client.chat.side_effect=NovaError(code,status)
            with self.subTest(code=code,status=status),patch.dict(os.environ,{'NOVA_DEV_KEY':'test-only'}),patch('nova_sdk.Client',return_value=client):
                with self.assertRaises(ProviderError) as raised:provider.send(provider.payload('id',[],response_schema()))
                self.assertEqual(raised.exception.new_request,new_id)
                self.assertEqual(raised.exception.unknown,unknown)
                self.assertEqual(raised.exception.status,status)

    def test_explicit_failure_uses_fresh_id_same_payload_and_accepts_replacement_once(self):
        provider=ScriptedProvider();original=provider.send;sent=[]
        def send(payload):
            sent.append(copy.deepcopy(payload))
            if len(sent)==1:raise ProviderError('PROVIDER_RESPONSE_INVALID',retryable=True,new_request=True,status=503)
            return original(payload)
        provider.send=send;self.phase(provider)
        self.assertEqual(len(sent),2)
        self.assertNotEqual(sent[0]['request_id'],sent[1]['request_id'])
        self.assertEqual({key:value for key,value in sent[0].items() if key!='request_id'},
            {key:value for key,value in sent[1].items() if key!='request_id'})
        self.assertEqual(self.jobs.status()['requests'],{'accepted':1,'failed':1})
        self.assertEqual(self.jobs.status()['jobs'],{'done':1})
        self.assertEqual(self.jobs.status()['usage'][0]['calls'],1)
        self.assertEqual(self.jobs.db.execute('SELECT attempt_count FROM jobs').fetchone()[0],1)

    def test_uncertain_nova_response_reuses_original_request_id(self):
        provider=ScriptedProvider();original=provider.send;sent=[]
        def send(payload):
            sent.append(copy.deepcopy(payload))
            if len(sent)==1:raise ProviderError('API_UNAVAILABLE',unknown=True)
            return original(payload)
        provider.send=send;self.phase(provider)
        self.assertEqual(sent[0],sent[1])
        self.assertEqual(self.jobs.status()['requests'],{'accepted':1})
        self.assertEqual(self.jobs.status()['usage'][0]['calls'],1)

    def test_repeated_explicit_errors_stop_after_five_distinct_requests(self):
        provider=ScriptedProvider();sent=[]
        def send(payload):
            sent.append(payload['request_id'])
            raise ProviderError('PROVIDER_RESPONSE_INVALID',retryable=True,new_request=True,status=503)
        provider.send=send
        with self.assertRaisesRegex(RuntimeError,'persistent_provider_failure:PROVIDER_RESPONSE_INVALID'):self.phase(provider)
        self.assertEqual(len(set(sent)),5)
        self.assertEqual(self.jobs.status()['requests'],{'failed':5})
        self.assertEqual(self.jobs.status()['usage'],[])
        self.assertEqual(self.jobs.db.execute('SELECT attempt_count FROM jobs').fetchone()[0],1)

    def test_pause_after_confirmed_failure_starts_no_new_request(self):
        provider=ScriptedProvider();sent=[]
        def send(payload):
            sent.append(payload['request_id']);self.jobs.pause()
            raise ProviderError('PROVIDER_RESPONSE_INVALID',retryable=True,new_request=True,status=503)
        provider.send=send;self.phase(provider)
        self.assertEqual(len(sent),1)
        self.assertEqual(self.jobs.status()['requests'],{'failed':1})
        self.assertEqual(self.jobs.status()['state'],'paused')

    def test_legacy_prepared_failure_uses_new_id_and_accounts_actual_response(self):
        provider=ScriptedProvider();old=provider.payload('cached-error',[
            dict(role='system',content='fixture'),dict(role='user',content=canonical(dict(phase='normalize',jobs=[dict(job_id=self.ident,input={})])))],response_schema())
        self.jobs.prepare_request('cached-error','nova_dev',old,[self.ident])
        self.jobs.request_state('cached-error','prepared',error='PROVIDER_RESPONSE_INVALID')
        original=provider.send;sent=[]
        def send(payload):
            sent.append(payload['request_id'])
            if payload['request_id']=='cached-error':raise ProviderError('PROVIDER_RESPONSE_INVALID',retryable=True,new_request=True,status=503)
            return original(payload)
        provider.send=send;self.phase(provider)
        self.assertEqual(len(sent),2)
        self.assertEqual(self.jobs.status()['requests'],{'accepted':1,'failed':1})
        self.assertEqual(self.jobs.status()['usage'][0]['calls'],1)

    def test_provider_recovery_preserves_done_bytes_usage_and_attempts(self):
        assets=inputs(self.root/'assets');entries=discover(assets)
        identity=build_identity(entries,self.config,assets);previous=copy.deepcopy(identity)
        previous['generator']['llm.py']='legacy-response-invalid-retry'
        work=self.root/'recover';source_id=digest(previous)[:32]
        source=Jobs(work/source_id,previous)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        done=source.add('normalize',{'done':True});pending=source.add('normalize',{'pending':True})
        source.prepare_request('good','nova_dev',{},[done])
        source.request_state('good','received',dict(content='fixture'))
        result=dict(job_id=done,concepts=nodes(),relations=[],value_matches=[])
        source.accept('good',{done:result},{},dict(day='2026-10-19',model='openai/gpt-6-luna',input_tokens=3,output_tokens=4))
        source.prepare_request('bad','nova_dev',dict(model='openai/gpt-6-luna'),[pending])
        source.request_state('bad','prepared',error='PROVIDER_RESPONSE_INVALID')
        for key,value in dict(state='failed',phase='normalize',normalize_frozen=True,error='persistent_provider_failure:PROVIDER_RESPONSE_INVALID').items():source.set(key,value)
        source.close();before=(work/source_id/'jobs.sqlite3').read_bytes()
        with patch('sys.stdout',new=io.StringIO()):report=recover_normalization(work,source_id,identity,repair='provider')
        self.assertEqual((work/source_id/'jobs.sqlite3').read_bytes(),before)
        restored=Jobs(work/report['run_id']);self.addCleanup(restored.close)
        self.assertEqual(restored.status()['jobs'],{'done':1,'pending':1})
        self.assertEqual(restored.status()['requests'],{'accepted':1,'failed':1})
        self.assertEqual(restored.status()['usage'][0]['calls'],1)
        self.assertEqual(restored.db.execute('SELECT result FROM jobs WHERE job_id=?',(done,)).fetchone()[0],canonical(result))
        self.assertEqual(restored.db.execute('SELECT attempt_count FROM jobs WHERE job_id=?',(pending,)).fetchone()[0],1)
        self.assertEqual(restored.get('recovery')['confirmed_failed_request_ids'],['bad'])
