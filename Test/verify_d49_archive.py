"""Run the unchanged SDK entrypoint against an internal protocol-only HTTP server."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

sys.path.insert(0,'/fixtures/Dev/tests/workflow')
sys.path.insert(0,'/submission')
import fixtures as f
from test_admitted import fixture_reply
from workflow.runtime import prepare


def main(observe=False):
    output = Path('/output')
    if observe and any(output.iterdir()):
        raise ValueError('Observed protocol verification requires a fresh output directory')
    resources=prepare();knowledge=resources.knowledge
    target=next(p.target for group in knowledge._disease_profiles.values() for p in group
        if p.effect in {'support','strong_support'} and knowledge.has_type(p.target,'Symptom'))
    client=f.FakeSDK(target=knowledge.term(target),chat_handler=lambda packet:fixture_reply(knowledge,packet))
    client.session_id='00000000-0000-4000-8000-000000000001'
    client.deadline=datetime.now(timezone.utc)+timedelta(minutes=25)
    requests, exchanges = [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self): self.reply(client.session())
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append({'path':self.path,'body':json.loads(json.dumps(body))})
            if self.path=='/_nova/ready': result={'ready':True}
            elif self.path=='/v1/chat/completions': result=client.chat(body.pop('messages'),**body)
            elif body['action']=='DIAGNOSE': result=client.diagnose(note=body['note'],diagnosis=body['diagnosis'])
            elif body['action']=='EXAM': result=client.exam(body['content'],body['request_id'])
            else: result=client.say(body['content'],body['request_id'])
            exchanges.append(dict(request=requests[-1], response=json.loads(json.dumps(result))))
            self.reply(result)
        def reply(self,result):
            raw=json.dumps(result,ensure_ascii=False).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    environment={key:value for key,value in os.environ.items() if key not in {'NOVA_DEV_KEY','OPENAI_API_KEY','CODEX_API_KEY'}}
    environment.update(NOVA_API_BASE=f'http://127.0.0.1:{server.server_port}',NOVA_RUN_TOKEN='synthetic-local-token',
        NOVA_SESSION_ID=client.session_id,PYTHONPATH='/submission')
    if observe:
        (output / 'agent').mkdir()
        environment['NOVA_OUTPUT_DIR'] = '/output/agent'
    guarded = os.environ.get('ONTOWARD_DENY_LANGGRAPH') == '1'
    if guarded:
        environment['PYTHONPATH'] = '/fixtures/Test/no_langgraph:/submission'
        probe = subprocess.run([sys.executable, '-B', '-c', 'import langgraph'], env=environment,
                               capture_output=True, text=True)
        assert probe.returncode != 0 and 'LangGraph is unavailable' in probe.stderr, probe.stderr
    try:
        entry = str(Path(__file__).with_name('observe.py')) if observe else '/submission/run.py'
        result=subprocess.run([sys.executable,'-B',entry],cwd='/submission',env=environment,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        assert requests[0]['path']=='/_nova/ready'
        assert len(client.submissions)==1
        assert sum(len(section) for section in client.submissions[0]['note'].values())==15
        assert not client.submissions[0]['note']['O']['tests']
        report={'status':'pass','entrypoint':'run.py','transport':'original_sdk_http_loopback','receipt':'completed',
            'requests':len(requests),'actions':len(client.actions),'diagnosis':client.submissions[0]['diagnosis'],
            'network':'none','development_credentials':False,'actual_models':'not_run','clinical_accuracy':'not_run',
            'langgraph_import':'blocked' if guarded else 'not_checked'}
        if observe:
            from viewer import render
            simulator = output / 'simulator'; simulator.mkdir(exist_ok=True)
            def save(path, value):
                path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            (output / 'agent/stdout.log').write_text(result.stdout)
            (output / 'agent/stderr.log').write_text(result.stderr)
            save(output / 'agent/process.json', dict(exit_code=result.returncode))
            save(output / 'run.json', dict(id=f'{__import__("settings").ALGORITHM_VERSION}-synthetic-observed',
                fixture_kind='protocol_fixture', backend='scripted'))
            save(output / 'result.json', dict(status='pass', backend='scripted', score_status='not_scored'))
            save(simulator / 'summary.json', dict(status='completed', receipt={'status':'completed'},
                backend='scripted', turns=len(client.actions), doctor_calls=len(client.requests), model_requests=len(client.requests)))
            save(simulator / 'record.json', client.submissions[0])
            save(simulator / 'requests.json', {row['request']['body']['request_id']:
                {**row['request'], 'response':row['response']} for row in exchanges if row['request']['body'].get('request_id')})
            save(simulator / 'transcript.json', dict(initial={'opening':client.target}, events=[
                dict(action=row['request']['body']['action'], content=row['request']['body'].get('content'),
                     request_id=row['request']['body'].get('request_id'), turn=row['response'].get('turn'), response=row['response'])
                for row in exchanges if row['request']['body'].get('action')]))
            rendered = render(output)
            assert rendered['trace']['status'] == 'complete', rendered['inspection']
            assert not [c for c in rendered['inspection']['checks'] if c['status'] == 'fail'], rendered['inspection']
            report['trace_status'] = rendered['trace']['status']
            report['inspection_status'] = rendered['inspection']['status']
        (output / 'sdk-http.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    finally: server.shutdown();server.server_close()


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--observe', action='store_true', help='Record current Test call boundaries and render a protocol report')
    main(parser.parse_args().observe)
