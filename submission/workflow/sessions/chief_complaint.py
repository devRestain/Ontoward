from ..rules.decision import prepare_decision, accept_ranking, rank_exchange
from ..rules.limits import LIMITS, SESSION_INTERVIEW_LIMITS
from ..state.models import Question


class ChiefComplaintSession:
    def __init__(self, knowledge, config, tools, brain):
        self.knowledge, self.config, self.tools, self.brain = knowledge, config, tools, brain
        self.closed = False
        self.error = None

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

    def prepare_collection(self, state):
        if not self.tools.ensure_chief(state):
            return False
        chief = state.case.collection_chief()
        stale = {q.item_id for q in state.interview.queue if q.purpose in {'hpi', 'chief', 'open_inquiry'}
                 and q.target and (chief is None or (q.target, q.observation_id, q.episode_id, q.time_context) !=
                     (chief.target, chief.observation_id, chief.episode_id, chief.time_context))}
        self.tools.questions.discard_unasked(state, stale, reason='chief_changed')
        target = self.tools.knowledge.term_id(chief.target, 'Symptom')
        for order, (name, status) in enumerate(self.tools.chief_statuses(state).items()):
            if status != 'unasked':
                continue
            attribute = self.tools.knowledge.term_id(name, 'FindingAttribute')
            spec = self.tools._spec(state, target, attribute, chief.observation_id, chief.episode_id,
                              purpose='hpi', field='S.hpi', time_context=chief.time_context) if attribute else None
            key = '|'.join(('SAY', chief.target, name, 'patient', '', chief.time_context, chief.observation_id or '', chief.episode_id or ''))
            if spec is None:
                state.interview.collection[key] = 'blocked_asset'
            elif self.tools.repeated_unknown_attribute(state, spec):
                self.tools.questions.discard_unasked(state, {q.item_id for q in state.interview.queue
                    if q.semantic_key() == self.tools._question(spec, '', 0, 0).semantic_key()}, reason='already_resolved')
                state.interview.collection[key] = 'passed_unknown'
            elif self.tools.budget.action_capacity(state) <= 1:
                state.interview.collection[key] = 'budget_stopped'
            else:
                self.tools._register(state, dict(spec, coverage=True), order, LIMITS.hpi_priority - order)
        if not self.tools.open_done(state):
            self.tools.questions.register(state, Question(item_id='ChiefComplaint:open', purpose='open_inquiry',
                text=self.tools.config.texts.open_question, order=1000, priority=LIMITS.open_inquiry_priority, coverage=True))
        return True

    def prepare(self, state):
        self.prepare_collection(state)

    def required_actions(self, state):
        return min(SESSION_INTERVIEW_LIMITS['ChiefComplaint'][0], sum(value == 'unasked' for value in self.tools.chief_statuses(state).values())
                   + int(not self.tools.open_done(state)))
