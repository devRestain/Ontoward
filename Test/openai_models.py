"""Explicit, simulator-only OpenAI Responses adapter; no retries or provider fallback."""
import json
from pathlib import Path
import re
import threading
import urllib.error
import urllib.request

from nova_sdk import NovaError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class OpenAIModels:
    def __init__(self, key, output, maximum, model='gpt-6-luna'):
        if not key.strip():
            raise ValueError('Set OPENAI_API_KEY for openai_api mode')
        if type(maximum) is not int or not 1 <= maximum <= 1000:
            raise ValueError('Choose a request ceiling from 1 to 1000')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', model):
            raise ValueError('Set TEST_OPENAI_MODEL to an OpenAI model ID without an openai/ prefix')
        self.key, self.output, self.maximum, self.model = key, Path(output), maximum, model
        self.calls, self.stopped = 0, None
        self.reported_input_tokens = self.reported_output_tokens = self.requests_with_usage = 0
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def record(self, value):
        with (self.output / 'openai-requests.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')

    def complete(self, role, messages, max_tokens, request_id, *, reasoning_effort='medium'):
        body = dict(model=self.model, input=messages, reasoning={'effort': reasoning_effort},
                    max_output_tokens=max_tokens, store=False)
        with self.lock:
            if self.stopped:
                raise NovaError(self.stopped, 503)
            if self.calls >= self.maximum:
                self.stopped = 'MODEL_CALL_LIMIT'
                raise NovaError(self.stopped, 429)
            self.calls += 1
            entry = dict(number=self.calls, request_id=request_id, role=role, model=self.model,
                         max_tokens=max_tokens, reasoning_effort=reasoning_effort)
            self.record({**entry, 'status': 'reserved', 'body': body})
        request = urllib.request.Request('https://api.openai.com/v1/responses',
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'), method='POST',
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json',
                     'X-Client-Request-Id': request_id})
        try:
            with self.opener.open(request, timeout=240) as response:
                raw = json.load(response)
                provider_id = response.headers.get('x-request-id')
        except urllib.error.HTTPError as error:
            # Keep only allowlisted error metadata, never headers, credentials or arbitrary messages.
            try:
                value = json.load(error).get('error', {})
                provider_code = value.get('code')
            except (ValueError, AttributeError, TypeError):
                provider_code = None
            code = ('CONTEXT_LIMIT_EXCEEDED' if provider_code == 'context_length_exceeded'
                    else 'REQUEST_BUDGET_EXHAUSTED' if provider_code == 'insufficient_quota'
                    else 'OPENAI_RATE_LIMIT' if error.code == 429
                    else 'OPENAI_AUTHENTICATION_ERROR' if error.code in {401, 403}
                    else 'OPENAI_HTTP_ERROR')
            if code in {'REQUEST_BUDGET_EXHAUSTED', 'OPENAI_AUTHENTICATION_ERROR'}:
                self.stopped = code
            self.record({**entry, 'status': 'failed', 'error': code, 'http_status': error.code,
                         'provider_code': provider_code if provider_code in {
                             'context_length_exceeded', 'insufficient_quota', 'rate_limit_exceeded',
                             'invalid_api_key', 'model_not_found'} else None,
                         'provider_request_id': error.headers.get('x-request-id')})
            raise NovaError(code, error.code) from None
        except (OSError, ValueError) as error:
            self.record({**entry, 'status': 'outcome_unknown', 'error': 'OPENAI_OUTCOME_UNKNOWN',
                         'error_type': type(error).__name__})
            raise NovaError('OPENAI_OUTCOME_UNKNOWN', 503) from None
        # Preserve the actual response before interpreting it. Never retry an uncertain effect.
        self.record({**entry, 'status': 'received', 'provider_request_id': provider_id, 'response': raw})
        amounts = raw.get('usage') if isinstance(raw, dict) else None
        if isinstance(amounts, dict) and all(type(amounts.get(name)) is int and amounts[name] >= 0
                                             for name in ('input_tokens', 'output_tokens')):
            with self.lock:
                self.reported_input_tokens += amounts['input_tokens']
                self.reported_output_tokens += amounts['output_tokens']
                self.requests_with_usage += 1
        try:
            return self.normalize(raw)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise NovaError('PROVIDER_RESPONSE_INVALID', 503) from None

    @staticmethod
    def normalize(raw):
        status = raw['status']
        if status not in {'completed', 'incomplete'}:
            raise ValueError('Unsuccessful Responses result')
        if status == 'incomplete' and raw.get('incomplete_details', {}).get('reason') != 'max_output_tokens':
            raise ValueError('Unsupported incomplete result')
        text = []
        for item in raw['output']:
            if item.get('type') != 'message':
                continue
            for part in item.get('content', []):
                if part.get('type') == 'output_text':
                    if not isinstance(part['text'], str):
                        raise ValueError('Invalid output text')
                    text.append(part['text'])
        usage = raw['usage']
        amounts = [usage[name] for name in ('input_tokens', 'output_tokens')]
        if any(type(value) is not int or value < 0 for value in amounts):
            raise ValueError('Invalid usage')
        normalized_usage = dict(prompt_tokens=amounts[0], completion_tokens=amounts[1],
                                total_tokens=sum(amounts))
        # output_tokens already includes reasoning; retain details without adding them again.
        for source, target in (('input_tokens_details', 'prompt_tokens_details'),
                               ('output_tokens_details', 'completion_tokens_details')):
            if source in usage:
                normalized_usage[target] = usage[source]
        return dict(id=raw['id'], object='chat.completion', model=raw['model'], usage=normalized_usage,
                    choices=[dict(index=0, message=dict(role='assistant', content=''.join(text)),
                                  finish_reason='length' if status == 'incomplete' else 'stop')])
