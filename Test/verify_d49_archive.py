"""Run the unchanged SDK entrypoint against an internal protocol-only HTTP server."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def main():
    resources=prepare();knowledge=resources.knowledge
    target=next(p.target for group in knowledge._disease_profiles.values() for p in group
        if p.effect in {'support','strong_support'} and knowledge.has_type(p.target,'Symptom'))
    client=f.FakeSDK(target=knowledge.term(target),chat_handler=lambda packet:fixture_reply(knowledge,packet))
    client.session_id='00000000-0000-4000-8000-000000000001'
    client.deadline=datetime.now(timezone.utc)+timedelta(minutes=25)
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self): self.reply(client.session())
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append({'path':self.path,'body':body})
            if self.path=='/_nova/ready': result={'ready':True}
            elif self.path=='/v1/chat/completions': result=client.chat(body.pop('messages'),**body)
            elif body['action']=='DIAGNOSE': result=client.diagnose(note=body['note'],diagnosis=body['diagnosis'])
            elif body['action']=='EXAM': result=client.exam(body['content'],body['request_id'])
            else: result=client.say(body['content'],body['request_id'])
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
    guarded = os.environ.get('ONTOWARD_DENY_LANGGRAPH') == '1'
    if guarded:
        environment['PYTHONPATH'] = '/fixtures/Test/no_langgraph:/submission'
        probe = subprocess.run([sys.executable, '-B', '-c', 'import langgraph'], env=environment,
                               capture_output=True, text=True)
        assert probe.returncode != 0 and 'LangGraph is unavailable' in probe.stderr, probe.stderr
    try:
        result=subprocess.run([sys.executable,'-B','/submission/run.py'],cwd='/submission',env=environment,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        assert requests[0]['path']=='/_nova/ready'
        assert len(client.submissions)==1
        assert sum(len(section) for section in client.submissions[0]['note'].values())==15
        assert not client.submissions[0]['note']['O']['tests']
        report={'status':'pass','entrypoint':'run.py','transport':'original_sdk_http_loopback','receipt':'completed',
            'requests':len(requests),'actions':len(client.actions),'diagnosis':client.submissions[0]['diagnosis'],
            'network':'none','development_credentials':False,'actual_models':'not_run','clinical_accuracy':'not_run',
            'langgraph_import':'blocked' if guarded else 'not_checked'}
        Path('/output/sdk-http.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    finally: server.shutdown();server.server_close()


if __name__=='__main__': main()
