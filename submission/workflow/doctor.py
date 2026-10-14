import json
import unicodedata

from nova_sdk import NovaError

from .rules.action import ActionResponse, REFUSAL_ERRORS, RESPONSE_FORMAT_ERRORS, content_error, failure_outcome
from .rules.limits import LIMITS
from .state.models import WorkflowState


class Doctor:
    def __init__(self, config, model, executor, nova_session, budget, usage, questions, interactions, new_request_id):
        self.config = config
        self.model = model
        self.executor = executor
        self.nova_session = nova_session
        self.budget = budget
        self.usage = usage
        self.questions = questions
        self.interactions = interactions
        self.new_request_id = new_request_id

    def frame_action(self, state: WorkflowState, client) -> None:
        action = state.interaction.selected
        if action is None or action.ready or state.interaction.termination:
            return
        if action.question.kind == "EXAM" or action.question.kind not in state.session.allowed_actions:
            return
        if not self.budget.can_frame(state, action):
            action.content = action.question.text
            action.render_source = "prepared"
            return
        payload = {"question": action.question.model_dump(), "dialogue": state.interaction.dialogue(),
                   "validation_feedback": action.feedback}
        content = self.model.complete(state, client, role="doctor", reserve_reply=action.question.parsing_required,
                           messages=[{"role": "system", "content": self.config.doctor_prompt},
                                     {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        action.render_attempts += 1
        action.render_source = "doctor"
        action.content = content if content is not None else ""

    def validate_action(self, state: WorkflowState) -> None:
        action = state.interaction.selected
        if action is None or state.interaction.termination:
            return
        action.content = unicodedata.normalize("NFC", action.content)
        error = content_error(action.content)
        allowed = action.question.kind in state.session.allowed_actions
        if error and allowed and action.question.kind == "SAY":
            action.feedback = {"error": error, "codepoints": len(action.content)}
            if self.budget.can_frame(state, action):
                return
            action.content = unicodedata.normalize("NFC", action.question.text)
            action.render_source = "prepared"
            error = content_error(action.content)
        if error or not allowed:
            self.questions.reject_action(state, action, error or "not_allowed")
            return
        action.feedback = None
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
                    {"content": action.content, "request_id": action.request_id}, entry.attempts)
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
