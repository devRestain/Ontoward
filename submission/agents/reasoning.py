from __future__ import annotations

from nova_sdk import Client
from knowledge.graph import ClinicalKnowledge

from .state import CaseState, Update


class ReasoningAgent:
    def __init__(self, knowledge: ClinicalKnowledge, client: Client):
        self.knowledge = knowledge
        self.client = client

    def retrieve_candidates(self, state: CaseState) -> Update:
        """Mark candidates_initialized after retrieval even if its result is empty."""
        raise NotImplementedError("Union finding-linked diseases, partially match, and advance to context")

    def refresh_hypotheses(self, state: CaseState) -> Update:
        """Re-evaluate active and reserve candidates from deduplicated current evidence.

        Refresh recall for new/corrected findings; use capped positive-only context.
        Preserve the current phase and clear evidence_changed after updating.
        """
        raise NotImplementedError("Recompute relative support without cumulative boosts or probabilities")

    def synthesize(self, state: CaseState) -> Update:
        """Review support, contradictions, unexplained findings, and plans.

        Handle forced entry before initial retrieval using only available evidence.
        Ensure at least one successful client.chat() per case, without fake call counts.
        Re-evaluate final evidence, clear evidence_changed and stale next_action,
        preserve incomplete HPI, and advance to education.
        Failure to form a valid submission must remain an explicit termination result.
        """
        raise NotImplementedError("Draft one diagnosis and plans without inventing evidence")
