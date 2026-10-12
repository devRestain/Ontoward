from nova_sdk import Client

from .state import CaseState, Update


class InterfaceAgent:
    def render(self, state: CaseState, client: Client) -> Update:
        raise NotImplementedError("Render one Korean action using a template or designated Doctor")

    def validate(self, state: CaseState) -> Update:
        raise NotImplementedError("Validate one action and NFC length 1–30 without truncation")

    def execute(self, state: CaseState, client: Client) -> Update:
        """Call client.say/exam; move and clear next_action into pending_action.

        Retain the response for the gateway and update authoritative turn metadata.
        Preserve the same request ID and payload when transmission is uncertain.
        Do not fabricate a result from an expected finding or a rejected action.
        """
        raise NotImplementedError("Execute an SDK action and return input to the common gateway")
