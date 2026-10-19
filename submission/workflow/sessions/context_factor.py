from ..rules.decision import prepare_decision, accept_ranking, rank_exchange
from ..rules.limits import LIMITS
from ..rules.collection import HISTORY


class ContextFactorSession:
    def __init__(self, knowledge, config, tools, brain):
        self.knowledge, self.config, self.tools, self.brain = knowledge, config, tools, brain
        self.closed = False
        self.error = None
        self.candidate_ids = ()

    def prepare_decision(self, state):
        return prepare_decision(state, self.knowledge, self.tools, mode='rank')

    def accept(self, state, raw, work):
        accept_ranking(state, raw, work)

    def close(self, state, client):
        if self.closed or state.session.termination or state.case.assessment and state.case.assessment.frozen:
            return
        self.closed = True
        work = self.prepare_decision(state)
        self.error = rank_exchange(state, client, self.brain, self.config, work,
            lambda raw: self.accept(state, raw, work))

    def enter(self, state, chief_session):
        assessment = state.case.assessment
        self.candidate_ids = tuple(self.knowledge.term_id(e.name, 'Disease') for e in assessment.differential
            if e.kind == 'disease') if chief_session.closed and not chief_session.error and assessment else ()
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
        specs = {}
        for disease in self.candidate_ids:
            contexts = [(c['id'], 'family' if c['type'] == 'family_history' else 'patient', 'unspecified', False)
                for c in self.tools.knowledge.get_supporting_context(disease)]
            for profile in self.tools.knowledge.get_disease_patterns(disease):
                contexts += [(c.concept_id, c.subject, c.time_context, True) for c in profile.applicability]
            for ident, subject, timing, prerequisite in contexts:
                if self.tools.knowledge.term(ident) in covered:
                    continue
                spec = self.tools._spec(state, ident, purpose='context', subject=subject, time_context=timing)
                if spec and self.tools._eligible(state, spec):
                    key = self.tools._key(spec)
                    if key not in specs or prerequisite:
                        specs[key] = (prerequisite, spec)
        if specs:
            _, spec = min(specs.values(), key=lambda row:(not row[0], row[1]['target_id']))
            self.tools._register(state, dict(spec, coverage=len(covered) < 2), 0, LIMITS.hpi_priority)

