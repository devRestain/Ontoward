from dataclasses import dataclass
from datetime import datetime, timezone

from .limits import LIMITS, SESSION_INTERVIEW_LIMITS, SESSION_ORDER
from .collection import INTAKE, HISTORY, answered


def utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BudgetDecision:
    expired: bool = False
    finalize: bool = False
    discard: frozenset[str] = frozenset()
    reason: str | None = None


class BudgetPolicy:
    def __init__(self, now=utc_now, *, education_enabled=False, knowledge=None):
        self.now, self.education_enabled, self.knowledge = now, education_enabled, knowledge

    def seconds_left(self, session):
        return (session.deadline - self.now()).total_seconds()

    def calls_left(self, session):
        if (not session.models_available or self.seconds_left(session) <= session.reserve_seconds
                or session.input_tokens >= session.input_token_limit or session.output_tokens >= session.output_token_limit):
            return 0
        return max(0, session.call_limit - session.doctor_calls)

    def interview_limits(self, state):
        return (0,0) if state.interview.current == 'Education' and not self.education_enabled else SESSION_INTERVIEW_LIMITS[state.interview.current]

    @staticmethod
    def interview_actions(state):
        usage = state.session.usage[state.interview.current]
        return usage.actions - usage.empathy_actions

    def required_actions(self, state, scope):
        if scope == 'Initiation':
            greeting = not any(a.purpose == 'greeting' and a.outcome != 'undelivered' for a in state.interview.answers)
            return int(greeting) + sum(not answered(state, slot) for slot in INTAKE)
        if scope == 'ChiefComplaint':
            chief = state.case.chief(confirmed=True)
            remaining = 6
            if self.knowledge and chief:
                target = self.knowledge.term_id(chief.target, 'Symptom')
                remaining = 0
                for attribute in self.knowledge.get_symptom_attributes(target):
                    name = self.knowledge.term(attribute)
                    key = ('SAY', chief.target, name, 'patient', '', chief.time_context, chief.observation_id or '', chief.episode_id or '')
                    acquired = any(f.target == chief.target and f.attribute == name and f.subject == 'patient'
                        and f.observation_id == chief.observation_id and f.episode_id == chief.episode_id
                        and f.time_context == chief.time_context and f.status in {'present','absent'} for f in state.case.current_facts())
                    processed = any(a.key == key and a.outcome != 'undelivered' for a in state.interview.answers)
                    blocked = state.interview.collection.get('|'.join(key)) == 'blocked_asset'
                    remaining += not (acquired or processed or blocked)
            opened = any(a.purpose == 'open_inquiry' and a.outcome != 'undelivered' for a in state.interview.answers)
            return min(7, remaining + int(not opened))
        if scope == 'ContextFactor':
            covered = {a.key[1] for a in state.interview.answers if a.purpose == 'context' and a.coverage
                       and a.outcome != 'undelivered' and a.key}
            graph = max(0, 2 - len(covered))
            chief = state.case.chief()
            if self.knowledge and chief:
                profiles = self.knowledge.get_patterns_by_target(self.knowledge.term_id(chief.target, 'Symptom'))
                from .assessment import context_questions
                diseases = {p.disease_id for p in profiles}
                available = {self.knowledge.term(target) for target,_ in context_questions(self.knowledge,diseases)}
                graph = min(graph, len(available - covered))
            return sum(not answered(state, slot) for slot in HISTORY) + graph
        if scope == 'Education':
            return LIMITS.education_turns if self.education_enabled else 0
        usage = state.session.usage[scope]
        return max(0, 3 - (usage.actions - usage.empathy_actions))

    def shared_action_capacity(self, state, *, purpose=None):
        following = SESSION_ORDER[SESSION_ORDER.index(state.interview.current) + 1:]
        protected = sum(self.required_actions(state, scope) for scope in following)
        if purpose == 'empathy':
            protected += self.required_actions(state, state.interview.current)
        return max(0, state.session.turns_remaining - protected)

    def action_capacity(self, state, *, purpose=None):
        shared = self.shared_action_capacity(state, purpose=purpose)
        return shared if purpose == 'empathy' else max(0, min(shared, self.interview_limits(state)[1] - self.interview_actions(state)))

    def collection_calls(self, state):
        return 4 + (2 if self.education_enabled and state.interview.education_status=='not_started' else 0)

    def collection_tokens(self, state):
        return 3 * LIMITS.gateway_tokens + LIMITS.gateway_recovery_tokens + (
            LIMITS.education_tokens + LIMITS.education_doctor_tokens
            if self.education_enabled and state.interview.education_status=='not_started' else 0)

    def collection_available(self, state):
        session = state.session
        education = state.interview.current == 'Education' and self.education_enabled
        return (not session.finalizing and session.turns_remaining > 0 and (education or self.calls_left(session) >= self.collection_calls(state))
            and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds
            and (education or session.output_token_limit - session.output_tokens >= self.collection_tokens(state)))

    def can_start_action(self, state, *, purpose=None):
        return self.collection_available(state) and self.action_capacity(state, purpose=purpose) > 0

    def education_available(self, state):
        session = state.session
        return (self.education_enabled and 'SAY' in session.allowed_actions and session.turns_remaining > 0
            and self.seconds_left(session) > session.reserve_seconds + LIMITS.response_seconds
            and session.usage['Education'].actions - session.usage['Education'].empathy_actions < SESSION_INTERVIEW_LIMITS['Education'][1])

    def can_clarify(self, state):
        return state.session.clarifications < LIMITS.clarifications and self.can_start_action(state)

    def model_allowance(self, session, role='gateway', *, maximum=None, state=None):
        if not self.calls_left(session):
            return 0
        maximum = min(maximum or {'education':LIMITS.education_tokens,
            'education_doctor':LIMITS.education_doctor_tokens}.get(role, LIMITS.gateway_tokens), LIMITS.gateway_recovery_tokens)
        reserve = LIMITS.education_doctor_tokens if role == 'education' and not session.finalizing else 0
        if reserve and self.calls_left(session) < 2:
            return 0
        if state and state.interview.current != 'Education' and role in {'gateway','clinical','empathy'}:
            pending = self.education_enabled and state.interview.education_status=='not_started'
            calls = 2 if pending else 0
            reserve = LIMITS.education_tokens + LIMITS.education_doctor_tokens if pending else 0
            if role == 'gateway' and not (state.case.assessment and state.case.assessment.frozen):
                calls += 2
                reserve += LIMITS.gateway_tokens + LIMITS.gateway_recovery_tokens
            if role == 'empathy':
                calls, reserve = self.collection_calls(state), self.collection_tokens(state)
            if self.calls_left(session) <= calls:
                return 0
        return max(0, min(maximum, session.output_token_limit - session.output_tokens - reserve))

    def can_empathize(self, state):
        session = state.session
        return (not session.finalizing and state.interview.current != 'Education' and self.can_start_action(state, purpose='empathy')
            and 'SAY' in session.allowed_actions and self.calls_left(session) >= self.collection_calls(state) + 1
            and session.output_token_limit - session.output_tokens >= self.collection_tokens(state) + LIMITS.gateway_tokens)

    def evaluate(self, state):
        if state.session.termination:
            return BudgetDecision()
        if self.seconds_left(state.session) <= 0:
            return BudgetDecision(expired=True)
        if not self.collection_available(state):
            session = state.session
            reason = ('collection_complete' if session.finalizing else 'turn_budget' if not session.turns_remaining
                else 'time_budget' if self.seconds_left(session) <= session.reserve_seconds + LIMITS.response_seconds
                else 'model_call_budget' if self.calls_left(session) < self.collection_calls(state) else 'model_token_budget')
            return BudgetDecision(finalize=True, discard=frozenset(q.item_id for q in state.interview.queue), reason=reason)
        if state.interview.status == 'uninitialized':
            return BudgetDecision()
        shared, current, calls = self.shared_action_capacity(state), self.action_capacity(state), self.calls_left(state.session)
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
                if shared > 0 and calls >= self.collection_calls(state) and (q.purpose == 'empathy' or current > 0):
                    keep.add(q.item_id)
                    shared -= 1
                    calls -= 3
                    current -= q.purpose != 'empathy'
        return BudgetDecision(discard=frozenset(q.item_id for q in state.interview.queue) - keep)

    def graph_step_limit(self, state):
        return 12 * (state.session.turns_remaining + LIMITS.clarifications + 6) + 100
