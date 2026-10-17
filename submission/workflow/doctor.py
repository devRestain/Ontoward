import unicodedata

from nova_sdk import NovaError

from .rules.action import ActionResponse, REFUSAL_ERRORS, RESPONSE_FORMAT_ERRORS, content_error, failure_outcome
from .state.models import WorkflowState


class Doctor:
    def __init__(self, executor, nova_session, usage, questions, interactions, budget):
        self.executor = executor
        self.nova_session = nova_session
        self.usage = usage
        self.questions = questions
        self.interactions = interactions
        self.budget = budget

    def validate_action(self, state: WorkflowState) -> None:
        action = state.interaction.selected
        if action is None or state.interaction.termination:
            return
        action.content = unicodedata.normalize("NFC", action.question.text)
        error = content_error(action.content)
        allowed = action.question.kind in state.session.allowed_actions
        if error or not allowed:
            self.questions.reject_action(state, action, error or "not_allowed")
            return
        action.ready = True

    def execute_action(self, state: WorkflowState, client) -> None:
        action = state.interaction.selected
        if action is None or not action.ready or state.interaction.termination:
            return
        if self.budget.seconds_left(state.session) <= 0:
            state.stop("expired", "session_expired")
            return
        if not self.budget.can_start_action(state, purpose=action.question.purpose):
            if not self.budget.collection_available(state.session):
                state.session.finalizing = True
                self.interactions.clear_selected(state)
            else:
                self.questions.discard_unasked(state, {action.question.item_id})
            return
        self.interactions.begin_action(state)
        previous_turns = state.session.turns_remaining
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
            self.usage.record_actions(state, previous_turns, response.turns_remaining, purpose=action.question.purpose)
            self.interactions.record_delivery(state, action, entry, response, raw)
        except NovaError as error:
            entry.response = {"error": error.code}
            if error.code == "REQUEST_BUDGET_EXHAUSTED" and not entry.attempts:
                self.interactions.consume_input(state)
                state.session.finalizing = True
            elif error.code in RESPONSE_FORMAT_ERRORS:
                self.interactions.receive_input(state, entry.response)
            elif error.code in REFUSAL_ERRORS:
                try:
                    self.nova_session.refresh_snapshot(state, client)
                    self.usage.record_actions(state, previous_turns, state.session.turns_remaining, purpose=action.question.purpose)
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
        except (ValueError, TypeError):
            state.stop("unknown", "invalid_action_response")
