from dataclasses import dataclass
from datetime import datetime, timezone

from .limits import LIMITS


def utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BudgetDecision:
    expired: bool = False
    finalize: bool = False
    discard: frozenset[str] = frozenset()


class BudgetPolicy:
    def __init__(self, now=utc_now):
        self.now = now

    def seconds_left(self, session):
        return (session.deadline - self.now()).total_seconds()

    def calls_left(self, session):
        if (not session.models_available or self.seconds_left(session) <= session.reserve_seconds
                or session.input_tokens >= session.input_token_limit or session.output_tokens >= session.output_token_limit):
            return 0
        return max(0, session.call_limit - session.doctor_calls)

    def action_capacity(self, state):
        protected = 0 if state.session.current == "Education" else LIMITS.education_turns
        return max(0, state.session.turns_remaining - protected)

    def can_clarify(self, state):
        session = state.session
        return (session.clarifications < LIMITS.clarifications and not session.finalizing
                and self.calls_left(session) >= 1 and self.action_capacity(state) > 0
                and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds
                and session.output_token_limit - session.output_tokens >= LIMITS.gateway_tokens)

    def model_allowance(self, session):
        if not self.calls_left(session):
            return 0
        return min(LIMITS.gateway_tokens, session.output_token_limit - session.output_tokens)

    def evaluate(self, state):
        if state.interaction.termination or state.interaction.pending:
            return BudgetDecision()
        session = state.session
        if self.seconds_left(session) <= 0:
            return BudgetDecision(expired=True)
        if (session.finalizing or self.seconds_left(session) <= session.reserve_seconds + LIMITS.response_seconds
                or session.turns_remaining == 0 or self.calls_left(session) == 0
                or session.output_token_limit - session.output_tokens < LIMITS.gateway_tokens):
            return BudgetDecision(finalize=True, discard=frozenset(item.id for item in state.case.unasked(session.current)))
        if not session.initialized:
            return BudgetDecision()
        actions_left, calls_left = self.action_capacity(state), self.calls_left(session)
        questions = [q for q in state.questions.questions
                     if (item := state.case.get(q.item_id)) and item.scope == session.current and item.status == "unasked"]
        keep = set()
        for question in sorted(questions, key=lambda q: (-q.priority, q.order, q.item_id)):
            if actions_left <= 0 or calls_left < 1:
                continue
            keep.add(question.item_id)
            actions_left -= 1
            calls_left -= 1
        return BudgetDecision(discard=frozenset(q.item_id for q in questions) - keep)

    @staticmethod
    def graph_step_limit(state):
        return LIMITS.graph_base_steps + LIMITS.graph_steps_per_turn * min(LIMITS.turns, state.session.turns_remaining)
