import time

from nova_sdk import NovaError

from ..rules.limits import LIMITS, TRANSIENT_ERRORS
from .sdk_boundary import sdk_call


class RequestExecutor:
    def __init__(self, budget, sleep=None):
        self.budget = budget
        self.sleep = sleep if sleep is not None else time.sleep

    def execute(self, state, client, call, payload, attempts, *, final=False, action=False):
        original_timeout = getattr(client, "timeout", None)
        reserve = 0 if final else state.session.reserve_seconds + (LIMITS.response_seconds if action else 0)
        try:
            for attempt in range(len(LIMITS.retry_delays) + 1):
                remaining = self.budget.seconds_left(state.session) - reserve
                if remaining <= 0:
                    raise NovaError("SESSION_EXPIRED" if self.budget.seconds_left(state.session) <= 0 else "REQUEST_BUDGET_EXHAUSTED")
                if original_timeout is not None:
                    client.timeout = min(LIMITS.request_timeout, remaining)
                try:
                    result = sdk_call(call, **payload)
                    if 'note' in payload and 'diagnosis' in payload and (not isinstance(result, dict) or result.get('status') != 'completed'):
                        # A malformed receipt has an unknown outcome. Recover with
                        # the identical ID/body within the existing transport bound.
                        if not isinstance(result, dict) or result.get('status') not in {'active', 'ready', 'in_progress', 'closed', 'expired'}:
                            raise NovaError('INVALID_API_RESPONSE')
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
