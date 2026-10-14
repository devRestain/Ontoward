from dataclasses import dataclass
from typing import Literal


SessionName = Literal["Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education"]
SESSION_ORDER: tuple[SessionName, ...] = ("Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education")


@dataclass(frozen=True)
class Limits:
    session_actions: tuple[int, ...] = (1, 20, 10, 14, 5)
    turns: int = 50
    finalization_seconds: int = 120
    model_calls: int = 200
    input_tokens: int = 500000
    output_tokens: int = 100000
    doctor_tokens: int = 1024
    gateway_tokens: int = 2048
    doctor_generations: int = 3
    response_format_retries: int = 1
    submission_repairs: int = 1
    clarifications: int = 2
    focused_ros: int = 6
    hpi_priority: int = 10000
    open_inquiry_priority: int = 1000000
    ros_priority: int = 900000
    clarification_priority: int = 2000000
    differential_rank_weight: int = 10
    content_codepoints: int = 30
    diagnosis_bytes: int = 500
    record_bytes: int = 100000
    request_timeout: int = 240
    retry_delays: tuple[int, ...] = (2, 5)
    graph_base_steps: int = 150
    graph_steps_per_turn: int = 24
    model: str = "openai/gpt-6-luna"
    doctor_reasoning: str = "low"
    gateway_reasoning: str = "medium"


LIMITS = Limits()
TRANSIENT_ERRORS = frozenset({"API_UNAVAILABLE", "INVALID_API_RESPONSE", "RESPONSE_TOO_LARGE",
                              "PROVIDER_UNAVAILABLE", "REQUEST_PENDING"})
