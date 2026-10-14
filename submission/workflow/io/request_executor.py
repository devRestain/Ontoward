import time

from nova_sdk import NovaError

from ..rules.limits import LIMITS, TRANSIENT_ERRORS


class RequestExecutor:
    def __init__(self, budget, sleep=None):
        self.budget = budget
        self.sleep = sleep if sleep is not None else time.sleep

    def execute(self, state, client, call, payload, attempts, *, final=False):
        original_timeout = getattr(client, "timeout", None)
        reserve = 0 if final else state.session.reserve_seconds
        try:
            for attempt in range(len(LIMITS.retry_delays) + 1):
                remaining = self.budget.seconds_left(state.session) - reserve
                if remaining <= 0:
                    raise NovaError("SESSION_EXPIRED" if self.budget.seconds_left(state.session) <= 0 else "REQUEST_BUDGET_EXHAUSTED")
                if original_timeout is not None:
                    client.timeout = min(LIMITS.request_timeout, remaining)
                try:
                    result = call(**payload)
                    attempts.append({"attempt": attempt + 1, "result": "response_received"})
                    return result
                except NovaError as error:
                    attempts.append({"attempt": attempt + 1, "error": error.code})
                    if error.code not in TRANSIENT_ERRORS or attempt == len(LIMITS.retry_delays):
                        raise
                    delay = LIMITS.retry_delays[attempt]
                    if self.budget.seconds_left(state.session) - reserve <= delay:
                        raise
                    self.sleep(delay)
        finally:
            if original_timeout is not None:
                client.timeout = original_timeout
