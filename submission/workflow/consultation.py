from nova_sdk import NovaError

from .rules.action import failure_outcome
from .rules.limits import LIMITS, SESSION_ORDER


class Consultation:
    def __init__(self, client, ear, brain, mouth, writer, nova_session, budget, questions, interactions):
        self.client, self.ear, self.brain, self.mouth, self.writer = client, ear, brain, mouth, writer
        self.nova_session, self.budget, self.questions, self.interactions = nova_session, budget, questions, interactions

    def enter_session(self, state):
        if state.session.termination or state.turn or state.interview.status == 'collecting':
            return
        state.interview.status = 'collecting'
        scope = state.interview.current
        if scope != 'Education':
            self.brain.replan(state,self.client,force=True)
        else:
            self.interactions.skip_empathy(state,'education_record_only')
            state.case.primary()
            if self.brain.config.education_enabled:
                notice = self.mouth.prepare_diagnosis(state,self.client,self.brain.knowledge)
                if notice or state.session.termination:
                    return
            self.brain.prepare_education(state,self.client)
            if self.brain.config.education_enabled and not state.session.termination:
                self.mouth.prepare_education(state,self.client)

    def refresh_after_input(self, state):
        if state.session.termination or state.case.assessment and state.case.assessment.frozen:
            return
        self.brain.replan(state,self.client)

    def close_collection(self, state):
        if state.turn:
            raise ValueError('Cannot close collection before input acceptance')
        self.brain.close_differential(state,self.client)

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
        self.brain.select_question(state)

    def advance_session(self, state):
        if state.turn or state.interview.queue:
            raise ValueError('Cannot advance an unfinished session')
        if state.interview.status == 'needs_preparation':
            self.enter_session(state)
            return
        if state.interview.current == 'Education':
            if self.brain.config.education_enabled and state.interview.education_status == 'not_started':
                state.interview.status = 'uninitialized'
            else:
                state.session.finalizing = True
        else:
            if state.interview.current == 'DifferentialDiagnosis':
                self.close_collection(state)
                if state.session.termination:
                    return
            state.interview.current = SESSION_ORDER[SESSION_ORDER.index(state.interview.current) + 1]
            state.interview.status = 'uninitialized'

    def finalize(self, state):
        if state.session.termination:
            return
        self.close_collection(state)
        if not state.session.termination:
            if self.brain.config.education_enabled:
                state.interview.current = 'Education'
            self.brain.prepare_education(state, self.client)
            self.questions.discard_unasked(state, {q.item_id for q in state.interview.queue}, reason='finalization_budget')
            self.writer.build_soap(state)

    def repair_submission(self, state):
        self.writer.begin_repair(state)
        self.writer.build_soap(state)

    def release(self):
        self.ear.dialogue.clear()
