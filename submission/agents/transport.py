import time

from nova_sdk import NovaError

TRANSIENT_ERRORS = {"API_UNAVAILABLE", "INVALID_API_RESPONSE", "RESPONSE_TOO_LARGE",
                    "PROVIDER_UNAVAILABLE", "REQUEST_PENDING"}


def request_with_recovery(state, client, call, payload, attempts, *, final=False):
    original_timeout = getattr(client, "timeout", None)
    reserve = 0 if final else state.session.reserve_seconds
    try:
        for attempt in range(3):
            remaining = state.session.seconds_left() - reserve
            if remaining <= 0:
                raise NovaError("SESSION_EXPIRED" if state.session.seconds_left() <= 0 else "REQUEST_BUDGET_EXHAUSTED")
            if original_timeout is not None:
                client.timeout = min(240, remaining)
            try:
                result = call(**payload)
                attempts.append({"attempt": attempt + 1, "result": "response_received"})
                return result
            except NovaError as error:
                attempts.append({"attempt": attempt + 1, "error": error.code})
                if error.code not in TRANSIENT_ERRORS or attempt == 2:
                    raise
                delay = (2, 5)[attempt]
                if state.session.seconds_left() - reserve <= delay:
                    raise
                time.sleep(delay)
    finally:
        if original_timeout is not None:
            client.timeout = original_timeout
