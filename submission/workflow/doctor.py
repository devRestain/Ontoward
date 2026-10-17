import json
import unicodedata

from nova_sdk import NovaError

from .rules.action import ActionResponse, REFUSAL_ERRORS, RESPONSE_FORMAT_ERRORS, content_error, failure_outcome
from .rules.limits import LIMITS
from .state.models import ActionSpec, Question, WorkflowState


class Doctor:
    def __init__(self, executor, nova_session, usage, questions, interactions, new_request_id, model, config):
        self.executor = executor
        self.nova_session = nova_session
        self.usage = usage
        self.questions = questions
        self.interactions = interactions
        self.new_request_id = new_request_id
        self.model = model
        self.config = config

    def prepare_empathy(self, state, client, event):
        payload = {"task": "empathy", "input": event.quote,
                   "last_empathy": [entry.request["content"] for entry in state.interaction.history
                       if entry.delivered and entry.question and entry.question.purpose == "empathy"][-2:]}
        messages = [{"role": "system", "content": self.config.empathy_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]
        if len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode()) > LIMITS.gateway_request_bytes:
            self.interactions.skip_empathy(state, "empathy_request_overflow", event.source_id)
            return
        content = self.model.complete(state, client, role="empathy", messages=messages)
        if state.interaction.termination:
            self.interactions.skip_empathy(state, "model_termination", event.source_id)
            return
        text = self.config.texts.empathy_fallback
        try:
            raw = json.loads(content)
            if not isinstance(raw, dict) or set(raw) != {"text"} or not isinstance(raw["text"], str):
                raise ValueError("Invalid empathy response")
            generated = unicodedata.normalize("NFC", raw["text"])
            if (content_error(generated) or any(character in generated for character in "?？\r\n")
                    or not any("\uac00" <= character <= "\ud7a3" for character in generated)):
                raise ValueError("Invalid empathy statement")
            text = generated
        except (TypeError, ValueError):
            state.interaction.issues.append("empathy_prepared_fallback")
        question = Question(item_id=f"empathy:{event.source_id}", field="S.ros", purpose="empathy",
                            text=text, order=0, priority=0)
        state.interaction.selected = ActionSpec(question=question, content=text, request_id=self.new_request_id(),
                                               render_source="empathy", empathy_source_id=event.source_id)

    def validate_action(self, state: WorkflowState) -> None:
        action = state.interaction.selected
        if action is None or state.interaction.termination:
            return
        action.content = unicodedata.normalize("NFC", action.question.text)
        error = content_error(action.content)
        allowed = action.question.kind in state.session.allowed_actions
        if error or not allowed:
            if action.empathy_source_id:
                self.interactions.skip_empathy(state, error or "not_allowed", action.empathy_source_id)
                self.interactions.clear_selected(state)
            else:
                self.questions.reject_action(state, action, error or "not_allowed")
            return
        action.ready = True

    def execute_action(self, state: WorkflowState, client) -> None:
        action = state.interaction.selected
        if action is None or not action.ready or state.interaction.termination:
            return
        self.interactions.begin_action(state)
        previous_turns = state.session.turns_remaining
        for format_attempt in range(LIMITS.response_format_retries + 1):
            entry = self.interactions.record_action_attempt(state, action)
            try:
                call = client.say if action.question.kind == "SAY" else client.exam
                raw = self.executor.execute(state, client, call,
                    {"content": action.content, "request_id": action.request_id}, entry.attempts, action=True)
                entry.response = raw
                response = ActionResponse.model_validate(raw)
                text = response.content if action.question.kind == "SAY" else response.result
                if response.status != "OK" or text is None or response.turns_remaining != previous_turns - 1:
                    raise ValueError("Invalid action result or turn metadata")
                self.usage.record_actions(state, previous_turns, response.turns_remaining)
                self.interactions.record_delivery(state, action, entry, response, raw)
                return
            except NovaError as error:
                entry.response = {"error": error.code}
                if error.code in RESPONSE_FORMAT_ERRORS:
                    if format_attempt < LIMITS.response_format_retries:
                        action.request_id = self.new_request_id()
                        continue
                    self.interactions.receive_input(state, entry.response)
                elif error.code in REFUSAL_ERRORS:
                    try:
                        self.nova_session.refresh_snapshot(state, client)
                        self.usage.record_actions(state, previous_turns, state.session.turns_remaining)
                        self.interactions.receive_input(state, entry.response)
                    except NovaError as refresh_error:
                        state.stop(failure_outcome(refresh_error), refresh_error.code)
                    except (ValueError, TypeError):
                        state.stop("unknown", "invalid_session_after_refusal")
                elif error.code == "TURN_LIMIT_REACHED":
                    self.usage.exhaust_turns(state)
                    self.interactions.receive_input(state, entry.response)
                else:
                    state.stop(failure_outcome(error), error.code)
                return
            except (ValueError, TypeError):
                state.stop("unknown", "invalid_action_response")
                return
