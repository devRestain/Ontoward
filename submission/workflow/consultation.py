from nova_sdk import NovaError

from .rules.limits import FIXED_UTTERANCES, LIMITS, SESSION_ORDER
from .rules.chief import force_chief


class Consultation:
    def __init__(self, client, ear, brain, mouth, writer, nova_session, budget, questions, interactions,
                 knowledge, config, tools, sessions):
        self.client, self.ear, self.brain, self.mouth, self.writer = client, ear, brain, mouth, writer
        self.nova_session, self.budget, self.questions, self.interactions = nova_session, budget, questions, interactions
        self.knowledge, self.config, self.tools, self.sessions = knowledge, config, tools, sessions
        self.differential = sessions['DifferentialDiagnosis']

    @staticmethod
    def error_reason(error):
        return getattr(error, 'code', type(error).__name__ + ': ' + str(error))[:500]

    def accept_input(self, state):
        try:
            self.ear.process_input(state, self.knowledge, self.client)
        except Exception as error:
            self.questions.pass_step(state, self.error_reason(error), operation=state.interview.current + ':input')
        try:
            self.refresh_after_input(state)
        except Exception as error:
            self.pass_session(state, error)

    def run(self, state):
        self.accept_input(state)
        if state.interview.current == 'Initiation':
            self.deliver_fixed(state, 'opening')
        while state.session.termination != 'submitted':
            if state.session.termination:
                # Actual expiry/closure prevents transmission, but never discards the result.
                self.finalize(state, allow_model=False)
                break
            try:
                self.check_budget(state)
            except Exception as error:
                state.interview.collection['budget:failure'] = self.error_reason(error)
                state.session.finalizing = True
            if state.session.finalizing or state.session.termination:
                self.finalize(state, allow_model=not bool(state.session.termination or state.session.budget_sync_required))
                self.finish_submission(state)
                break
            try:
                if state.interview.status == 'uninitialized':
                    self.enter_session(state)
                elif state.interview.queue:
                    self.select_action(state)
                    self.mouth.validate_action(state)
                    if state.turn and state.turn.stage == 'ready':
                        self.mouth.execute_action(state, self.client)
                    if state.turn and state.turn.stage == 'received':
                        self.accept_input(state)
                else:
                    self.advance_session(state)
            except Exception as error:
                if state.turn and state.turn.kind in {'action', 'initial'}:
                    self.questions.pass_step(state, self.error_reason(error), operation=state.interview.current + ':action')
                else:
                    self.pass_session(state, error)
        return state

    def deliver_fixed(self, state, phase):
        for number, text in enumerate(FIXED_UTTERANCES[phase]):
            self.mouth.execute_fixed(state, self.client, f'{phase}:{number}', text)

    def pass_session(self, state, error):
        scope = state.interview.current
        reason = self.error_reason(error)
        state.interview.collection[scope + ':completion'] = reason
        if state.turn:
            self.questions.pass_step(state, reason, operation=scope + ':pass')
        # Close each unasked item once, retaining its complete semantic scope.
        for question in list(state.interview.queue):
            from .state.models import TurnContext
            state.turn = TurnContext(kind='action', question_id=question.item_id, stage='selected')
            self.questions.pass_step(state, reason)
        session = self.sessions[scope]
        if hasattr(session, 'closed'):
            session.closed = True
            session.error = reason
        if scope in {'DifferentialDiagnosis', 'Education'}:
            if scope == 'Education' and state.interview.education_status == 'not_started':
                state.interview.education_status = 'failed'
                state.interview.education_reason = reason
            state.session.finalizing = True
        else:
            state.interview.current = SESSION_ORDER[SESSION_ORDER.index(scope) + 1]
            state.interview.status = 'uninitialized'

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
        self.prepare_session(state)

    def prepare_session(self, state):
        current = state.interview.current
        if current == 'ContextFactor':
            session = self.sessions[current]
            specs = session.context_specs(state)
            self.budget.required_counts = {current: session.required_actions(state, specs=specs)}
            session.prepare(state, specs=specs)
            return
        self.refresh_requirements(state)
        if current in {'DifferentialDiagnosis', 'Education'}:
            self.sessions[current].prepare(state, self.client)
        else:
            self.sessions[current].prepare(state)

    def refresh_requirements(self, state):
        scope = state.interview.current
        session = self.sessions[scope]
        self.budget.required_counts = {scope: session.required_actions(state)} if hasattr(session, 'required_actions') else {}

    def refresh_after_input(self, state):
        if state.session.termination or state.case.assessment and state.case.assessment.frozen:
            return
        if state.interview.status == 'collecting' and not state.turn:
            self.prepare_session(state)

    def close_collection(self, state, *, allow_model=True):
        if state.turn and state.turn.kind != 'submission':
            self.questions.pass_step(state, 'pending_action_at_finalization')
        if not state.case.collection_chief():
            try:
                if allow_model and not state.session.budget_sync_required and not state.session.termination:
                    self.tools.chief_fallback(state)
                else:
                    force_chief(state, self.knowledge, self.config)
            except Exception as error:
                state.interview.collection['chief:failure'] = self.error_reason(error)
        try:
            self.differential.close(state, self.client, allow_model=allow_model)
        except Exception as error:
            reason = self.error_reason(error)
            state.interview.collection['DifferentialDiagnosis:close'] = reason
            try:
                self.differential.freeze_fallback(state, reason)
            except Exception as fallback_error:
                self.differential.freeze_problem(state, self.error_reason(fallback_error))

    def check_budget(self, state):
        if state.session.termination:
            return
        if state.session.budget_sync_required:
            if self.budget.seconds_left(state.session) > state.session.reserve_seconds + LIMITS.response_seconds:
                try:
                    self.nova_session.refresh_snapshot(state, self.client)
                except (NovaError, TypeError, ValueError) as error:
                    state.interview.collection['budget:sync'] = self.error_reason(error)
            if state.session.budget_sync_required:
                # Do not repeatedly GET or spend resources with unconfirmed consumption.
                state.session.finalizing = True
                return
        self.refresh_requirements(state)
        decision = self.budget.evaluate(state)
        if decision.expired:
            state.stop('expired', 'session_expired')
            state.session.finalizing = True
            return
        if decision.finalize:
            state.interview.collection[f'{state.interview.current}:completion'] = decision.reason
            if state.turn:
                self.questions.pass_step(state, decision.reason)
            self.questions.discard_unasked(state, decision.discard, reason=decision.reason)
            if state.interview.current != 'Education':
                self.close_collection(state)
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
        self.tools.select_question(state)

    def advance_session(self, state):
        if state.turn or state.interview.queue:
            raise ValueError('Cannot advance an unfinished session')
        if state.interview.status == 'needs_preparation':
            self.enter_session(state)
            return
        scope = state.interview.current
        if scope == 'Education':
            if self.config.education_enabled and state.interview.education_status == 'not_started':
                state.interview.status = 'uninitialized'
            else:
                state.session.finalizing = True
        else:
            if scope == 'DifferentialDiagnosis':
                self.close_collection(state)
            else:
                try:
                    self.sessions[scope].close(state, self.client)
                except Exception as error:
                    state.interview.collection[scope + ':decision'] = self.error_reason(error)
                    self.sessions[scope].error = self.error_reason(error)
            state.interview.current = SESSION_ORDER[SESSION_ORDER.index(scope) + 1]
            state.interview.status = 'uninitialized'

    def finalize(self, state, *, allow_model=True):
        if state.session.termination == 'submitted' or state.turn and state.turn.kind == 'submission':
            return
        self.close_collection(state, allow_model=allow_model)
        try:
            if self.config.education_enabled and not state.session.termination:
                state.interview.current = 'Education'
                self.sessions['Education'].prepare_plan(state, self.client)
        except Exception as error:
            state.interview.education_status = 'partial' if state.case.plan else 'failed'
            state.interview.education_reason = self.error_reason(error)
        self.questions.discard_unasked(state, {q.item_id for q in state.interview.queue}, reason='finalization_budget')
        self.deliver_fixed(state, 'closing')
        try:
            self.writer.build_soap(state)
        except Exception as error:
            self.writer.build_minimal(state, self.error_reason(error))

    def finish_submission(self, state):
        if state.session.termination:
            return
        for attempt in range(LIMITS.submission_repairs + 1):
            try:
                try:
                    self.writer.validate_submission(state)
                except Exception as error:
                    self.writer.build_minimal(state, self.error_reason(error))
                if state.turn.error:
                    self.writer.build_minimal(state, state.turn.error)
                self.writer.submit_diagnosis(state)
                if state.session.termination:
                    return
                if state.turn.error == 'INVALID_RECORD_FIELDS' and attempt < LIMITS.submission_repairs:
                    self.repair_submission(state)
                    continue
                self.writer.confirm_submission(state)
            except Exception as error:
                if state.session.termination == 'submitted':
                    return
                if state.turn:
                    state.turn.error = self.error_reason(error)
                state.stop('unknown', self.error_reason(error))
            return

    def repair_submission(self, state):
        self.writer.begin_repair(state)
        self.writer.build_minimal(state, 'confirmed_record_rejection')

    def release(self):
        self.ear.dialogue.clear()
