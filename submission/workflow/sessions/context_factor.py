from ..rules.assessment import context_questions, applicability
from ..state.evidence import EvidenceIndex
from ..rules.limits import LIMITS
from ..rules.collection import HISTORY, answered


class ContextFactorSession:
    def __init__(self, knowledge, config, tools):
        self.knowledge, self.config, self.tools = knowledge, config, tools
        self.candidate_ids = ()
        self.rules = ()

    def close(self, state, client):
        pass

    def enter(self, state, assessment):
        self.candidate_ids = tuple(self.knowledge.term_id(e.name, 'Disease') for e in assessment.differential
            if e.kind == 'disease') if assessment else ()
        self.rules = tuple(context_questions(self.knowledge, self.candidate_ids))
        if not self.candidate_ids:
            state.interview.collection['ContextFactor:candidates'] = 'cc_assessment_unavailable'

    def prepare(self, state, *, specs=None):
        self.tools._prepare_common(state, HISTORY, self.config.texts.history_questions, 'history')
        if not state.interview.queue:
            self.prepare_context(state, specs=specs)

    def prepare_context(self, state, *, specs=None):
        covered = {a.key[1] for a in state.interview.answers if a.purpose == 'context' and a.coverage
            and a.outcome != 'undelivered' and a.key}
        if len(covered) >= 2 and self.tools.budget.action_capacity(state) <= 0:
            return
        specs = self.context_specs(state) if specs is None else specs
        if specs:
            spec = min(specs.values(), key=lambda row: row['target_id'])
            self.tools._register(state, dict(spec, coverage=len(covered) < 2), 0, LIMITS.hpi_priority)

    def context_specs(self, state):
        specs = {}
        index = EvidenceIndex.from_case(state.case, self.knowledge)
        for ident, rule_scope in self.rules:
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

    def required_actions(self, state, *, specs=None):
        covered = {a.key[1] for a in state.interview.answers if a.purpose == 'context' and a.coverage
                   and a.outcome != 'undelivered' and a.key}
        specs = self.context_specs(state) if specs is None else specs
        related = min(max(0, 2 - len(covered)), len({s['target_id'] for s in specs.values()}))
        return sum(not answered(state, slot) for slot in HISTORY) + related

