from __future__ import annotations

from datetime import datetime
from typing import Literal

from nova_sdk import RECORD_FIELDS
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..rules.limits import LIMITS, SESSION_ORDER, SessionName
SOAPField = Literal[
    "S.cc", "S.hpi", "S.pmh", "S.fh", "S.sh", "S.ros", "O.exam", "O.tests",
    "A.evidence", "A.differential", "P.tests", "P.treatment", "P.disposition", "P.follow_up", "P.education",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ClinicalValue(Model):
    kind: Literal["symptom", "finding", "context", "attribute", "text", "plan", "education"]
    text: str
    status: Literal["present", "absent", "uncertain", "unknown"] = "unknown"
    concept_ids: list[str] = Field(default_factory=list)
    observation_id: str | None = None
    episode_id: str | None = None
    attribute_id: str | None = None
    values: list[str] = Field(default_factory=list)
    subject: Literal["patient", "family"] = "patient"
    time_context: Literal["current", "past", "unspecified"] = "unspecified"


class RecordItem(Model):
    id: str
    scope: SessionName
    status: Literal["unasked", "done"] = "unasked"
    value: ClinicalValue | None = None
    source_refs: list[str] = Field(default_factory=list)
    context_refs: list[str] = Field(default_factory=list)


class CaseState(Model):
    S: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["S"]})
    O: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["O"]})
    A: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["A"]})
    P: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["P"]})
    diagnosis: str | None = None
    diagnosis_kind: Literal["disease", "symptom"] | None = None
    diagnosis_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sections(self):
        ids = []
        for section, fields in RECORD_FIELDS.items():
            if set(getattr(self, section)) != set(fields):
                raise ValueError(f"Invalid SOAP section: {section}")
            for records in getattr(self, section).values():
                for key, item in records.items():
                    if key != item.id:
                        raise ValueError("Record key must match its ID")
                    ids.append(key)
        if len(ids) != len(set(ids)):
            raise ValueError("Record IDs must be unique")
        return self

    def entries(self):
        for section, fields in RECORD_FIELDS.items():
            for field in fields:
                for item in getattr(self, section)[field].values():
                    yield f"{section}.{field}", item

    def get(self, item_id: str) -> RecordItem | None:
        return next((item for _, item in self.entries() if item.id == item_id), None)

    def put(self, field: SOAPField, item: RecordItem) -> None:
        self.remove({item.id})
        section, name = field.split(".")
        getattr(self, section)[name][item.id] = item

    def remove(self, ids: set[str]) -> None:
        for section in RECORD_FIELDS:
            for records in getattr(self, section).values():
                for item_id in ids:
                    records.pop(item_id, None)

    def unasked(self, scope: SessionName) -> list[RecordItem]:
        return [item for _, item in self.entries() if item.scope == scope and item.status == "unasked"]

    def chief_complaints(self, *, confirmed=False) -> list[RecordItem]:
        statuses = {"present"} if confirmed else {"present", "uncertain"}
        return [item for item in self.S["cc"].values() if item.status == "done" and item.source_refs
                and item.value and item.value.kind == "symptom" and item.value.subject == "patient"
                and item.value.time_context != "past" and item.value.status in statuses]


class SessionLimit(Model):
    actions: int = Field(ge=0)


def default_limits() -> dict[SessionName, SessionLimit]:
    return {scope: SessionLimit(actions=actions) for scope, actions in zip(SESSION_ORDER, LIMITS.session_actions)}


class Usage(Model):
    actions: int = 0
    calls: int = 0


class SessionContext(Model):
    session_id: str
    deadline: datetime
    turns_remaining: int = Field(ge=0, le=LIMITS.turns)
    current: SessionName = "Initiation"
    initialized: bool = False
    questions_prepared: bool = False
    finalizing: bool = False
    reserve_seconds: int = LIMITS.finalization_seconds
    limits: dict[SessionName, SessionLimit] = Field(default_factory=default_limits)
    usage: dict[SessionName, Usage] = Field(default_factory=lambda: {scope: Usage() for scope in SESSION_ORDER})
    allowed_actions: list[str] = Field(default_factory=lambda: ["SAY", "EXAM", "DIAGNOSE"])
    doctor_calls: int = 0
    doctor_successes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    call_limit: int = LIMITS.model_calls
    input_token_limit: int = LIMITS.input_tokens
    output_token_limit: int = LIMITS.output_tokens
    models_available: bool = True
    clarifications: int = Field(default=0, ge=0, le=LIMITS.clarifications)



