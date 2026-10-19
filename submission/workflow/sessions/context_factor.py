from ..rules.assessment import context_questions, applicability
from ..state.evidence import EvidenceIndex
from ..rules.limits import LIMITS
from ..rules.collection import HISTORY, answered


class ContextFactorSession:
    def __init__(self, knowledge, config, tools, brain):
        self.knowledge, self.config, self.tools, self.brain = knowledge, config, tools, brain
        self.closed = False
        self.error = None
        self.candidate_ids = ()

    def close(self, state, client):
        self.closed = True

    def enter(self, state, assessment):
        self.candidate_ids = tuple(self.knowledge.term_id(e.name, 'Disease') for e in assessment.differential
            if e.kind == 'disease') if assessment else ()
        if not self.candidate_ids:
            state.interview.collection['ContextFactor:candidates'] = 'cc_assessment_unavailable'

    def prepare(self, state):
        self.tools._prepare_common(state, HISTORY, self.config.texts.history_questions, 'history')
        if not state.interview.queue:
            self.prepare_context(state)

    def prepare_context(self, state):
        covered = {a.key[1] for a in state.interview.answers if a.purpose == 'context' and a.coverage
            and a.outcome != 'undelivered' and a.key}
        if len(covered) >= 2 and self.tools.budget.action_capacity(state) <= 0:
            return
        specs = self.context_specs(state)
        if specs:
            spec = min(specs.values(), key=lambda row: row['target_id'])
            self.tools._register(state, dict(spec, coverage=len(covered) < 2), 0, LIMITS.hpi_priority)

    def context_specs(self, state):
        specs = {}
        index = EvidenceIndex.from_case(state.case, self.knowledge)
        for ident, rule_scope in context_questions(self.knowledge, self.candidate_ids):
            from knowledge.conditions import Applicability
            conditions = [Applicability(concept_id=ident,status=status,**{key:value for key,value in rule_scope.model_dump().items() if key not in {'concept_id','status'}})
                for status in ('present','absent')]
            if any(applicability([condition],index.contexts)[0] == 'matched' for condition in conditions):
                continue
            spec = self.tools._spec(state, ident, purpose='context', subject=rule_scope.subject,
                subject_member=rule_scope.subject_member, time_context=self.knowledge.execution_time(ident,rule_scope))
            if spec and self.tools._eligible(state,spec):
                specs[self.tools._key(spec)] = spec
        return specs

    def required_actions(self, state):
        covered = {a.key[1] for a in state.interview.answers if a.purpose == 'context' and a.coverage
                   and a.outcome != 'undelivered' and a.key}
        related = min(max(0, 2 - len(covered)), len({s['target_id'] for s in self.context_specs(state).values()}))
        return sum(not answered(state, slot) for slot in HISTORY) + related

