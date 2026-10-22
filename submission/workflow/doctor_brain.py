from dataclasses import dataclass

from nova_sdk import NovaError

from .model_context import message_metrics

from .state import usage
from .rules.limits import LIMITS, TRANSIENT_ERRORS


@dataclass(frozen=True)
class ModelResult:
    content: str | None = None
    error: str | None = None
    request_id: str | None = None


class DoctorBrain:
    def __init__(self, executor, budget, new_request_id):
        self.executor, self.budget = executor, budget
        self.new_request_id = new_request_id

    def complete(self, state, client, *, role, messages, max_tokens=None):
        session = state.session
        if role not in {'gateway', 'clinical', 'education', 'education_doctor'}:
            raise ValueError('Unsupported designated-model role')
        input_metrics = message_metrics(role, messages)
        education = role in {'education', 'education_doctor'}
        if education:
            if session.budget_sync_required:
                return ModelResult(error='LOCAL_EDUCATION_BUDGET_SYNC_REQUIRED')
            if input_metrics['messages_json_bytes'] > LIMITS.education_max_messages_bytes:
                return ModelResult(error='LOCAL_EDUCATION_MESSAGE_LIMIT')
        allowance = self.budget.model_allowance(session, role, maximum=max_tokens, state=state)
        if not allowance:
            return ModelResult(error='MODEL_UNAVAILABLE')
        request = {'messages':messages, 'model':LIMITS.model, 'request_id':self.new_request_id(),
                   'max_tokens':allowance, 'reasoning_effort':'high' if role in {'education','clinical'} else LIMITS.gateway_reasoning}
        attempts, response, accounted = [], None, False
        usage.record_model_request(state)
        try:
            response = self.executor.execute(state, client, client.chat, request, attempts)
            amounts = [response['usage'][k] for k in ('prompt_tokens', 'completion_tokens')]
            if any(type(n) is not int or n < 0 for n in amounts):
                raise ValueError('Invalid model usage')
            usage.record_tokens(state, amounts)
            accounted = True
            if amounts[0] > LIMITS.request_input_tokens:
                raise NovaError('CONTEXT_LIMIT_EXCEEDED', 400)
            if session.input_tokens > session.input_token_limit or session.output_tokens > session.output_token_limit:
                raise NovaError('MODEL_TOKEN_BUDGET', 429)
            choice = response['choices'][0]
            content = choice['message']['content'] or ''
            if choice.get('finish_reason') == 'length':
                result = ModelResult(error='OUTPUT_TRUNCATED', request_id=request['request_id'])
            elif not isinstance(content, str):
                raise ValueError('Invalid model content')
            else:
                if content.strip():
                    usage.record_model_success(state)
                result = ModelResult(content=content, request_id=request['request_id'])
        except NovaError as error:
            result = ModelResult(error=error.code, request_id=request['request_id'])
            if education and error.code == 'CONTEXT_LIMIT_EXCEEDED':
                session.budget_sync_required = True
            elif error.code in TRANSIENT_ERRORS:
                session.budget_sync_required = True
            elif error.code in {'MODEL_CALL_LIMIT', 'MODEL_TOKEN_BUDGET', 'REQUEST_BUDGET_EXHAUSTED'}:
                usage.disable_models(state)
                session.budget_sync_required = True
        except (KeyError, IndexError, TypeError, ValueError):
            if not accounted:
                usage.disable_models(state)
            result = ModelResult(error='invalid_model_response', request_id=request['request_id'])
        except Exception as error:
            session.budget_sync_required = True
            result = ModelResult(error='model_exception_' + type(error).__name__, request_id=request['request_id'])
        return result
