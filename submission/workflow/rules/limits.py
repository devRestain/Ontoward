from dataclasses import dataclass
from typing import Literal


SessionName = Literal["Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education"]
SESSION_ORDER: tuple[SessionName, ...] = ("Initiation", "ChiefComplaint", "ContextFactor", "DifferentialDiagnosis", "Education")


@dataclass(frozen=True)
class Limits:
    turns: int = 50
    finalization_seconds: int = 120
    response_seconds: int = 120
    education_turns: int = 3
    model_calls: int = 200
    input_tokens: int = 500000
    output_tokens: int = 100000
    gateway_tokens: int = 2048
    response_format_retries: int = 1
    submission_repairs: int = 1
    clarifications: int = 2
    focused_ros: int = 6
    hpi_priority: int = 10000
    open_inquiry_priority: int = 1000000
    clarification_priority: int = 2000000
    differential_display: int = 5
    parser_concepts: int = 256
    parser_vocabulary_bytes: int = 32768
    expanded_parser_concepts: int = 1024
    expanded_parser_vocabulary_bytes: int = 131072
    content_codepoints: int = 30
    diagnosis_bytes: int = 500
    record_bytes: int = 100000
    request_timeout: int = 240
    retry_delays: tuple[int, ...] = (2, 5)
    graph_base_steps: int = 150
    graph_steps_per_turn: int = 24
    model: str = "openai/gpt-6-luna"
    gateway_reasoning: str = "medium"
    context_records: int = 24
    context_turns: int = 6
    context_bytes: int = 16384
    expanded_context_records: int = 64
    expanded_context_turns: int = 12
    expanded_context_bytes: int = 65536


LIMITS = Limits()
TRANSIENT_ERRORS = frozenset({"API_UNAVAILABLE", "INVALID_API_RESPONSE", "RESPONSE_TOO_LARGE",
                              "PROVIDER_UNAVAILABLE", "REQUEST_PENDING"})
