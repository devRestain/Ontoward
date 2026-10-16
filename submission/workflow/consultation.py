from .rules.limits import SESSION_ORDER
from .state.models import WorkflowState


class Consultation:
    def __init__(self, client, interpreter, doctor, planner, reasoner, writer, nova_session, budget, questions, interactions):
        self.client = client
        self.interpreter = interpreter
        self.doctor = doctor
        self.planner = planner
        self.reasoner = reasoner
        self.writer = writer
        self.nova_session = nova_session
        self.budget = budget
        self.questions = questions
        self.interactions = interactions

    def enter_session(self, state: WorkflowState) -> None:
        if state.interaction.termination or state.session.initialized or state.interaction.pending:
            return
        state.session.initialized = True
        self.prepare_session(state)
        if state.session.current != "Initiation" and state.interaction.needs_clarification:
            if state.session.questions_prepared:
                self.planner.prepare_clarification(state, state.interaction.clarification_target)
            self.interactions.consume_clarification(state)

    def prepare_session(self, state: WorkflowState) -> None:
        prepare = {
            "Initiation": self.prepare_initiation,
            "ChiefComplaint": self.prepare_chief_complaint,
            "ContextFactor": self.prepare_context_factors,
            "DifferentialDiagnosis": self.prepare_differential_diagnosis,
            "Education": self.prepare_education,
        }[state.session.current]
        if prepare(state):
            state.session.questions_prepared = True

    def prepare_initiation(self, state):
        self.planner.prepare_initiation(state)
        return True

    def prepare_chief_complaint(self, state):
        if not state.case.chief_complaints():
            if not self.planner.prepare_clarification(state):
                state.stop("failed", "no_supported_chief_complaint")
            return False
        self.planner.prepare_chief_complaint(state)
        return True

    def prepare_context_factors(self, state):
        self.reasoner.retrieve_candidates(state)
        if not state.differential.hypotheses and self.planner.prepare_clarification(state):
            return False
        self.planner.prepare_context_questions(state)
        return True

    def prepare_differential_diagnosis(self, state):
        self.reasoner.refresh_hypotheses(state, score_context=True)
        self.planner.prepare_differential_questions(state)
        return True

    def prepare_education(self, state):
        self.reasoner.select_diagnosis(state)
        if not state.interaction.termination:
            self.planner.prepare_education(state)
        return True

    def refresh_after_input(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        previous = (state.case.diagnosis_kind, state.case.diagnosis)
        if state.session.current == "ChiefComplaint" and self.planner.open_done(state):
            state.differential.initialized = True
        self.reasoner.refresh_hypotheses(state)
        interaction = state.interaction
        if state.session.current != "Initiation" and interaction.needs_clarification:
            self.planner.prepare_clarification(state, interaction.clarification_target)
            self.interactions.consume_clarification(state)
        if state.session.current == "Education" and state.session.initialized:
            self.reasoner.select_diagnosis(state)
            if not interaction.termination and previous != (state.case.diagnosis_kind, state.case.diagnosis):
                interaction.diagnosis_revision += 1
                if interaction.explained_revision >= 0:
                    interaction.correction_required = True
                self.planner.prepare_education(state, replace=True)
        else:
            self.planner.replan(state)

    def check_budget(self, state: WorkflowState) -> None:
        decision = self.budget.evaluate(state)
        if decision.expired:
            state.stop("expired", "session_expired")
            return
        if decision.finalize:
            state.session.finalizing = True
            self.interactions.clear_selected(state)
        self.questions.discard_unasked(state, decision.discard)

    def advance_session(self, state: WorkflowState) -> None:
        if not state.session.initialized or state.interaction.pending or state.case.unasked(state.session.current):
            raise ValueError("Cannot advance an unfinished session")
        if not state.session.questions_prepared:
            self.prepare_session(state)
            return
        if state.session.current in {"ContextFactor", "DifferentialDiagnosis"}:
            self.reasoner.refresh_hypotheses(state, score_context=True)
            if not state.differential.hypotheses and self.planner.prepare_clarification(state):
                return
        if state.interaction.termination:
            return
        if state.session.current == "Education":
            state.session.finalizing = True
        else:
            state.session.current = SESSION_ORDER[SESSION_ORDER.index(state.session.current) + 1]
            state.session.initialized = False
            state.session.questions_prepared = False
            self.questions.clear_session_references(state)

    def finalize(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        self.reasoner.select_diagnosis(state)
        if not state.interaction.termination:
            self.planner.prepare_education(state, create_questions=False)
            self.writer.build_soap(state)

    def repair_submission(self, state: WorkflowState) -> None:
        self.writer.begin_repair(state)
        self.finalize(state)
