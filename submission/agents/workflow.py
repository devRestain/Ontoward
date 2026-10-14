from functools import partial

from langgraph.graph import END, START, StateGraph

from .interview import InterviewAgent
from .reasoning import ReasoningAgent
from .resources import Resources
from .routing import (abort, finish, route_action_budget, route_after_submit, route_budget,
                      route_confirmation, route_soap, route_submission, route_validation)
from .session import SessionController
from .state import WorkflowState
from .submission import SubmissionAgent


class ConsultationWorkflow:
    def __init__(self, client, resources: Resources):
        self.client = client
        self.resources = resources
        self.session = SessionController()
        self.interview = InterviewAgent(resources.knowledge, resources.config)
        self.reasoning = ReasoningAgent(resources.knowledge)
        self.submission = SubmissionAgent(client, resources.knowledge, resources.config)

    @staticmethod
    def _node(state: WorkflowState, operation):
        updated = state.model_copy(deep=True)
        operation(updated)
        return WorkflowState.model_validate(updated.model_dump()).model_dump()

    def enter_scope(self, state: WorkflowState) -> None:
        if state.interaction.termination or state.session.initialized or state.interaction.pending:
            return
        state.session.initialized = True
        self.prepare_questions(state)
        if state.session.current != "Initiation" and state.interaction.needs_clarification:
            if state.session.questions_prepared:
                self.interview.clarify(state, state.interaction.clarification_target)
            state.interaction.needs_clarification = False
            state.interaction.clarification_target = None

    def prepare_questions(self, state: WorkflowState) -> None:
        scope = state.session.current
        if scope == "Initiation":
            self.interview.initiation(state)
        elif scope == "ChiefComplaint":
            if not state.case.chief_complaints():
                if self.interview.clarify(state):
                    return
                state.stop("failed", "no_supported_chief_complaint")
                return
            self.interview.fixed_hpi(state)
        elif scope == "ContextFactor":
            self.reasoning.retrieve_candidates(state)
            if not state.differential.hypotheses and self.interview.clarify(state):
                return
            self.interview.collect_context(state)
        elif scope == "DifferentialDiagnosis":
            self.reasoning.refresh_hypotheses(state, score_context=True)
            self.interview.investigate(state)
        else:
            self.reasoning.select_diagnosis(state)
            if not state.interaction.termination:
                self.interview.prepare_education(state)
        state.session.questions_prepared = True

    def refresh(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        previous = (state.case.diagnosis_kind, state.case.diagnosis)
        self.reasoning.refresh_hypotheses(state)
        interaction = state.interaction
        if state.session.current != "Initiation" and interaction.needs_clarification:
            self.interview.clarify(state, interaction.clarification_target)
            interaction.needs_clarification = False
            interaction.clarification_target = None
        if state.session.current == "Education" and state.session.initialized:
            self.reasoning.select_diagnosis(state)
            if not interaction.termination and previous != (state.case.diagnosis_kind, state.case.diagnosis):
                self.interview.prepare_education(state, replace=True)

    def advance(self, state: WorkflowState) -> None:
        if not state.session.initialized or state.interaction.pending or state.case.unasked(state.session.current):
            raise ValueError("Cannot advance an unfinished scope")
        if not state.session.questions_prepared:
            self.prepare_questions(state)
            return
        scope = state.session.current
        if scope in {"ContextFactor", "DifferentialDiagnosis"}:
            self.reasoning.refresh_hypotheses(state, score_context=True)
            if not state.differential.hypotheses and self.interview.clarify(state):
                return
        if state.interaction.termination:
            return
        self.session.advance_scope(state)

    def finalize(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        self.reasoning.select_diagnosis(state)
        if not state.interaction.termination:
            self.interview.prepare_education(state, create_questions=False)
            self.submission.render_soap(state)

    def repair_submission(self, state: WorkflowState) -> None:
        state.interaction.submission_repairs += 1
        state.interaction.submission_request_id = None
        state.interaction.submission_result = None
        state.interaction.submission_error = None
        self.finalize(state)

    def compile(self):
        graph = StateGraph(WorkflowState)
        operations = {
            "gateway": partial(self.resources.gateway.ingest, knowledge=self.resources.knowledge, client=self.client),
            "refresh": self.refresh, "enter": self.enter_scope, "budget": self.session.budget_guard,
            "select": self.interview.select_question,
            "render": partial(self.resources.interface.render, client=self.client),
            "validate": self.resources.interface.validate, "action_budget": self.session.budget_guard,
            "execute": partial(self.resources.interface.execute, client=self.client), "advance": self.advance,
            "soap": self.finalize, "validate_submission": self.submission.validate_submission,
            "repair_submission": self.repair_submission, "submit": self.submission.submit_diagnosis,
            "confirm_submission": self.submission.confirm_submission, "finish": finish, "abort": abort,
        }
        for name, operation in operations.items():
            graph.add_node(name, partial(self._node, operation=operation))
        graph.add_edge(START, "gateway")
        graph.add_edge("gateway", "refresh")
        graph.add_edge("refresh", "budget")
        graph.add_edge("enter", "budget")
        graph.add_conditional_edges("budget", route_budget, {key: key for key in ("abort", "gateway", "soap", "enter", "select", "advance")})
        graph.add_edge("select", "render")
        graph.add_edge("render", "validate")
        graph.add_conditional_edges("validate", route_validation, {key: key for key in ("abort", "render", "budget", "action_budget")})
        graph.add_conditional_edges("action_budget", route_action_budget,
                                    {key: key for key in ("abort", "gateway", "soap", "enter", "advance", "execute", "budget")})
        graph.add_edge("execute", "gateway")
        graph.add_edge("advance", "budget")
        graph.add_conditional_edges("soap", route_soap, {key: key for key in ("abort", "validate_submission")})
        graph.add_conditional_edges("validate_submission", route_submission, {key: key for key in ("abort", "repair_submission", "submit")})
        graph.add_edge("repair_submission", "validate_submission")
        graph.add_conditional_edges("submit", route_after_submit, {key: key for key in ("repair_submission", "confirm_submission")})
        graph.add_conditional_edges("confirm_submission", route_confirmation, {"finish": "finish", "abort": "abort"})
        graph.add_edge("finish", END)
        graph.add_edge("abort", END)
        return graph.compile()
