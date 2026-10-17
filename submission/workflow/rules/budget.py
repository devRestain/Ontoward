from dataclasses import dataclass
from datetime import datetime, timezone

from .limits import LIMITS, SESSION_INTERVIEW_LIMITS


def utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BudgetDecision:
    expired: bool = False
    finalize: bool = False
    discard: frozenset[str] = frozenset()


class BudgetPolicy:
    def __init__(self, now=utc_now, *, education_enabled=False):
        self.now = now
        self.education_enabled = education_enabled

    def seconds_left(self, session):
        return (session.deadline - self.now()).total_seconds()

    def calls_left(self, session):
        if (not session.models_available or self.seconds_left(session) <= session.reserve_seconds
                or session.input_tokens >= session.input_token_limit or session.output_tokens >= session.output_token_limit):
            return 0
        return max(0, session.call_limit - session.doctor_calls)

    def interview_limits(self, state):
        if state.session.current == "Education" and self.education_enabled:
            return 2, LIMITS.education_turns
        return SESSION_INTERVIEW_LIMITS[state.session.current]

    @staticmethod
    def interview_actions(state):
        usage = state.session.usage[state.session.current]
        return usage.actions - usage.empathy_actions

    def shared_action_capacity(self, state):
        protected = LIMITS.education_turns if self.education_enabled and state.session.current != "Education" else 0
        return max(0, state.session.turns_remaining - protected)

    def action_capacity(self, state, *, purpose=None):
        shared = self.shared_action_capacity(state)
        if purpose == "empathy":
            return shared
        return max(0, min(shared, self.interview_limits(state)[1] - self.interview_actions(state)))

    def collection_available(self, session):
        return (not session.finalizing and session.turns_remaining > 0 and self.calls_left(session) > 0
                and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds
                and session.output_token_limit - session.output_tokens >= LIMITS.gateway_tokens)

    def can_start_action(self, state, *, purpose=None):
        return self.collection_available(state.session) and self.action_capacity(state, purpose=purpose) > 0

    def can_clarify(self, state):
        session = state.session
        return session.clarifications < LIMITS.clarifications and self.can_start_action(state)

    def model_allowance(self, session):
        if not self.calls_left(session):
            return 0
        return min(LIMITS.gateway_tokens, session.output_token_limit - session.output_tokens)

    def evaluate(self, state):
        if state.interaction.termination:
            return BudgetDecision()
        session = state.session
        if self.seconds_left(session) <= 0:
            return BudgetDecision(expired=True)
        if not self.collection_available(session):
            return BudgetDecision(finalize=True, discard=frozenset(item.id for item in state.case.unasked(session.current)))
        if not session.initialized:
            return BudgetDecision()
        actions_left, calls_left = self.shared_action_capacity(state), self.calls_left(session)
        interview_left = self.action_capacity(state)
        questions = [q for q in state.questions.questions
                     if (item := state.case.get(q.item_id)) and item.scope == session.current and item.status == "unasked"]
        keep = set()
        for question in sorted(questions, key=lambda q: (-q.priority, q.order, q.item_id)):
            if actions_left <= 0 or calls_left < 1 or (question.purpose != "empathy" and interview_left <= 0):
                continue
            keep.add(question.item_id)
            actions_left -= 1
            calls_left -= 1
            if question.purpose != "empathy":
                interview_left -= 1
        return BudgetDecision(discard=frozenset(q.item_id for q in questions) - keep)

    @staticmethod
    def graph_step_limit(state):
        return LIMITS.graph_base_steps + LIMITS.graph_steps_per_turn * min(LIMITS.turns, state.session.turns_remaining)
