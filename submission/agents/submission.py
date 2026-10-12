from __future__ import annotations

from nova_sdk import Client

from .state import CaseState, Update


class SubmissionAgent:
    def __init__(self, client: Client):
        self.client = client

    def select_education(self, state: CaseState) -> Update:
        raise NotImplementedError("Select undelivered education if affordable, otherwise advance to soap")

    def render_soap(self, state: CaseState) -> Update:
        raise NotImplementedError("Render validated CaseState facts and plans; keep preliminary O.tests empty")

    def validate_submission(self, state: CaseState) -> Update:
        """Validate the SDK's 15 SOAP fields and a separate nonblank diagnosis.

        Keep preliminary O.tests empty and validate evidence and UTF-8 byte limits.
        """
        raise NotImplementedError("Validate SDK record fields, diagnosis, evidence, and byte limits")

    def submit_diagnosis(self, state: CaseState) -> Update:
        raise NotImplementedError("Recheck submission time and call client.diagnose with validated payload and request ID")

    def confirm_submission(self, state: CaseState) -> Update:
        raise NotImplementedError("Distinguish confirmed submission, failure, and unknown outcome")
