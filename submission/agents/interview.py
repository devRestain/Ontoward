from __future__ import annotations

from knowledge.graph import ClinicalKnowledge

from .state import CaseState, Update


class InterviewAgent:
    def __init__(self, knowledge: ClinicalKnowledge):
        self.knowledge = knowledge

    def fixed_hpi(self, state: CaseState) -> Update:
        """Freeze each initial chief complaint's applicable slot order once.

        Skip resolved/unknown/not_applicable slots; preserve unresolved conflicts.
        Select one next_action or advance phase to open_inquiry after completion.
        """
        raise NotImplementedError("Process fixed slots without diagnostic ranking or early score exits")

    def open_inquiry(self, state: CaseState) -> Update:
        raise NotImplementedError("Ask for other symptoms, preserve timing, then advance to retrieval")

    def collect_context(self, state: CaseState) -> Update:
        raise NotImplementedError("Select useful unconfirmed context or advance to investigation")

    def investigate(self, state: CaseState) -> Update:
        raise NotImplementedError("Select a useful SAY/EXAM or advance to synthesis; retain reserve candidates")
