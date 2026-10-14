from pydantic import BaseModel, ConfigDict, Field

from .limits import LIMITS, TRANSIENT_ERRORS

RESPONSE_FORMAT_ERRORS = frozenset({"PATIENT_RESPONSE_INVALID", "EXAMINER_RESPONSE_INVALID"})
REFUSAL_ERRORS = frozenset({"EXAM_NOT_SPECIFIC", "EXAM_NOT_RECOGNIZED", "EMPTY_CONTENT",
                            "CONTENT_TOO_LONG", "ACTION_NOT_AVAILABLE"})


class ActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    turn: int = Field(ge=0, le=LIMITS.turns)
    turns_remaining: int = Field(ge=0, le=LIMITS.turns)
    content: str | None = None
    result: str | None = None


def content_error(text):
    if not text.strip():
        return "empty_content"
    return "content_too_long" if len(text) > LIMITS.content_codepoints else None


def failure_outcome(error):
    if error.code == "SESSION_EXPIRED":
        return "expired"
    if error.code in {"SESSION_CLOSED", "RUN_NOT_ACTIVE"}:
        return "closed"
    if error.code in {*TRANSIENT_ERRORS, "REQUEST_BUDGET_EXHAUSTED"}:
        return "unknown"
    return "failed"
