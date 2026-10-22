from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..state import usage
from ..rules.limits import LIMITS
from ..state.models import SessionContext, TurnContext, WorkflowState
from .sdk_boundary import sdk_call


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    initial: dict[str, object]
    deadline: datetime
    turns_remaining: int = Field(ge=0, le=LIMITS.turns)
    status: str = "active"
    allowed_actions: list[str] = Field(default_factory=lambda: ["SAY", "EXAM", "DIAGNOSE"])
    doctor_calls_remaining: int | None = Field(default=None, ge=0)
    input_tokens_remaining: int | None = Field(default=None, ge=0)
    output_tokens_remaining: int | None = Field(default=None, ge=0)

    @field_validator("initial")
    @classmethod
    def validate_initial(cls, value):
        if "opening" in value and not isinstance(value["opening"], str):
            raise ValueError("Initial opening must be text")
        if "vital_signs" in value and not isinstance(value["vital_signs"], (str, dict)):
            raise ValueError("Initial vital signs must be structured values or text")
        return value

    @field_validator("deadline")
    @classmethod
    def aware_deadline(cls, value):
        if value.tzinfo is None:
            raise ValueError("Session deadline must include a timezone")
        return value


class NovaSessionClient:
    def __init__(self, executor, budget, interactions):
        self.executor = executor
        self.budget = budget
        self.interactions = interactions

    def initialize_case(self, client) -> WorkflowState:
        raw = sdk_call(client.session)
        incoming = SessionInput.model_validate(raw)
        state = WorkflowState(session=SessionContext(
            session_id=str(raw.get("session_id") or client.session_id),
            deadline=incoming.deadline, turns_remaining=incoming.turns_remaining,
        ))
        state.case.presenting_text = incoming.initial.get('opening', '')
        state.case.initial_vital_signs = incoming.initial.get('vital_signs')
        self.apply_snapshot(state, incoming)
        if not state.session.termination:
            state.turn = TurnContext(kind='initial', response=incoming.initial)
        return state

    def apply_snapshot(self, state: WorkflowState, value: SessionInput) -> None:
        session = state.session
        usage.apply_server_budget(state, value)
        session.budget_sync_required = False
        session.deadline = value.deadline
        session.allowed_actions = value.allowed_actions
        if value.status in {"closed", "completed"}:
            state.stop("closed", "session_closed")
        elif value.status == "expired" or self.budget.seconds_left(session) <= 0:
            state.stop("expired", "session_expired")
        elif value.status not in {"active", "ready", "in_progress"}:
            state.stop("failed", "invalid_session_status")

    def refresh_snapshot(self, state: WorkflowState, client, *, final=False, account_action=False) -> None:
        previous = state.session.turns_remaining
        raw = self.executor.execute(state, client, client.session, {}, [], final=final)
        self.apply_snapshot(state, SessionInput.model_validate(raw))
        if account_action:
            usage.record_actions(state, previous, state.session.turns_remaining)
