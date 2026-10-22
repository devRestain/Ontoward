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
from .rules.chief import force_chief
from .sessions.initiation import InitiationSession
from .sessions.chief_complaint import ChiefComplaintSession
from .sessions.context_factor import ContextFactorSession
from .sessions.differential_diagnosis import DifferentialDiagnosisSession
from .sessions.education import EducationSession
from .state.interactions import InteractionLifecycle
from .state.questions import QuestionLifecycle
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
    interactions = InteractionLifecycle(new_request_id)
    questions = QuestionLifecycle(interactions)
    executor = RequestExecutor(budget, sleep)
    nova_session = NovaSessionClient(executor, budget, interactions)
    brain = DoctorBrain(executor, budget, new_request_id)
    mouth = DoctorMouth(executor, nova_session, questions, interactions, brain, resources.config, budget)
    tools = QuestionTools(resources.knowledge, resources.config, questions, interactions, budget)
    ear = DoctorEar(resources.config, brain, questions, pending_questions=tools.pending_questions)
    tools.chief_fallback = lambda state: force_chief(state, resources.knowledge, resources.config, brain, client)
    writer = SubmissionWriter(client, resources.knowledge, resources.config, executor, nova_session, new_request_id)
    args = (resources.knowledge, resources.config, tools, brain)
    sessions = dict(Initiation=InitiationSession(*args), ChiefComplaint=ChiefComplaintSession(*args),
        ContextFactor=ContextFactorSession(resources.knowledge, resources.config, tools),
        DifferentialDiagnosis=DifferentialDiagnosisSession(*args, record_view=writer.build_record_view),
        Education=EducationSession(resources.knowledge, resources.config, brain, mouth, questions, budget))
    return Consultation(client, ear, brain, mouth, writer, nova_session, budget, questions, interactions,
        resources.knowledge, resources.config, tools, sessions)



def consult(client, resources: PreparedResources):
    consultation = assemble_consultation(client, resources)
    try:
        state = consultation.nova_session.initialize_case(client)
    except Exception as error:
        # No valid initial snapshot means there is no case/deadline to invent.
        return dict(session=dict(termination='unknown', reason=consultation.error_reason(error),
                                 final_payload=None, receipt=None))
    try:
        try:
            consultation.run(state)
        except Exception as error:
            # An operation boundary may itself fail. Use the independent clinical
            # freeze and minimal Writer once, without replaying the failed operation.
            reason = consultation.error_reason(error)
            if state.session.termination != 'submitted':
                consultation.differential.freeze_problem(state, reason)
                if state.turn and state.turn.kind != 'submission':
                    consultation.questions.pass_step(state, reason)
                if not state.turn or state.turn.kind != 'submission':
                    consultation.writer.build_minimal(state, reason)
                consultation.finish_submission(state)
        try:
            return state.model_dump(mode='json')
        except Exception:
            return dict(case=dict(diagnosis=state.case.diagnosis), session=dict(
                termination=state.session.termination, reason=state.session.reason,
                final_payload=state.session.final_payload, receipt=state.session.receipt,
                submission_request_id=state.session.submission_request_id))
    finally:
        try:
            consultation.release()
        except Exception:
            pass  # Cleanup must never replace a preserved payload or actual receipt.
