from dataclasses import dataclass
from uuid import uuid4

from knowledge.graph import ClinicalKnowledge
from settings import knowledge_manifest

from .consultation import Consultation
from .doctor_mouth import DoctorMouth
from .doctor_ear import DoctorEar
from .doctor_brain import DoctorBrain
from .io.nova_session import NovaSessionClient
from .io.request_executor import RequestExecutor
from .rules.budget import BudgetPolicy, utc_now
from .rules.questions import QuestionTools
from .sessions.initiation import InitiationSession
from .sessions.chief_complaint import ChiefComplaintSession
from .sessions.context_factor import ContextFactorSession
from .sessions.differential_diagnosis import DifferentialDiagnosisSession
from .sessions.education import EducationSession
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
    budget = BudgetPolicy(now, education_enabled=resources.config.education_enabled)
    usage = UsageAccounting()
    interactions = InteractionLifecycle(new_request_id)
    questions = QuestionLifecycle(interactions)
    executor = RequestExecutor(budget, sleep)
    nova_session = NovaSessionClient(executor, budget, usage, interactions)
    brain = DoctorBrain(executor, budget, usage, new_request_id)
    ear = DoctorEar(resources.config, brain, questions, interactions)
    mouth = DoctorMouth(executor, nova_session, usage, questions, interactions, brain, resources.config, budget)
    tools = QuestionTools(resources.knowledge, resources.config, questions, interactions, budget, usage)
    args = (resources.knowledge, resources.config, tools, brain)
    sessions = dict(Initiation=InitiationSession(*args), ChiefComplaint=ChiefComplaintSession(*args),
        ContextFactor=ContextFactorSession(*args), DifferentialDiagnosis=DifferentialDiagnosisSession(*args),
        Education=EducationSession(resources.knowledge, resources.config, brain, mouth, questions, budget))
    writer = SubmissionWriter(client, resources.knowledge, resources.config, executor, nova_session, new_request_id)
    return Consultation(client, ear, brain, mouth, writer, nova_session, budget, questions, interactions,
        resources.knowledge, resources.config, tools, sessions)



def consult(client, resources: PreparedResources):
    consultation = assemble_consultation(client, resources)
    state = consultation.nova_session.initialize_case(client)
    try:
        result = consultation.run(state).model_dump(mode='json')
        outcome = result['session']
        if outcome['termination'] != 'submitted':
            raise RuntimeError(f"Consultation {outcome['termination']}: {outcome['reason']}")
        return result
    finally:
        consultation.release()
