from dataclasses import dataclass
from typing import Literal


SessionName = Literal["Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education"]
SESSION_ORDER: tuple[SessionName, ...] = ("Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education")
PLAN_FIELDS = ("tests", "treatment", "disposition", "follow_up", "education")
SESSION_INTERVIEW_LIMITS = {
    "Initiation": (5, 7), "ChiefComplaint": (7, 14), "ContextFactor": (7, 9),
    "DifferentialDiagnosis": (3, 10), "Education": (5, 10),
}


@dataclass(frozen=True)
class Limits:
    turns: int = 50
    finalization_seconds: int = 120
    response_seconds: int = 120
    education_turns: int = 7
    education_tokens: int = 8000
    education_doctor_tokens: int = 8000
    education_max_messages_bytes: int = 32_768
    model_calls: int = 200
    input_tokens: int = 500_000
    output_tokens: int = 100_000
    request_input_tokens: int = 100_000
    gateway_tokens: int = 8000
    gateway_recovery_tokens: int = 8000
    submission_repairs: int = 1
    clarifications: int = 2
    focused_ros: int = 6
    graph_input_items: int = 50
    hpi_priority: int = 10000
    open_inquiry_priority: int = 1000000
    clarification_priority: int = 2000000
    content_codepoints: int = 30
    diagnosis_bytes: int = 500
    record_bytes: int = 100000
    request_timeout: int = 240
    retry_delays: tuple[int, ...] = (2,)
    model: str = "openai/gpt-6-luna"
    gateway_reasoning: str = "medium"
    expanded_context_records: int = 64
    expanded_context_turns: int = 12


LIMITS = Limits()
TRANSIENT_ERRORS = frozenset({"API_UNAVAILABLE", "INVALID_API_RESPONSE", "RESPONSE_TOO_LARGE",
                              "PROVIDER_UNAVAILABLE", "REQUEST_PENDING"})
