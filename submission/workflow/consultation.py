from nova_sdk import NovaError

from .rules.action import failure_outcome
from .rules.limits import LIMITS, SESSION_ORDER


class Consultation:
    def __init__(self, client, ear, brain, mouth, writer, nova_session, budget, questions, interactions,
                 knowledge, config, tools, sessions):
        self.client, self.ear, self.brain, self.mouth, self.writer = client, ear, brain, mouth, writer
        self.nova_session, self.budget, self.questions, self.interactions = nova_session, budget, questions, interactions
        self.knowledge, self.config, self.tools, self.sessions = knowledge, config, tools, sessions
        self.differential = sessions['DifferentialDiagnosis']

    def enter_session(self, state):
        if state.session.termination or state.turn or state.interview.status == 'collecting':
            return
        state.interview.status = 'collecting'
        scope = state.interview.current
        if scope == 'ContextFactor':
            chief = self.sessions['ChiefComplaint']
            assessment = state.case.assessment
            if (not chief.closed or chief.error or assessment is None or assessment.frozen
                    or (assessment.based_on_case_revision, assessment.based_on_chief_fact_id) != (
                        state.case.revision, state.case.chief_fact_id)):
                assessment = None
            self.sessions[scope].enter(state, assessment)
        if scope == 'Education':
            self.interactions.skip_empathy(state,'education_record_only')
        self.prepare_session(state)

    def prepare_session(self, state):
        current = state.interview.current
        if current in {'DifferentialDiagnosis', 'Education'}:
            self.sessions[current].prepare(state, self.client)
        else:
            self.sessions[current].prepare(state)

    def refresh_after_input(self, state):
        if state.session.termination or state.case.assessment and state.case.assessment.frozen:
            return
        if state.interview.status == 'collecting' and not state.turn:
            self.prepare_session(state)

    def close_collection(self, state):
        if state.turn:
            raise ValueError('Cannot close collection before input acceptance')
        self.differential.close(state,self.client)

    def check_budget(self, state):
        if state.session.termination:
            return
        if self.budget.seconds_left(state.session) > state.session.reserve_seconds + LIMITS.response_seconds:
            try:
                self.nova_session.refresh_snapshot(state, self.client)
            except NovaError as error:
                state.stop(failure_outcome(error), error.code)
            except (TypeError, ValueError):
                state.stop('unknown', 'invalid_session_budget')
            if state.session.termination:
                return
        decision = self.budget.evaluate(state)
        if decision.expired:
            self.interactions.skip_empathy(state, 'session_expired')
            state.stop('expired', 'session_expired')
            return
        if decision.finalize:
            self.interactions.skip_empathy(state, 'finalization_budget')
            state.interview.collection[f'{state.interview.current}:completion'] = decision.reason
            self.interactions.clear_selected(state)
            self.questions.discard_unasked(state, decision.discard, reason=decision.reason)
            if state.interview.current != 'Education':
                self.close_collection(state)
                if state.session.termination:
                    return
                previous = state.interview.current
                state.interview.current = 'Education'
                if self.budget.education_available(state):
                    state.session.finalizing = False
                    state.interview.status = 'uninitialized'
                    return
                state.interview.current = previous
            state.session.finalizing = True
        self.questions.discard_unasked(state, decision.discard)

    def select_action(self, state):
        if state.interview.current == 'Education':
            self.interactions.skip_empathy(state, 'education_record_only')
        event = state.interview.empathy
        greeting_due = state.interview.current == 'Initiation' and not any(
            a.purpose == 'greeting' and a.outcome != 'undelivered' for a in state.interview.answers)
        if event and not greeting_due and state.interview.current != 'Education':
            if self.budget.can_empathize(state):
                self.mouth.prepare_empathy(state, self.client, event)
                if state.turn or state.session.termination:
                    return
            else:
                self.interactions.skip_empathy(state, 'empathy_budget')
        self.tools.select_question(state)

    def advance_session(self, state):
        if state.turn or state.interview.queue:
            raise ValueError('Cannot advance an unfinished session')
        if state.interview.status == 'needs_preparation':
            self.enter_session(state)
            return
        if state.interview.current == 'Education':
            if self.config.education_enabled and state.interview.education_status == 'not_started':
                state.interview.status = 'uninitialized'
            else:
                state.session.finalizing = True
        else:
            if state.interview.current == 'DifferentialDiagnosis':
                self.close_collection(state)
                if state.session.termination:
                    return
            else:
                self.sessions[state.interview.current].close(state, self.client)
                if state.session.termination:
                    return
            state.interview.current = SESSION_ORDER[SESSION_ORDER.index(state.interview.current) + 1]
            state.interview.status = 'uninitialized'

    def finalize(self, state):
        if state.session.termination:
            return
        self.close_collection(state)
        if not state.session.termination:
            if self.config.education_enabled:
                state.interview.current = 'Education'
            self.sessions['Education'].prepare_plan(state, self.client)
            self.questions.discard_unasked(state, {q.item_id for q in state.interview.queue}, reason='finalization_budget')
            self.writer.build_soap(state)

    def repair_submission(self, state):
        self.writer.begin_repair(state)
        self.writer.build_soap(state)

    def release(self):
        self.ear.dialogue.clear()
