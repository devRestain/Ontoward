from .rules.limits import SESSION_ORDER
from .state.models import FixedDiagnosis, WorkflowState


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
        return self.planner.prepare_chief_complaint(state)

    def prepare_context_factors(self, state):
        self.reasoner.retrieve_candidates(state)
        self.planner.prepare_context_questions(state)
        return True

    def prepare_differential_diagnosis(self, state):
        self.reasoner.refresh_hypotheses(state)
        self.planner.prepare_differential_questions(state)
        return True

    def prepare_education(self, state):
        self.interactions.skip_empathy(state, "education_record_only")
        self.reasoner.select_diagnosis(state)
        if not state.interaction.termination:
            self.freeze_diagnosis(state)
            self.planner.prepare_education(state, self.client)
            if self.planner.config.education_enabled and not state.interaction.termination:
                self.doctor.prepare_education(state, self.client)
        return True

    def freeze_diagnosis(self, state):
        if self.planner.config.education_enabled and not state.case.fixed_diagnosis:
            unresolved = []
            chosen = next((h for h in state.differential.hypotheses if h.disease_id == state.differential.selected_id), None)
            if chosen and chosen.unresolved_conditions:
                unresolved.append("Diagnostic prerequisites remain unconfirmed")
            if any(s in {"unknown", "blocked_asset", "budget_stopped", "recorded_unmapped"} for s in state.questions.chief_attributes.values()):
                unresolved.append("Chief complaint details remain incomplete")
            if not any(e.delivered and e.kind == "EXAM" for e in state.interaction.history):
                unresolved.append("No additional physical examination obtained")
            if any(outcome.state in {"unsupported", "unknown", "conflict"} for outcome in state.case.outcomes):
                unresolved.append("Some reported information remains unresolved in the admitted vocabulary")
            if any(outcome.state == "forced" for outcome in state.case.outcomes):
                unresolved.append("Some patient facts use forced database approximations")
            state.case.fixed_diagnosis = FixedDiagnosis(kind=state.case.diagnosis_kind,
                disease_id=state.differential.selected_id, name=state.case.diagnosis,
                evidence_ids=list(state.case.diagnosis_evidence), unresolved=unresolved)

    def refresh_after_input(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        if state.case.fixed_diagnosis:
            self.interactions.consume_clarification(state)
            return
        if state.session.current == "ChiefComplaint" and self.planner.open_done(state):
            state.differential.initialized = True
        self.reasoner.refresh_hypotheses(state)
        delivered = next((entry for entry in reversed(state.interaction.history)
                          if entry.delivered and entry.question and entry.question.assessment), None)
        if delivered and "observed_after" not in delivered.question.assessment:
            supported = {h.disease_id for h in self.reasoner.supported_hypotheses(state)}
            delivered.question.assessment["observed_after"] = {
                h.disease_id: {"score": h.score, "chief_score": h.chief_score,
                              "eligible": h.disease_id in supported}
                for h in state.differential.hypotheses}
        self.interactions.consume_clarification(state)
        self.planner.replan(state)

    def check_budget(self, state: WorkflowState) -> None:
        decision = self.budget.evaluate(state)
        if decision.expired:
            self.interactions.skip_empathy(state, "session_expired")
            state.stop("expired", "session_expired")
            return
        if decision.finalize:
            self.interactions.skip_empathy(state, "finalization_budget")
            state.session.finalizing = True
            self.interactions.clear_selected(state)
        self.questions.discard_unasked(state, decision.discard)

    def select_action(self, state: WorkflowState) -> None:
        if state.session.current == "Education":
            self.interactions.skip_empathy(state, "education_record_only")
        event = self.interactions.pending_empathy(state)
        greeting_due = state.session.current == "Initiation" and not any(
            entry.delivered and entry.question and entry.question.purpose == "greeting" for entry in state.interaction.history)
        if event and not greeting_due and state.session.current != "Education":
            if self.budget.can_empathize(state):
                self.doctor.prepare_empathy(state, self.client, event)
                if state.interaction.selected or state.interaction.termination:
                    return
            else:
                self.interactions.skip_empathy(state, "empathy_budget", event.source_id)
        self.planner.select_question(state)

    def advance_session(self, state: WorkflowState) -> None:
        if not state.session.initialized or state.interaction.pending or state.unasked():
            raise ValueError("Cannot advance an unfinished session")
        if not state.session.questions_prepared:
            self.prepare_session(state)
            return
        if state.session.current in {"ContextFactor", "DifferentialDiagnosis"}:
            self.reasoner.refresh_hypotheses(state)
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
            self.freeze_diagnosis(state)
            if self.planner.config.education_enabled:
                state.session.current = "Education"
            self.planner.prepare_education(state, self.client)
            self.questions.discard_unasked(state, {item.id for item in state.questions.education if item.status == "pending"})
            self.writer.build_soap(state)

    def repair_submission(self, state: WorkflowState) -> None:
        self.writer.begin_repair(state)
        self.finalize(state)
