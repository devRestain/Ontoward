from dataclasses import dataclass
from uuid import uuid4

from knowledge.graph import ClinicalKnowledge
from settings import knowledge_manifest

from .consultation import Consultation
from .doctor_mouth import DoctorMouth
from .graph import build_graph
from .doctor_ear import DoctorEar
from .doctor_brain import DoctorBrain
from .io.model_client import ModelClient
from .io.nova_session import NovaSessionClient
from .io.request_executor import RequestExecutor
from .rules.budget import BudgetPolicy, utc_now
from .state.interactions import InteractionLifecycle
from .state.questions import QuestionLifecycle
from .state.usage import UsageAccounting
from .submission_writer import SubmissionWriter
from .text_config import TextConfig


@dataclass(frozen=True)
class PreparedResources:
    knowledge: ClinicalKnowledge
    config: TextConfig


def prepare() -> PreparedResources:
    config = TextConfig.load()
    knowledge = ClinicalKnowledge.load(knowledge_manifest())
    if config.education_enabled and knowledge.guidelines is None:
        raise ValueError("Education requires a manifest-pinned guideline index")
    return PreparedResources(knowledge, config)


def assemble_consultation(client, resources, *, now=utc_now, sleep=None, new_request_id=None):
    new_request_id = new_request_id if new_request_id is not None else lambda: str(uuid4())
    budget = BudgetPolicy(now, education_enabled=resources.config.education_enabled, knowledge=resources.knowledge)
    usage = UsageAccounting()
    interactions = InteractionLifecycle(new_request_id)
    questions = QuestionLifecycle(interactions)
    executor = RequestExecutor(budget, sleep)
    nova_session = NovaSessionClient(executor, budget, usage, interactions)
    model = ModelClient(executor, budget, usage, new_request_id)
    ear = DoctorEar(resources.config, model, questions, interactions)
    mouth = DoctorMouth(executor, nova_session, usage, questions, interactions, model, resources.config, budget)
    brain = DoctorBrain(resources.knowledge, resources.config, questions, interactions, budget, usage, model)
    writer = SubmissionWriter(client, resources.knowledge, resources.config, executor, nova_session, new_request_id)
    return Consultation(client, ear, brain, mouth, writer, nova_session, budget, questions, interactions)



def consult(client, resources: PreparedResources):
    consultation = assemble_consultation(client, resources)
    state = consultation.nova_session.initialize_case(client)
    try:
        result = build_graph(consultation, resources.knowledge).invoke(
            state.model_dump(mode='json'), {'recursion_limit': consultation.budget.graph_step_limit(state)}
        )
        outcome = result['session']
        if outcome['termination'] != 'submitted':
            raise RuntimeError(f"Consultation {outcome['termination']}: {outcome['reason']}")
        return result
    finally:
        consultation.release()
