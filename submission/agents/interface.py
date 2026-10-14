import json
import unicodedata
from uuid import uuid4

from nova_sdk import NovaError
from pydantic import BaseModel, ConfigDict, Field

from .model import GATEWAY_TOKENS, complete
from .session import SessionController, sdk_failure
from .state import ClinicalValue, InteractionEntry, WorkflowState
from .transport import request_with_recovery


class ActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    turn: int = Field(ge=0, le=50)
    turns_remaining: int = Field(ge=0, le=50)
    content: str | None = None
    result: str | None = None


class InterfaceAgent:
    def __init__(self, config):
        self.config = config

    @staticmethod
    def can_frame(state, action):
        reserve = int(action.question.parsing_required)
        return (action.render_attempts < 3 and state.session.calls_left() > reserve
                and state.session.output_token_limit - state.session.output_tokens > (GATEWAY_TOKENS if reserve else 0))

    def render(self, state: WorkflowState, client) -> None:
        action = state.interaction.selected
        if action is None or action.ready or state.interaction.termination:
            return
        if action.question.kind == "EXAM" or action.question.kind not in state.session.allowed_actions:
            return
        if not self.can_frame(state, action):
            action.content = action.question.text
            action.render_source = "prepared"
            return
        payload = {"question": action.question.model_dump(), "dialogue": state.interaction.dialogue(),
                   "validation_feedback": action.feedback}
        content = complete(state, client, role="doctor", reserve_reply=action.question.parsing_required,
                           messages=[{"role": "system", "content": self.config.doctor_prompt},
                                     {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        action.render_attempts += 1
        action.render_source = "doctor"
        action.content = content if content is not None else ""

    @staticmethod
    def content_error(text):
        if not text.strip():
            return "empty_content"
        return "content_too_long" if len(text) > 30 else None

    def validate(self, state: WorkflowState) -> None:
        action = state.interaction.selected
        if action is None or state.interaction.termination:
            return
        action.content = unicodedata.normalize("NFC", action.content)
        error = self.content_error(action.content)
        allowed = action.question.kind in state.session.allowed_actions
        if error and allowed and action.question.kind == "SAY":
            action.feedback = {"error": error, "codepoints": len(action.content)}
            if self.can_frame(state, action):
                return
            action.content = unicodedata.normalize("NFC", action.question.text)
            action.render_source = "prepared"
            error = self.content_error(action.content)
        if error or not allowed:
            item = state.case.get(action.question.item_id)
            if item:
                item.status = "done"
                item.value = ClinicalValue(kind="text", text=self.config.texts.invalid_action_text, status="unknown")
            state.interaction.issues.append(f"invalid_action:{action.question.item_id}:{error or 'not_allowed'}")
            state.interaction.selected = None
            return
        action.feedback = None
        action.ready = True

    def execute(self, state: WorkflowState, client) -> None:
        action = state.interaction.selected
        if action is None or not action.ready or state.interaction.termination:
            return
        state.interaction.selected = None
        state.interaction.pending = action
        previous_turns = state.session.turns_remaining
        for format_attempt in range(2):
            entry = InteractionEntry(id=action.request_id, kind=action.question.kind,
                question=action.question.model_copy(deep=True),
                request={"request_id": action.request_id, "action": action.question.kind, "content": action.content})
            state.interaction.history.append(entry)
            try:
                call = client.say if action.question.kind == "SAY" else client.exam
                raw = request_with_recovery(state, client, call,
                    {"content": action.content, "request_id": action.request_id}, entry.attempts)
                entry.response = raw
                response = ActionResponse.model_validate(raw)
                text = response.content if action.question.kind == "SAY" else response.result
                if response.status != "OK" or text is None or response.turns_remaining != previous_turns - 1:
                    raise ValueError("Invalid action result or turn metadata")
                state.session.turns_remaining = response.turns_remaining
                state.session.usage[state.session.current].actions += previous_turns - response.turns_remaining
                entry.turn = response.turn
                entry.delivered = True
                state.interaction.incoming = raw
                if action.question.purpose == "education":
                    item = state.case.get(action.question.item_id)
                    if item:
                        item.status = "done"
                        item.value = ClinicalValue(kind="education", text=action.content, status="present")
                        item.source_refs = [entry.id]
                return
            except NovaError as error:
                entry.response = {"error": error.code}
                if error.code in {"PATIENT_RESPONSE_INVALID", "EXAMINER_RESPONSE_INVALID"}:
                    if format_attempt == 0:
                        action.request_id = str(uuid4())
                        continue
                    state.interaction.incoming = entry.response
                elif error.code in {"EXAM_NOT_SPECIFIC", "EXAM_NOT_RECOGNIZED", "EMPTY_CONTENT", "CONTENT_TOO_LONG", "ACTION_NOT_AVAILABLE"}:
                    try:
                        SessionController().refresh(state, client)
                        state.session.usage[state.session.current].actions += max(0, previous_turns - state.session.turns_remaining)
                        state.interaction.incoming = entry.response
                    except NovaError as refresh_error:
                        sdk_failure(state, refresh_error)
                    except (ValueError, TypeError):
                        state.stop("unknown", "invalid_session_after_refusal")
                elif error.code == "TURN_LIMIT_REACHED":
                    state.session.turns_remaining = 0
                    state.interaction.incoming = entry.response
                else:
                    sdk_failure(state, error)
                return
            except (ValueError, TypeError):
                state.stop("unknown", "invalid_action_response")
                return
