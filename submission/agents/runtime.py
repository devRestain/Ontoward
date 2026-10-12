from nova_sdk import Client
from knowledge.graph import ClinicalKnowledge
from settings import knowledge_manifest

from .gateway import InputGateway
from .interface import InterfaceAgent
from .resources import Resources
from .workflow import ConsultationWorkflow


def prepare() -> Resources:
    """The SDK calls ready() after this returns; do not access a case here."""
    return Resources(ClinicalKnowledge.load(knowledge_manifest()), InputGateway(), InterfaceAgent())


def consult(client: Client, resources: Resources):
    workflow = ConsultationWorkflow(client, resources)
    state = workflow.session.initialize_case(client)
    return workflow.compile().invoke(
        state.model_dump(), {"recursion_limit": workflow.session.graph_step_limit(state)}
    )
