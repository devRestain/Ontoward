from nova_sdk import NovaError

from ..rules.action import failure_outcome
from ..rules.limits import LIMITS, TRANSIENT_ERRORS


class ModelClient:
    def __init__(self, executor, budget, usage, new_request_id):
        self.executor = executor
        self.budget = budget
        self.usage = usage
        self.new_request_id = new_request_id

    def complete(self, state, client, *, role, messages):
        session = state.session
        if role not in {"gateway", "terminology", "empathy"}:
            raise ValueError("Unsupported designated-model role")
        allowance = self.budget.model_allowance(session)
        if not allowance:
            state.interaction.issues.append(f"{role}_budget_exhausted")
            return None
        request = {"messages": messages, "model": LIMITS.model, "request_id": self.new_request_id(),
                   "max_tokens": allowance,
                   "reasoning_effort": LIMITS.gateway_reasoning}
        exchange = {"role": role, "scope": session.current, "request": request, "attempts": []}
        state.interaction.model_history.append(exchange)
        self.usage.record_model_request(state)
        usage_accounted = False
        try:
            completion = self.executor.execute(state, client, client.chat, request, exchange["attempts"])
            exchange["response"] = completion
            usage = completion["usage"]
            amounts = [usage[key] for key in ("prompt_tokens", "completion_tokens")]
            if any(type(amount) is not int or amount < 0 for amount in amounts):
                raise ValueError("Invalid model usage")
            self.usage.record_tokens(state, amounts)
            usage_accounted = True
            content = completion["choices"][0]["message"]["content"]
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise ValueError("Invalid model content")
            if content.strip():
                self.usage.record_model_success(state, role)
            return content
        except NovaError as error:
            exchange["error"] = error.code
            if error.code in {"MODEL_CALL_LIMIT", "MODEL_TOKEN_BUDGET", *TRANSIENT_ERRORS, "REQUEST_BUDGET_EXHAUSTED"}:
                self.usage.disable_models(state)
                state.interaction.issues.append(error.code)
            elif error.code == "PROVIDER_RESPONSE_INVALID":
                state.interaction.issues.append(f"empty_{role}_response")
            elif error.code == "CONTEXT_LIMIT_EXCEEDED":
                state.interaction.issues.append(error.code)
            else:
                state.stop(failure_outcome(error), error.code)
        except (KeyError, IndexError, TypeError, ValueError):
            if not usage_accounted:
                self.usage.disable_models(state)
            exchange["error"] = "invalid_model_response"
            state.interaction.issues.append(f"invalid_{role}_response")
        return None
