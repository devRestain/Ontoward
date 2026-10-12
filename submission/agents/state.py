from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Phase = Literal[
    "hpi", "open_inquiry", "retrieval", "context", "investigation",
    "synthesis", "education", "soap",
]
Update = dict[str, object]


class InquirySlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    observation_id: str
    attribute_id: str
    status: Literal[
        "pending", "resolved", "unknown", "not_applicable", "conflicted"
    ] = "pending"


class ActionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["SAY", "EXAM"]
    purpose: Literal["hpi", "open_inquiry", "context", "investigation", "education"]
    target_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    slot_id: str | None = None
    content: str | None = None
    request_id: str | None = None


class CaseState(BaseModel):
    """Case-only state; detailed evidence and SDK payload models are deferred."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    phase: Phase = "hpi"
    session: dict[str, object] = Field(default_factory=dict)
    incoming: dict[str, object] | None = None
    observations: list[dict[str, object]] = Field(default_factory=list)
    chief_complaint_ids: list[str] = Field(default_factory=list)
    symptom_groups: list[dict[str, object]] = Field(default_factory=list)
    hpi_slots: list[InquirySlot] = Field(default_factory=list)
    hpi_initialized: bool = False
    hpi_complete: bool = False
    open_inquiry_processed: bool = False
    evidence_changed: bool = False
    candidates_initialized: bool = False
    hypotheses: list[dict[str, object]] = Field(default_factory=list)
    active_hypotheses: list[str] = Field(default_factory=list)
    reserve_hypotheses: list[str] = Field(default_factory=list)
    next_action: ActionSpec | None = None
    pending_action: ActionSpec | None = None
    action_history: list[dict[str, object]] = Field(default_factory=list)
    turns_remaining: int | None = None
    deadline: str | None = None
    budget_decision: Literal["continue", "finalize", "stop"] | None = None
    doctor_calls: int = 0
    education_status: Literal["pending", "delivered", "undelivered"] = "pending"
    soap_draft: dict[str, object] | None = None
    diagnosis: str | None = None
    submission_payload: dict[str, object] | None = None
    submission_result: dict[str, object] | None = None
    termination: Literal["submitted", "failed", "unknown", "expired", "closed"] | None = None
