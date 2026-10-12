from nova_sdk import Client
from knowledge.graph import ClinicalKnowledge

from .state import CaseState, Update


class InputGateway:
    def ingest(self, state: CaseState, knowledge: ClinicalKnowledge, client: Client) -> Update:
        """Validate initial/action inputs and state updates before accepting evidence.

        Link short replies to pending_action; retain raw text, turn, episode,
        corrections, unsolicited facts, refusals, and unknown transmission outcomes.
        Clear pending_action only after processing its outcome; education replies
        remain in finalization. Never infer unasked negatives.
        """
        raise NotImplementedError("Normalize inputs and preserve observation provenance")
