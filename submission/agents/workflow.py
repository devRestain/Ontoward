from functools import partial

from langgraph.graph import END, START, StateGraph
from nova_sdk import Client

from .interview import InterviewAgent
from .reasoning import ReasoningAgent
from .resources import Resources
from .routing import (
    finish, route_action_budget, route_budget, route_phase, route_selection,
    route_soap, route_submission,
)
from .session import SessionController
from .state import CaseState
from .submission import SubmissionAgent


class ConsultationWorkflow:
    def __init__(self, client: Client, resources: Resources):
        self.client = client
        self.resources = resources
        self.session = SessionController()
        self.interview = InterviewAgent(resources.knowledge)
        self.reasoning = ReasoningAgent(resources.knowledge, client)
        self.submission = SubmissionAgent(client)

    def compile(self):
        graph = StateGraph(CaseState)
        graph.add_node("gateway", partial(self.resources.gateway.ingest, knowledge=self.resources.knowledge, client=self.client))
        graph.add_node("budget", self.session.budget_guard)
        graph.add_node("route_phase", lambda state: {})
        graph.add_node("refresh", self.reasoning.refresh_hypotheses)
        graph.add_node("hpi", self.interview.fixed_hpi)
        graph.add_node("open_inquiry", self.interview.open_inquiry)
        graph.add_node("retrieval", self.reasoning.retrieve_candidates)
        graph.add_node("context", self.interview.collect_context)
        graph.add_node("investigation", self.interview.investigate)
        graph.add_node("synthesis", self.reasoning.synthesize)
        graph.add_node("education", self.submission.select_education)
        graph.add_node("render_action", partial(self.resources.interface.render, client=self.client))
        graph.add_node("validate_action", self.resources.interface.validate)
        graph.add_node("action_budget", self.session.budget_guard)
        graph.add_node("execute_action", partial(self.resources.interface.execute, client=self.client))
        graph.add_node("soap", self.submission.render_soap)
        graph.add_node("validate_submission", self.submission.validate_submission)
        graph.add_node("submit", self.submission.submit_diagnosis)
        graph.add_node("confirm_submission", self.submission.confirm_submission)
        graph.add_node("finish", finish)

        graph.add_edge(START, "gateway")
        graph.add_edge("gateway", "budget")
        graph.add_conditional_edges("budget", route_budget, {
            name: name for name in ("finish", "soap", "synthesis", "refresh", "route_phase")
        })
        graph.add_edge("refresh", "route_phase")
        graph.add_conditional_edges("route_phase", route_phase, {
            name: name for name in (
                "hpi", "open_inquiry", "retrieval", "context", "investigation",
                "synthesis", "education", "soap", "finish",
            )
        })
        for node in ("hpi", "open_inquiry", "retrieval", "context", "investigation", "synthesis", "education"):
            graph.add_conditional_edges(node, route_selection, {
                name: name for name in ("finish", "render_action", "route_phase")
            })
        graph.add_edge("render_action", "validate_action")
        graph.add_edge("validate_action", "action_budget")
        graph.add_conditional_edges("action_budget", route_action_budget, {
            name: name for name in ("finish", "soap", "synthesis", "execute_action")
        })
        graph.add_edge("execute_action", "gateway")
        graph.add_conditional_edges("soap", route_soap, {
            name: name for name in ("finish", "validate_submission")
        })
        graph.add_conditional_edges("validate_submission", route_submission, {
            name: name for name in ("finish", "submit")
        })
        graph.add_edge("submit", "confirm_submission")
        graph.add_edge("confirm_submission", "finish")
        graph.add_edge("finish", END)
        return graph.compile()
