from ..rules.decision import prepare_decision, accept_ranking, rank_exchange
from ..rules.limits import LIMITS
from ..rules.collection import INTAKE, answered
from ..state.models import Question


class InitiationSession:
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

    def prepare(self, state):
        if not any(a.purpose == 'greeting' and a.outcome != 'undelivered' for a in state.interview.answers):
            self.tools.questions.register(state, Question(item_id='Initiation:greeting', purpose='greeting',
                text=self.tools.config.texts.greeting, order=-1, priority=LIMITS.clarification_priority, coverage=True))
            return
        if not self.tools.ensure_chief(state):
            return
        self.tools._prepare_common(state, INTAKE, self.tools.config.texts.intake_questions, 'intake')

    def required_actions(self, state):
        greeting = not any(a.purpose == 'greeting' and a.outcome != 'undelivered' for a in state.interview.answers)
        return int(greeting) + sum(not answered(state, slot) for slot in INTAKE)

