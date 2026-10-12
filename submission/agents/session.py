from __future__ import annotations

from nova_sdk import Client

from .state import CaseState, Update


class SessionController:
    def initialize_case(self, client: Client) -> CaseState:
        raise NotImplementedError("Read client.session() and validate a fresh case with its initial input")

    def budget_guard(self, state: CaseState) -> Update:
        """Set continue/finalize/stop from authoritative session limits.

        Reserve time for the required Doctor call, record generation, and submission.
        Set termination on stop; preserve hpi_complete=False on forced interruption.
        Mark skipped pending education undelivered without rewriting delivered history.
        The same guard runs again after action rendering and validation.
        """
        raise NotImplementedError("Choose a bounded budget decision without fixed example quotas")

    def graph_step_limit(self, state: CaseState) -> int:
        # Graph steps exceed SDK turns, including steps that consume no interaction.
        raise NotImplementedError("Bound graph execution separately from the session's action budget")
