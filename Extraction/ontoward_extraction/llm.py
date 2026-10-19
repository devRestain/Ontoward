import json
import os
import subprocess
import signal
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import canonical


class ProviderError(RuntimeError):
    def __init__(self, code, *, retry_at=None, retryable=False, unknown=False):
        super().__init__(code)
        self.retry_at, self.retryable, self.unknown = retry_at, retryable, unknown


def kst_day():
    return datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()


class Provider:
    def __init__(self, config, directory):
        self.config, self.directory = config, Path(directory)
        self.name = config['provider']
        self.timeout = config['timeout_seconds']
        if self.name == 'nova_dev' and not os.environ.get('NOVA_DEV_KEY'):
            raise ProviderError('missing_NOVA_DEV_KEY')
        if self.name == 'openai_api' and not os.environ.get('OPENAI_API_KEY'):
            raise ProviderError('missing_OPENAI_API_KEY')

    def payload(self, request_id, messages, schema, final=False):
        model = self.config['models']['final' if final else 'draft']
        maximum = self.config['max_tokens']['final' if final else 'draft']
        if self.name == 'nova_dev':
            return dict(request_id=request_id,messages=messages,model='openai/'+model,
                reasoning_effort=self.config['effort'],max_tokens=maximum)
        if self.name == 'openai_api':
            return {'request_id':request_id,'body':dict(model=model,input=messages,
                reasoning={'effort':self.config['effort']},max_output_tokens=maximum,store=False,
                text={'format':dict(type='json_schema',name='extraction_batch',strict=True,schema=schema)})}
        request_dir = self.directory / 'requests' / request_id
        return dict(request_id=request_id,model=model,messages=messages,schema=schema,
            directory=str(request_dir),effort=self.config['effort'],output_limit_enforcement='unavailable',
            argv=['codex','exec','--ephemeral','--ignore-user-config','--skip-git-repo-check',
                '--sandbox','read-only','--json','--color','never','--model',model,
                '-c','forced_login_method="chatgpt"','-c','cli_auth_credentials_store="file"',
                '-c','approval_policy="never"','-c','web_search="disabled"','-c','features.shell_tool=false',
                '-c','agents.enabled=false','-c','model_provider="openai"',
                '-c','model_providers.openai.request_max_retries=0','-c','model_providers.openai.stream_max_retries=0',
                '-c','model_reasoning_effort="'+self.config['effort']+'"',
                '--cd',str(request_dir),'--output-schema',str(request_dir/'schema.json'),
                '--output-last-message',str(request_dir/'response.json'),'-'])

    def send(self, payload):
        if self.name == 'nova_dev':
            from nova_sdk import Client, NovaError
            client = Client(api_base=self.config.get('api_base','https://nova.snubhai.org'),
                token=os.environ['NOVA_DEV_KEY'],sample=True,timeout=self.timeout)
            client.session_id = ''
            try:
                raw = client.chat(**payload)
            except NovaError as error:
                code = str(error)
                if error.status == 429 and any(word in code.upper() for word in ('DAILY','QUOTA')):
                    raise ProviderError('nova_daily_quota',retry_at=next_kst_day()) from error
                raise ProviderError(code,retryable=error.status is not None and (error.status>=500 or error.status==429),
                    unknown=error.status is None) from error
            choices = raw.get('choices',[])
            if not choices:
                return self.result('',payload['model'],raw.get('usage',{}),'invalid',raw)
            choice=choices[0]
            return self.result(choice.get('message',{}).get('content',''),payload['model'],raw.get('usage',{}),choice.get('finish_reason','invalid'),raw)
        if self.name == 'openai_api':
            request=urllib.request.Request('https://api.openai.com/v1/responses',data=canonical(payload['body']).encode(),
                headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'],'Content-Type':'application/json',
                    'X-Client-Request-Id':payload['request_id']},method='POST')
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=self.timeout) as response:
                    raw=json.load(response)
            except urllib.error.HTTPError as error:
                try:
                    code=json.loads(error.read()).get('error',{}).get('code') or 'http_'+str(error.code)
                except (ValueError,AttributeError):
                    code='http_'+str(error.code)
                delay=error.headers.get('Retry-After','')
                retry_at=None
                if delay.isdigit():
                    import time
                    retry_at=time.time()+int(delay)
                raise ProviderError(code,retry_at=retry_at,retryable=error.code==429 and code!='insufficient_quota') from error
            except (OSError,ValueError) as error:
                raise ProviderError('openai_outcome_unknown',unknown=True) from error
            texts=[]
            refused=False
            for item in raw.get('output',[]):
                for part in item.get('content',[]):
                    if part.get('type')=='refusal': refused=True
                    elif part.get('type')=='output_text': texts.append(part['text'])
            return self.result(''.join(texts),payload['body']['model'],raw.get('usage',{}),
                'refusal' if refused else 'stop' if raw.get('status')=='completed' else 'length' if raw.get('status')=='incomplete' else 'invalid',raw)
        directory=Path(payload['directory']); directory.mkdir(parents=True,exist_ok=True)
        response=directory/'response.json'
        if response.is_file():
            return self.cached(payload)
        (directory/'schema.json').write_text(canonical(payload['schema']))
        environment={key:value for key,value in os.environ.items() if key in {'PATH','LANG','LC_ALL','CODEX_HOME','HOME'}}
        try:
            status=subprocess.run(['codex','-c','cli_auth_credentials_store="file"','login','status'],
                capture_output=True,text=True,timeout=15,env=environment)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise ProviderError('codex_unavailable') from error
        if status.returncode or 'chatgpt' not in (status.stdout+status.stderr).casefold():
            raise ProviderError('codex_subscription_login_required')
        with (directory/'events.jsonl').open('w') as events, (directory/'stderr.log').open('w') as errors:
            try:
                process=subprocess.Popen(payload['argv'],stdin=subprocess.PIPE,stdout=events,stderr=errors,
                    text=True,env=environment,start_new_session=True)
                try:
                    process.communicate(canonical(payload['messages']),timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL); process.wait()
                    raise ProviderError('codex_outcome_unknown',unknown=True)
            except OSError as error:
                raise ProviderError('codex_unavailable') from error
        if process.returncode or not response.is_file():
            raise ProviderError('codex_failed_or_unknown',unknown=True)
        return self.cached(payload)

    def cached(self,payload):
        directory=Path(payload['directory']);usage={}
        events=directory/'events.jsonl'
        for line in (events.read_text() if events.is_file() else '').splitlines():
            try:
                event=json.loads(line)
                if event.get('type')=='turn.completed': usage=event.get('usage',{})
            except ValueError:
                continue
        return self.result((directory/'response.json').read_text(),payload['model'],usage,'stop')

    @staticmethod
    def result(content,model,usage,finish,raw=None):
        return {'content':content,'finish_reason':finish,'raw':raw,'usage':{'day':kst_day(),'model':model,
            'input_tokens':usage.get('input_tokens',usage.get('prompt_tokens',0)),
            'output_tokens':usage.get('output_tokens',usage.get('completion_tokens',0))}}


def next_kst_day():
    from datetime import timedelta, time
    now=datetime.now(ZoneInfo('Asia/Seoul'))
    return datetime.combine(now.date()+timedelta(days=1),time(),tzinfo=now.tzinfo).timestamp()