class Hypothesis(Model):
    disease_id: str
    pattern_ids: list[str] = Field(default_factory=list)
    feature_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    opposing_ids: list[str] = Field(default_factory=list)
    evidence_score: int = 0
    context_bonus: int | None = None

    @property
    def score(self) -> int:
        return self.evidence_score + (self.context_bonus or 0)


class DifferentialState(Model):
    initialized: bool = False
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    selected_id: str | None = None


class Question(Model):
    item_id: str
    field: SOAPField
    kind: Literal["SAY", "EXAM"] = "SAY"
    purpose: Literal["chief", "hpi", "open_inquiry", "ros", "clarification", "context", "feature", "education"]
    text: str
    order: int
    priority: int
    target_id: str | None = None
    attribute_id: str | None = None
    observation_id: str | None = None
    episode_id: str | None = None
    subject: Literal["patient", "family"] = "patient"
    time_context: Literal["current", "past", "unspecified"] = "unspecified"
    parsing_required: bool = True
    affirmative_presence: bool = False


class QuestionPlan(Model):
    questions: list[Question] = Field(default_factory=list)


class ActionSpec(Model):
    question: Question
    content: str
    request_id: str
    render_attempts: int = Field(default=0, ge=0, le=LIMITS.doctor_generations)
    render_source: Literal["prepared", "doctor"] = "prepared"
    ready: bool = False
    feedback: dict[str, object] | None = None


class InteractionEntry(Model):
    id: str
    kind: Literal["initial", "SAY", "EXAM", "DIAGNOSE"]
    request: dict[str, object] = Field(default_factory=dict)
    response: dict[str, object] = Field(default_factory=dict)
    turn: int | None = None
    delivered: bool = False
    question: Question | None = None
    attempts: list[dict[str, object]] = Field(default_factory=list)


class InteractionState(Model):
    model_history: list[dict[str, object]] = Field(default_factory=list)
    history: list[InteractionEntry] = Field(default_factory=list)
    incoming: dict[str, object] | None = None
    selected: ActionSpec | None = None
    pending: ActionSpec | None = None
    submission_payload: dict[str, object] | None = None
    submission_request_id: str | None = None
    submission_result: dict[str, object] | None = None
    termination: Literal["submitted", "failed", "unknown", "expired", "closed"] | None = None
    reason: str | None = None
    issues: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_target: Question | None = None
    submission_repairs: int = Field(default=0, ge=0, le=LIMITS.submission_repairs)
    submission_error: str | None = None

    def dialogue(self) -> list[dict[str, object]]:
        turns = []
        for entry in self.history:
            if entry.kind == "initial" and entry.response.get("opening"):
                turns.append({"id": entry.id, "kind": "initial", "patient": entry.response["opening"]})
            elif entry.kind == "SAY" and entry.delivered:
                turns.append({"id": entry.id, "kind": "SAY", "turn": entry.turn,
                              "question_id": entry.question.item_id if entry.question else None,
                              "doctor": entry.request["content"], "patient": entry.response.get("content", "")})
        return turns


class WorkflowState(Model):
    case: CaseState = Field(default_factory=CaseState)
    session: SessionContext
    differential: DifferentialState = Field(default_factory=DifferentialState)
    questions: QuestionPlan = Field(default_factory=QuestionPlan)
    interaction: InteractionState = Field(default_factory=InteractionState)

    def stop(self, outcome: Literal["failed", "unknown", "expired", "closed"], reason: str) -> None:
        self.interaction.termination = outcome
        self.interaction.reason = reason


class Fact(Model):
    field: SOAPField
    value: ClinicalValue
    quote: str = Field(min_length=1)
    record_id: str | None = None
    context_refs: list[str] = Field(default_factory=list)


class ParsedInput(Model):
    facts: list[Fact] = Field(default_factory=list)
