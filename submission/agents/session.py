from datetime import datetime

from nova_sdk import NovaError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .state import SCOPES, SessionContext, WorkflowState
from .transport import TRANSIENT_ERRORS, request_with_recovery


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    initial: dict[str, object]
    deadline: datetime
    turns_remaining: int = Field(ge=0, le=50)
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


def sdk_failure(state: WorkflowState, error: NovaError) -> None:
    if error.code == "SESSION_EXPIRED":
        state.stop("expired", error.code)
    elif error.code in {"SESSION_CLOSED", "RUN_NOT_ACTIVE"}:
        state.stop("closed", error.code)
    elif error.code in {*TRANSIENT_ERRORS, "REQUEST_BUDGET_EXHAUSTED"}:
        state.stop("unknown", error.code)
    else:
        state.stop("failed", error.code)


class SessionController:
    def initialize_case(self, client) -> WorkflowState:
        raw = client.session()
        incoming = SessionInput.model_validate(raw)
        state = WorkflowState(session=SessionContext(
            session_id=str(raw.get("session_id") or client.session_id),
            deadline=incoming.deadline, turns_remaining=incoming.turns_remaining,
        ))
        self.apply_session(state, incoming)
        state.interaction.incoming = {"initial": incoming.initial}
        return state

    @staticmethod
    def apply_session(state: WorkflowState, value: SessionInput) -> None:
        session = state.session
        session.turns_remaining = value.turns_remaining
        session.deadline = value.deadline
        session.allowed_actions = value.allowed_actions
        for remaining, used, limit in (
            (value.doctor_calls_remaining, session.doctor_calls, "call_limit"),
            (value.input_tokens_remaining, session.input_tokens, "input_token_limit"),
            (value.output_tokens_remaining, session.output_tokens, "output_token_limit"),
        ):
            if remaining is not None:
                setattr(session, limit, min(getattr(session, limit), used + remaining))
        if value.status in {"closed", "completed"}:
            state.stop("closed", "session_closed")
        elif value.status == "expired" or session.seconds_left() <= 0:
            state.stop("expired", "session_expired")
        elif value.status not in {"active", "ready", "in_progress"}:
            state.stop("failed", "invalid_session_status")

    def refresh(self, state: WorkflowState, client, *, final=False) -> None:
        raw = request_with_recovery(state, client, client.session, {}, [], final=final)
        self.apply_session(state, SessionInput.model_validate(raw))

    def budget_guard(self, state: WorkflowState) -> None:
        if state.interaction.termination or state.interaction.pending:
            return
        session = state.session
        if session.seconds_left() <= 0:
            state.stop("expired", "session_expired")
            return
        if session.finalizing or session.seconds_left() <= session.reserve_seconds or session.turns_remaining == 0 or session.calls_left() == 0:
            session.finalizing = True
            state.interaction.selected = None
            removed = {item.id for item in state.case.unasked(session.current)}
            state.case.remove(removed)
            state.questions.questions = [q for q in state.questions.questions if q.item_id not in removed]
            return
        if not session.initialized:
            return
        limit, usage = session.limits[session.current], session.usage[session.current]
        actions_left = min(limit.actions - usage.actions, session.turns_remaining)
        calls_left = session.calls_left()
        questions = [q for q in state.questions.questions
                     if (item := state.case.get(q.item_id)) and item.scope == session.current and item.status == "unasked"]
        keep = set()
        for question in sorted(questions, key=lambda q: (-q.priority, q.order, q.item_id)):
            selected = state.interaction.selected
            already_framed = selected and selected.question.item_id == question.item_id and selected.ready
            cost = int(question.parsing_required) + int(question.kind == "SAY" and not already_framed)
            if actions_left <= 0 or calls_left < cost:
                continue
            keep.add(question.item_id)
            actions_left -= 1
            calls_left -= cost
        removed = {q.item_id for q in questions} - keep
        state.case.remove(removed)
        state.questions.questions = [q for q in state.questions.questions if q.item_id not in removed]
        selected = state.interaction.selected
        if selected and selected.question.item_id in removed:
            state.interaction.selected = None

    def graph_step_limit(self, state: WorkflowState) -> int:
        return 150 + 24 * min(50, state.session.turns_remaining)

    def advance_scope(self, state: WorkflowState) -> None:
        if not state.session.initialized or state.interaction.pending or state.case.unasked(state.session.current):
            raise ValueError("Cannot advance an unfinished scope")
        if state.session.current == "Education":
            state.session.finalizing = True
        else:
            state.session.current = SCOPES[SCOPES.index(state.session.current) + 1]
            state.session.initialized = False
            state.session.questions_prepared = False
            state.questions.questions = []
