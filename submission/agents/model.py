from uuid import uuid4

from nova_sdk import NovaError

from .session import sdk_failure
from .transport import TRANSIENT_ERRORS, request_with_recovery

MODEL = "openai/gpt-6-luna"
GATEWAY_TOKENS = 2048


def complete(state, client, *, role, messages, reserve_reply=False):
    session = state.session
    reserve_calls = int(reserve_reply)
    output_left = session.output_token_limit - session.output_tokens
    reserve_tokens = min(GATEWAY_TOKENS, output_left) if reserve_reply else 0
    if session.calls_left() <= reserve_calls or output_left <= reserve_tokens:
        state.interaction.issues.append(f"{role}_budget_exhausted")
        return None
    request = {"messages": messages, "model": MODEL, "request_id": str(uuid4()),
               "max_tokens": min(1024 if role == "doctor" else GATEWAY_TOKENS, output_left - reserve_tokens),
               "reasoning_effort": "low" if role == "doctor" else "medium"}
    exchange = {"role": role, "scope": session.current, "request": request, "attempts": []}
    state.interaction.model_history.append(exchange)
    session.doctor_calls += 1
    session.usage[session.current].calls += 1
    usage_accounted = False
    try:
        completion = request_with_recovery(state, client, client.chat, request, exchange["attempts"])
        exchange["response"] = completion
        usage = completion["usage"]
        amounts = [usage[key] for key in ("prompt_tokens", "completion_tokens")]
        if any(type(amount) is not int or amount < 0 for amount in amounts):
            raise ValueError("Invalid model usage")
        session.input_tokens += amounts[0]
        session.output_tokens += amounts[1]
        usage_accounted = True
        content = completion["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Invalid model content")
        if content.strip():
            session.doctor_successes += 1
        return content
    except NovaError as error:
        exchange["error"] = error.code
        if error.code in {"MODEL_CALL_LIMIT", "MODEL_TOKEN_BUDGET", *TRANSIENT_ERRORS, "REQUEST_BUDGET_EXHAUSTED"}:
            session.models_available = False
            state.interaction.issues.append(error.code)
        elif error.code == "PROVIDER_RESPONSE_INVALID":
            state.interaction.issues.append(f"empty_{role}_response")
        else:
            sdk_failure(state, error)
    except (KeyError, IndexError, TypeError, ValueError):
        if not usage_accounted:
            session.models_available = False
        exchange["error"] = "invalid_model_response"
        state.interaction.issues.append(f"invalid_{role}_response")
    return None
