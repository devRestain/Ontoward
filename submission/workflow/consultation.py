from nova_sdk import NovaError

from .rules.action import failure_outcome
from .rules.limits import LIMITS, SESSION_ORDER


class Consultation:
    def __init__(self, client, interpreter, doctor, planner, reasoner, writer, nova_session, budget, questions, interactions):
        self.client, self.interpreter, self.doctor = client, interpreter, doctor
        self.planner, self.reasoner, self.writer = planner, reasoner, writer
        self.nova_session, self.budget, self.questions, self.interactions = nova_session, budget, questions, interactions

    def enter_session(self, state):
        if state.session.termination or state.turn or state.interview.status == 'collecting':
            return
        state.interview.status = 'collecting'
        scope = state.interview.current
        if scope == 'Initiation':
            self.planner.prepare_initiation(state)
        elif scope == 'ChiefComplaint':
            if not self.planner.prepare_chief_complaint(state):
                state.interview.status = 'needs_preparation'
        elif scope in {'ContextFactor', 'DifferentialDiagnosis'}:
            self.planner.replan(state, force=True)
        else:
            self.interactions.skip_empathy(state, 'education_record_only')
            self.freeze_diagnosis(state)
            if not state.session.termination:
                if self.planner.config.education_enabled:
                    notice = self.doctor.prepare_diagnosis(state, self.client, self.planner.knowledge)
                    if notice or state.session.termination:
                        return
                self.planner.prepare_education(state, self.client)
                if self.planner.config.education_enabled and not state.session.termination:
                    self.doctor.prepare_education(state, self.client)

    def freeze_diagnosis(self, state):
        if state.case.diagnosis:
            return
        self.reasoner.select_diagnosis(state)
        if state.session.termination:
            return
        unresolved = []
        snapshot = self.reasoner.refresh_hypotheses(state)
        chosen = next((h for h in snapshot.hypotheses if self.reasoner.knowledge.term(h.disease_id) == state.case.diagnosis.name), None)
        if chosen and chosen.unresolved_conditions:
            unresolved.append('Diagnostic prerequisites remain unconfirmed')
        if any(s in {'unknown', 'blocked_asset', 'budget_stopped', 'recorded_unmapped'}
               for s in self.planner.chief_statuses(state).values()):
            unresolved.append('Chief complaint details remain incomplete')
        if not any(a.key and a.key[0] == 'EXAM' and a.outcome != 'undelivered' for a in state.interview.answers):
            unresolved.append('No additional physical examination obtained')
        if any(a.outcome in {'unsupported', 'unknown', 'conflict'} for a in state.interview.answers):
            unresolved.append('Some reported information remains unresolved in the admitted vocabulary')
        if any(f.binding == 'forced' for f in state.case.facts.values()):
            unresolved.append('Some patient facts use forced database approximations')
        state.case.diagnosis.unresolved = tuple(unresolved)

    def refresh_after_input(self, state):
        if state.session.termination or state.case.diagnosis:
            return
        self.reasoner.refresh_hypotheses(state)
        if state.interview.status == 'collecting':
            self.planner.replan(state)

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
                self.doctor.prepare_empathy(state, self.client, event)
                if state.turn or state.session.termination:
                    return
            else:
                self.interactions.skip_empathy(state, 'empathy_budget')
        self.planner.select_question(state)

    def advance_session(self, state):
        if state.turn or state.interview.queue:
            raise ValueError('Cannot advance an unfinished session')
        if state.interview.status == 'needs_preparation':
            self.enter_session(state)
            return
        if state.interview.current == 'Education':
            if self.planner.config.education_enabled and state.interview.education_status == 'not_started':
                state.interview.status = 'uninitialized'
            else:
                state.session.finalizing = True
        else:
            state.interview.current = SESSION_ORDER[SESSION_ORDER.index(state.interview.current) + 1]
            state.interview.status = 'uninitialized'

    def finalize(self, state):
        if state.session.termination:
            return
        self.freeze_diagnosis(state)
        if not state.session.termination:
            if self.planner.config.education_enabled:
                state.interview.current = 'Education'
            self.planner.prepare_education(state, self.client)
            self.questions.discard_unasked(state, {q.item_id for q in state.interview.queue}, reason='finalization_budget')
            self.writer.build_soap(state)

    def repair_submission(self, state):
        self.writer.begin_repair(state)
        self.writer.build_soap(state)

    def release(self):
        self.reasoner.clear()
        self.interpreter.dialogue.clear()
        self.interpreter.patient_context.clear()
