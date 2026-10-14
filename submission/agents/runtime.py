from knowledge.graph import ClinicalKnowledge
from settings import knowledge_manifest

from .config import TextConfig
from .gateway import InputGateway
from .interface import InterfaceAgent
from .resources import Resources
from .workflow import ConsultationWorkflow


def prepare() -> Resources:
    config = TextConfig.load()
    return Resources(ClinicalKnowledge.load(knowledge_manifest()), config, InputGateway(config), InterfaceAgent(config))


def consult(client, resources: Resources):
    workflow = ConsultationWorkflow(client, resources)
    state = workflow.session.initialize_case(client)
    result = workflow.compile().invoke(
        state.model_dump(), {"recursion_limit": workflow.session.graph_step_limit(state)}
    )
    outcome = result["interaction"]
    if outcome["termination"] != "submitted":
        raise RuntimeError(f"Consultation {outcome['termination']}: {outcome['reason']}")
    return result
