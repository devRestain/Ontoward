import io
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ontoward_extraction.__main__ import configuration, main
from ontoward_extraction.build import run_phase, wait_until
from ontoward_extraction.jobs import Jobs, PauseRequested
from ontoward_extraction.llm import Provider, ProviderError
from ontoward_extraction.models import response_schema
from support import inputs, ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=configuration(ROOT/'config.json')

    def test_openai_completed_incomplete_refusal_and_usage(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only-key'}):
            client=Provider(dict(self.config,provider='openai_api'),self.root)
            payload=client.payload('local-correlation',[dict(role='user',content='fixture')],response_schema())
            for status,parts,expected in [('completed',[{'type':'output_text','text':'{}'}],'stop'),
                ('incomplete',[],'length'),('completed',[{'type':'refusal','refusal':'fixture'}],'refusal')]:
                raw=dict(status=status,output=[dict(content=parts)],usage=dict(input_tokens=3,output_tokens=4))
                opener=MagicMock();opener.open.return_value=io.BytesIO(json.dumps(raw).encode())
                with patch('urllib.request.build_opener',return_value=opener):
                    response=client.send(payload)
                self.assertEqual(response['finish_reason'],expected)
                self.assertEqual(response['usage']['output_tokens'],4)
                request=opener.open.call_args.args[0]
                self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
                self.assertNotIn('session_id',json.loads(request.data))

    def test_openai_disconnect_is_unknown_and_not_success(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only-key'}):
            client=Provider(dict(self.config,provider='openai_api'),self.root)
            opener=MagicMock();opener.open.side_effect=TimeoutError('fixture')
            with patch('urllib.request.build_opener',return_value=opener):
                with self.assertRaises(ProviderError) as raised:
                    client.send(client.payload('request',[],response_schema()))
            self.assertTrue(raised.exception.unknown)

    def test_nova_development_route_clears_inherited_session(self):
        with patch.dict(os.environ,{'NOVA_DEV_KEY':'test-only-nova','NOVA_SESSION_ID':'unwanted'}):
            client=Provider(self.config,self.root)
            mock=MagicMock();mock.chat.return_value={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':2,'completion_tokens':1}}
            with patch('nova_sdk.Client',return_value=mock) as constructor:
                result=client.send(client.payload('same-request',[],response_schema(),True))
            self.assertEqual(mock.session_id,'')
            self.assertTrue(constructor.call_args.kwargs['sample'])
            self.assertEqual(mock.chat.call_args.kwargs['request_id'],'same-request')
            self.assertNotIn('temperature',mock.chat.call_args.kwargs)
            self.assertEqual(result['usage']['input_tokens'],2)

    def test_codex_subprocess_receives_no_api_or_nova_credentials(self):
        client=Provider(dict(self.config,provider='codex_subscription'),self.root)
        payload=client.payload('cli-request',[],response_schema())
        directory=Path(payload['directory'])
        class Process:
            returncode=0
            def communicate(self,*args,**kwargs):
                (directory/'response.json').write_text('{"results":[]}')
                (directory/'events.jsonl').write_text('{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":1}}\n')
        status=MagicMock(returncode=0,stdout='Logged in using ChatGPT',stderr='')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','NOVA_DEV_KEY':'synthetic','CODEX_API_KEY':'synthetic'}):
            with patch('subprocess.run',return_value=status),patch('subprocess.Popen',return_value=Process()) as process:
                result=client.send(payload)
        self.assertFalse({'OPENAI_API_KEY','NOVA_DEV_KEY','CODEX_API_KEY'} & process.call_args.kwargs['env'].keys())
        self.assertTrue(process.call_args.kwargs['start_new_session'])
        self.assertEqual(result['finish_reason'],'stop')

    def test_cli_sigterm_saves_current_response_and_resumes_completed_jobs(self):
        assets=inputs(self.root/'assets');provider=ScriptedProvider(lambda:signal.raise_signal(signal.SIGTERM))
        args=['run','--config',str(ROOT/'config.json'),'--assets',str(assets),'--work',str(self.root/'runs'),
            '--output',str(self.root/'output')]
        with patch('ontoward_extraction.build.Provider',return_value=provider),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(args),0)
        run=next((self.root/'runs').iterdir());jobs=Jobs(run,readonly=True)
        self.assertEqual(jobs.status()['state'],'paused')
        completed={row[0] for row in jobs.db.execute("SELECT job_id FROM jobs WHERE status='done'")};jobs.close()
        with self.assertRaisesRegex(ValueError,'checkpoint_exists_use_resume'):
            main(args)
        provider.after_send=None;provider.calls.clear()
        with patch('ontoward_extraction.build.Provider',return_value=provider),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(args+['--resume']),0)
        self.assertFalse(completed.intersection(provider.calls))
        jobs=Jobs(run,readonly=True);self.assertEqual(jobs.status()['state'],'complete');jobs.close()

    def test_quota_wait_honors_pause_without_new_calls(self):
        jobs=Jobs(self.root/'quota',{'config':self.config})
        try:
            jobs.interrupted=True
            with self.assertRaises(PauseRequested): wait_until(jobs,99999999999)
            self.assertEqual(jobs.status()['requests'],{})
        finally: jobs.close()

    def test_repeated_invalid_output_stops_as_operational_failure(self):
        jobs=Jobs(self.root/'bad',{'config':self.config});job=jobs.add('normalize',{'value':'fixture'})
        provider=ScriptedProvider();provider.send=lambda payload:dict(content='{',finish_reason='stop',
            usage=dict(day='2026-10-19',model='luna',input_tokens=1,output_tokens=1))
        try:
            with self.assertRaisesRegex(RuntimeError,'output_contract_failed'):
                with jobs.worker(): run_phase(jobs,'normalize',self.config,provider)
            self.assertEqual(jobs.status()['jobs'],{'failed':1})
            self.assertEqual(jobs.status()['usage'][0]['calls'],6)
        finally: jobs.close()


if __name__=='__main__': unittest.main()
