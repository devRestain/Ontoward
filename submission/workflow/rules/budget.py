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

    def can_frame(self, state, action):
        reserve = int(action.question.parsing_required)
        return (action.render_attempts < LIMITS.doctor_generations and self.calls_left(state.session) > reserve
                and state.session.output_token_limit - state.session.output_tokens > (LIMITS.gateway_tokens if reserve else 0))

    def can_clarify(self, state):
        session = state.session
        return (session.clarifications < LIMITS.clarifications and not session.finalizing
                and self.calls_left(session) >= 2
                and session.usage[session.current].actions < session.limits[session.current].actions
                and session.turns_remaining > 0)

    def model_allowance(self, session, role, reserve_reply):
        output_left = session.output_token_limit - session.output_tokens
        reserve_tokens = min(LIMITS.gateway_tokens, output_left) if reserve_reply else 0
        if self.calls_left(session) <= int(reserve_reply) or output_left <= reserve_tokens:
            return 0
        return min(LIMITS.doctor_tokens if role == "doctor" else LIMITS.gateway_tokens, output_left - reserve_tokens)

    def evaluate(self, state):
        if state.interaction.termination or state.interaction.pending:
            return BudgetDecision()
        session = state.session
        if self.seconds_left(session) <= 0:
            return BudgetDecision(expired=True)
        if (session.finalizing or self.seconds_left(session) <= session.reserve_seconds
                or session.turns_remaining == 0 or self.calls_left(session) == 0):
            return BudgetDecision(finalize=True, discard=frozenset(item.id for item in state.case.unasked(session.current)))
        if not session.initialized:
            return BudgetDecision()
        actions_left = min(session.limits[session.current].actions - session.usage[session.current].actions, session.turns_remaining)
        calls_left = self.calls_left(session)
        questions = [q for q in state.questions.questions
                     if (item := state.case.get(q.item_id)) and item.scope == session.current and item.status == "unasked"]
        keep = set()
        for question in sorted(questions, key=lambda q: (-q.priority, q.order, q.item_id)):
            selected = state.interaction.selected
            already_framed = selected and selected.question.item_id == question.item_id and selected.ready
            cost = int(question.parsing_required) + int(question.kind == "SAY" and not already_framed)
            if actions_left <= 0 or calls_left < cost:
                continue
            keep.add(question.item_id)
            actions_left -= 1
            calls_left -= cost
        return BudgetDecision(discard=frozenset(q.item_id for q in questions) - keep)

    @staticmethod
    def graph_step_limit(state):
        return LIMITS.graph_base_steps + LIMITS.graph_steps_per_turn * min(LIMITS.turns, state.session.turns_remaining)
