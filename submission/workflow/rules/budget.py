from dataclasses import dataclass
from datetime import datetime, timezone

from .limits import LIMITS, SESSION_INTERVIEW_LIMITS, SESSION_ORDER

# Protect normal input (context + mapping) and final clinical/education work.
# The optional Ear repairs share the remaining calls; each call still protects
# final clinical and Education resources in model_allowance. Do not reserve four
# input calls for every question, which would stop collection unnecessarily early.
MODEL_CALLS = {
    'input': 2,
    'decision': 1,
    'clinical': 2,
    'education': 1,
    'education_doctor': 1,
}


def utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BudgetDecision:
    expired: bool = False
    finalize: bool = False
    discard: frozenset[str] = frozenset()
    reason: str | None = None


class BudgetPolicy:
    def __init__(self, now=utc_now, *, education_enabled=False):
        self.now, self.education_enabled = now, education_enabled
        self.required_counts = {}

    def seconds_left(self, session):
        return (session.deadline - self.now()).total_seconds()

    def calls_left(self, session):
        if (not session.models_available or self.seconds_left(session) <= session.reserve_seconds
                or session.input_tokens >= session.input_token_limit
                or session.output_tokens >= session.output_token_limit):
            return 0
        return max(0, session.call_limit - session.doctor_calls)

    def interview_limits(self, state):
        return (0,0) if state.interview.current == 'Education' and not self.education_enabled else SESSION_INTERVIEW_LIMITS[state.interview.current]

    @staticmethod
    def interview_actions(state):
        usage = state.session.usage[state.interview.current]
        return usage.actions

    def required_actions(self, state, scope):
        if scope == 'Education' and not self.education_enabled:
            return 0
        if scope == state.interview.current and scope in self.required_counts:
            return self.required_counts[scope]
        target = LIMITS.education_turns if scope == 'Education' else SESSION_INTERVIEW_LIMITS[scope][0]
        usage = state.session.usage[scope]
        return max(0, target - usage.actions)

    def model_work(self, state):
        work = {name: MODEL_CALLS[name] for name in ('input', 'clinical')}
        if self.education_enabled and state.interview.education_status == 'not_started':
            work.update({name: MODEL_CALLS[name] for name in ('education', 'education_doctor')})
        return work

    @staticmethod
    def reserve(work, tasks):
        return sum(work[name] for name in tasks if name in work)

    def shared_action_capacity(self, state):
        following = SESSION_ORDER[SESSION_ORDER.index(state.interview.current) + 1:]
        protected = sum(self.required_actions(state, scope) for scope in following)
        return max(0, state.session.turns_remaining - protected)

    def action_capacity(self, state):
        shared = self.shared_action_capacity(state)
        return max(0, min(shared, self.interview_limits(state)[1] - self.interview_actions(state)))

    def collection_calls(self, state):
        work = self.model_work(state)
        return self.reserve(work, work)

    def collection_available(self, state):
        session = state.session
        education = state.interview.current == 'Education' and self.education_enabled
        return (not session.finalizing and session.turns_remaining > 0 and (education or self.calls_left(session) >= self.collection_calls(state))
            and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds)

    def can_start_action(self, state):
        return self.collection_available(state) and self.action_capacity(state) > 0

    def education_available(self, state):
        session = state.session
        return (self.education_enabled and 'SAY' in session.allowed_actions and session.turns_remaining > 0
            and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds
            and session.usage['Education'].actions < SESSION_INTERVIEW_LIMITS['Education'][1])

    def can_clarify(self, state):
        return state.session.clarifications < LIMITS.clarifications and self.can_start_action(state)

    def model_allowance(self, session, role='gateway', *, maximum=None, state=None):
        if not self.calls_left(session):
            return 0
        maximum = min(maximum or {'education':LIMITS.education_tokens,
            'education_doctor':LIMITS.education_doctor_tokens}.get(role, LIMITS.gateway_tokens), LIMITS.gateway_recovery_tokens)
        calls = 0
        if state:
            work = self.model_work(state)
            tasks = []
            if role == 'education' and not session.finalizing:
                work['education_doctor'] = MODEL_CALLS['education_doctor']
                tasks = ['education_doctor']
            elif state.interview.current != 'Education' and role in {'gateway', 'clinical'}:
                tasks = ['education', 'education_doctor']
                if role == 'gateway' and not (state.case.assessment and state.case.assessment.frozen):
                    tasks.append('clinical')
            calls = self.reserve(work, tasks)
        elif role == 'education' and not session.finalizing:
            calls = MODEL_CALLS['education_doctor']
        if self.calls_left(session) <= calls:
            return 0
        return min(maximum, session.output_token_limit - session.output_tokens)

    def evaluate(self, state):
        if state.session.termination:
            return BudgetDecision()
        if self.seconds_left(state.session) <= 0:
            return BudgetDecision(expired=True)
        if not self.collection_available(state):
            session = state.session
            reason = ('collection_complete' if session.finalizing else 'turn_budget' if not session.turns_remaining
                else 'time_budget' if self.seconds_left(session) <= session.reserve_seconds + LIMITS.response_seconds
                else 'model_token_budget' if session.input_tokens >= session.input_token_limit
                    or session.output_tokens >= session.output_token_limit
                else 'model_call_budget')
            return BudgetDecision(finalize=True, discard=frozenset(q.item_id for q in state.interview.queue), reason=reason)
        if state.interview.status == 'uninitialized':
            return BudgetDecision()
        shared, calls = self.shared_action_capacity(state), self.calls_left(state.session)
        current = max(0, min(shared, self.interview_limits(state)[1] - self.interview_actions(state)))
        keep = set()
        if state.interview.current == 'Education':
            groups = {}
            for q in sorted(state.interview.queue, key=lambda q:q.order):
                group = q.plan_sentence_id or (q.item_id.rsplit(':', 1)[0] if q.item_id.startswith('Education:diagnosis:') else q.item_id)
                groups.setdefault(group, []).append(q)
            for group in groups.values():
                if len(group) <= min(shared, current):
                    keep.update(q.item_id for q in group)
                    shared -= len(group)
                    current -= len(group)
        else:
            for q in sorted(state.interview.queue, key=lambda q:(-q.priority, q.order, q.item_id)):
                if shared > 0 and calls >= self.collection_calls(state) and current > 0:
                    keep.add(q.item_id)
                    shared -= 1
                    calls -= self.reserve(MODEL_CALLS, ('input', 'decision'))
                    current -= 1
        return BudgetDecision(discard=frozenset(q.item_id for q in state.interview.queue) - keep)
