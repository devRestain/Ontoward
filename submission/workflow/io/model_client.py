import json
from dataclasses import dataclass

from nova_sdk import NovaError

from ..audit import emit
from ..rules.action import failure_outcome
from ..rules.limits import LIMITS, TRANSIENT_ERRORS


@dataclass(frozen=True)
class ModelResult:
    content: str | None = None
    error: str | None = None
    request_id: str | None = None


class ModelClient:
    def __init__(self, executor, budget, usage, new_request_id, audit=None):
        self.executor, self.budget, self.usage = executor, budget, usage
        self.new_request_id, self.audit = new_request_id, audit

    def complete(self, state, client, *, role, messages, max_tokens=None):
        session = state.session
        if role not in {'gateway', 'empathy', 'education', 'education_doctor'}:
            raise ValueError('Unsupported designated-model role')
        allowance = self.budget.model_allowance(session, role, maximum=max_tokens)
        size = len(json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode())
        if role.startswith('education') and (size > LIMITS.education_request_bytes
                or size > session.input_token_limit - session.input_tokens):
            return ModelResult(error='INPUT_BUDGET_EXHAUSTED')
        if not allowance:
            return ModelResult(error='MODEL_UNAVAILABLE')
        request = {'messages':messages, 'model':LIMITS.model, 'request_id':self.new_request_id(),
                   'max_tokens':allowance, 'reasoning_effort':'high' if role == 'education' else LIMITS.gateway_reasoning}
        attempts, response, accounted = [], None, False
        self.usage.record_model_request(state)
        try:
            response = self.executor.execute(state, client, client.chat, request, attempts)
            amounts = [response['usage'][k] for k in ('prompt_tokens', 'completion_tokens')]
            if any(type(n) is not int or n < 0 for n in amounts):
                raise ValueError('Invalid model usage')
            self.usage.record_tokens(state, amounts)
            accounted = True
            choice = response['choices'][0]
            content = choice['message']['content'] or ''
            if choice.get('finish_reason') == 'length':
                result = ModelResult(error='OUTPUT_TRUNCATED', request_id=request['request_id'])
            elif not isinstance(content, str):
                raise ValueError('Invalid model content')
            else:
                if content.strip():
                    self.usage.record_model_success(state, role)
                result = ModelResult(content=content, request_id=request['request_id'])
        except NovaError as error:
            result = ModelResult(error=error.code, request_id=request['request_id'])
            if error.code in TRANSIENT_ERRORS:
                state.stop('unknown', error.code)
            elif error.code in {'MODEL_CALL_LIMIT', 'MODEL_TOKEN_BUDGET', 'REQUEST_BUDGET_EXHAUSTED'}:
                self.usage.disable_models(state)
            elif error.code not in {'PROVIDER_RESPONSE_INVALID', 'CONTEXT_LIMIT_EXCEEDED'}:
                state.stop(failure_outcome(error), error.code)
        except (KeyError, IndexError, TypeError, ValueError):
            if not accounted:
                self.usage.disable_models(state)
            result = ModelResult(error='invalid_model_response', request_id=request['request_id'])
        emit(self.audit, 'model_exchange', role=role, request=request, response=response,
             error=result.error, attempts=attempts)
        return result
