from dataclasses import dataclass
from uuid import uuid4

from knowledge.graph import ClinicalKnowledge
from settings import knowledge_manifest

from .clinical_reasoner import ClinicalReasoner
from .consultation import Consultation
from .doctor import Doctor
from .graph import build_graph
from .input_interpreter import InputInterpreter
from .interview_planner import InterviewPlanner
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
    return PreparedResources(ClinicalKnowledge.load(knowledge_manifest()), config)


def assemble_consultation(client, resources, *, now=utc_now, sleep=None, new_request_id=None):
    new_request_id = new_request_id if new_request_id is not None else lambda: str(uuid4())
    budget = BudgetPolicy(now, education_enabled=resources.config.education_enabled)
    usage = UsageAccounting()
    interactions = InteractionLifecycle(new_request_id)
    questions = QuestionLifecycle(resources.config, interactions)
    executor = RequestExecutor(budget, sleep)
    nova_session = NovaSessionClient(executor, budget, usage, interactions)
    model = ModelClient(executor, budget, usage, new_request_id)
    interpreter = InputInterpreter(resources.config, model, questions, interactions)
    doctor = Doctor(executor, nova_session, usage, questions, interactions, new_request_id)
    planner = InterviewPlanner(resources.knowledge, resources.config, questions, interactions, budget, usage)
    reasoner = ClinicalReasoner(resources.knowledge)
    writer = SubmissionWriter(client, resources.knowledge, resources.config, executor, nova_session, interactions, new_request_id)
    return Consultation(client, interpreter, doctor, planner, reasoner, writer, nova_session, budget, questions, interactions)


def consult(client, resources: PreparedResources):
    consultation = assemble_consultation(client, resources)
    state = consultation.nova_session.initialize_case(client)
    result = build_graph(consultation, resources.knowledge).invoke(
        state.model_dump(), {"recursion_limit": consultation.budget.graph_step_limit(state)}
    )
    outcome = result["interaction"]
    if outcome["termination"] != "submitted":
        raise RuntimeError(f"Consultation {outcome['termination']}: {outcome['reason']}")
    return result
