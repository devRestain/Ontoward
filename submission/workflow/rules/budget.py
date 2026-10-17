from dataclasses import dataclass
from datetime import datetime, timezone

from .limits import LIMITS, SESSION_INTERVIEW_LIMITS, SESSION_ORDER
from .collection import INTAKE, HISTORY, ATTRIBUTE_CATEGORIES, answered, slot_resolved


def utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BudgetDecision:
    expired: bool = False
    finalize: bool = False
    discard: frozenset[str] = frozenset()


class BudgetPolicy:
    def __init__(self, now=utc_now, *, education_enabled=False, knowledge=None):
        self.now = now
        self.education_enabled = education_enabled
        self.knowledge = knowledge

    def seconds_left(self, session):
        return (session.deadline - self.now()).total_seconds()

    def calls_left(self, session):
        if (not session.models_available or self.seconds_left(session) <= session.reserve_seconds
                or session.input_tokens >= session.input_token_limit or session.output_tokens >= session.output_token_limit):
            return 0
        return max(0, session.call_limit - session.doctor_calls)

    def interview_limits(self, state):
        if state.session.current == "Education" and not self.education_enabled:
            return 0, 0
        return SESSION_INTERVIEW_LIMITS[state.session.current]

    @staticmethod
    def interview_actions(state):
        usage = state.session.usage[state.session.current]
        return usage.actions - usage.empathy_actions

    def required_actions(self, state, scope):
        if scope == "Initiation":
            greeting = not any(e.delivered and e.question and e.question.purpose == "greeting" for e in state.interaction.history)
            return int(greeting) + sum(not answered(state, slot) for slot in INTAKE)
        if scope == "ChiefComplaint":
            if state.questions.chief_anchor_key:
                attributes = sum(s in {"unasked", "budget_stopped"} for s in state.questions.chief_attributes.values())
            elif self.knowledge and state.case.primary_chief:
                attributes = sum(not slot_resolved(state.case, ATTRIBUTE_CATEGORIES.get(a.rsplit(":", 1)[-1], ""))
                    for a in self.knowledge.get_symptom_attributes(state.case.primary_chief.target_id))
            else:
                attributes = 6
            opened = any(e.delivered and e.question and e.question.purpose == "open_inquiry" for e in state.interaction.history)
            return min(7, attributes + int(not opened))
        if scope == "ContextFactor":
            graph = max(0, 2 - len(state.questions.context_coverage))
            if self.knowledge and state.case.primary_chief:
                profiles = self.knowledge.get_patterns_by_target(state.case.primary_chief.target_id)
                available = {c["id"] for p in profiles for c in self.knowledge.get_supporting_context(p.disease_id)}
                available.update(c.concept_id for p in profiles for c in p.applicability)
                graph = min(graph, len(available - set(state.questions.context_coverage)))
            return sum(not answered(state, slot) for slot in HISTORY) + graph
        if scope == "Education":
            return LIMITS.education_turns if self.education_enabled else 0
        return max(0, 3 - (state.session.usage[scope].actions - state.session.usage[scope].empathy_actions))

    def shared_action_capacity(self, state, *, purpose=None):
        following = SESSION_ORDER[SESSION_ORDER.index(state.session.current) + 1:]
        protected = sum(self.required_actions(state, scope) for scope in following)
        if purpose == "empathy":
            protected += self.required_actions(state, state.session.current)
        return max(0, state.session.turns_remaining - protected)

    def action_capacity(self, state, *, purpose=None):
        shared = self.shared_action_capacity(state, purpose=purpose)
        if purpose == "empathy":
            return shared
        return max(0, min(shared, self.interview_limits(state)[1] - self.interview_actions(state)))

    def collection_available(self, session):
        education = session.current == "Education" and self.education_enabled
        return (not session.finalizing and session.turns_remaining > 0 and (education or self.calls_left(session) > 0)
                and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds
                and (education or session.output_token_limit - session.output_tokens >= LIMITS.gateway_tokens))

    def can_start_action(self, state, *, purpose=None):
        return self.collection_available(state.session) and self.action_capacity(state, purpose=purpose) > 0

    def can_clarify(self, state):
        session = state.session
        return session.clarifications < LIMITS.clarifications and self.can_start_action(state)

    def model_allowance(self, session, role="gateway", *, maximum=None):
        if not self.calls_left(session):
            return 0
        maximum = maximum or {"education": LIMITS.education_tokens,
                   "education_doctor": LIMITS.education_doctor_tokens}.get(role, LIMITS.gateway_tokens)
        maximum = min(maximum, LIMITS.gateway_recovery_tokens)
        reserve = LIMITS.education_doctor_tokens if role == "education" and not session.finalizing else 0
        if reserve and self.calls_left(session) < 2:
            return 0
        return max(0, min(maximum, session.output_token_limit - session.output_tokens - reserve))

    def can_empathize(self, state):
        session = state.session
        return (not session.finalizing and not state.interaction.submission_payload
                and session.current != "Education"
                and self.action_capacity(state, purpose="empathy") > 0 and "SAY" in session.allowed_actions
                and self.calls_left(session) >= 2
                and session.output_token_limit - session.output_tokens >= 2 * LIMITS.gateway_tokens
                and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds)

    def evaluate(self, state):
        if state.interaction.termination:
            return BudgetDecision()
        session = state.session
        if self.seconds_left(session) <= 0:
            return BudgetDecision(expired=True)
        if not self.collection_available(session):
            return BudgetDecision(finalize=True, discard=frozenset(item.id for item in state.unasked()))
        if not session.initialized:
            return BudgetDecision()
        actions_left, calls_left = self.shared_action_capacity(state), self.calls_left(session)
        interview_left = self.action_capacity(state)
        questions = state.pending_questions()
        keep = set()
        if session.current == "Education":
            groups = {}
            for question in sorted(questions, key=lambda q: q.order):
                groups.setdefault(question.plan_sentence_id or question.item_id, []).append(question)
            for group in groups.values():
                if len(group) <= min(actions_left, interview_left):
                    keep.update(q.item_id for q in group)
                    actions_left -= len(group)
                    interview_left -= len(group)
            return BudgetDecision(discard=frozenset(q.item_id for q in questions) - keep)
        for question in sorted(questions, key=lambda q: (-q.priority, q.order, q.item_id)):
            model_cost = int(question.purpose != "education")
            if actions_left <= 0 or calls_left < model_cost or (question.purpose != "empathy" and interview_left <= 0):
                continue
            keep.add(question.item_id)
            actions_left -= 1
            calls_left -= model_cost
            if question.purpose != "empathy":
                interview_left -= 1
        return BudgetDecision(discard=frozenset(q.item_id for q in questions) - keep)

    @staticmethod
    def graph_step_limit(state):
        return LIMITS.graph_base_steps + LIMITS.graph_steps_per_turn * min(LIMITS.turns, state.session.turns_remaining)
