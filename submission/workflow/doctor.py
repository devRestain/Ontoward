import json
import unicodedata

from nova_sdk import NovaError

from .rules.action import ActionResponse, REFUSAL_ERRORS, RESPONSE_FORMAT_ERRORS, content_error, failure_outcome
from .rules.limits import LIMITS
from .education import message_bytes, messages
from .state.models import ActionSpec, Question, WorkflowState
from .state.canonical import CanonicalSnapshot


class Doctor:
    def __init__(self, executor, nova_session, usage, questions, interactions, new_request_id, model, config, budget):
        self.executor = executor
        self.nova_session = nova_session
        self.usage = usage
        self.questions = questions
        self.interactions = interactions
        self.new_request_id = new_request_id
        self.model = model
        self.config = config
        self.budget = budget

    def prepare_education(self, state, client):
        progress = state.interaction.education
        if progress.rendering_attempted:
            return
        progress.rendering_attempted = True
        batches, batch = [], []
        base = {"task": "education_doctor", "fixed_diagnosis": state.case.fixed_diagnosis.model_dump(),
                "patient": CanonicalSnapshot.from_case(state.case).payload(), "turn_budget": self.budget.action_capacity(state)}
        core, remaining = [], list(progress.sentences)
        for field in ("education", "tests", "treatment", "disposition", "follow_up"):
            first = next((sentence for sentence in remaining if sentence.field == field), None)
            if first:
                core.append(first)
                remaining.remove(first)
        ordered = [*core, *sorted(remaining, key=lambda s: s.priority != "safety")]
        for sentence in ordered:
            row = {"id": sentence.id, "text": sentence.text}
            if message_bytes(messages(self.config.education_doctor_prompt, {**base, "sentences": [*batch, row]})) > LIMITS.education_request_bytes:
                if batch:
                    batches.append(batch)
                batch = []
            batch.append(row)
        if batch:
            batches.append(batch)
        rendered = {}
        for batch in batches:
            remaining = {row["id"]: row for row in batch}
            errors = {}
            for attempt in range(2):
                payload = {**base, "sentences": list(remaining.values()), "validation_errors": errors}
                request = messages(self.config.education_doctor_prompt, payload)
                if message_bytes(request) > LIMITS.education_request_bytes:
                    errors = {ident: "education_doctor_context_overflow" for ident in remaining}
                    break
                content = self.model.complete(state, client, role="education_doctor", messages=request)
                try:
                    raw = json.loads(content)
                    if not isinstance(raw, dict) or set(raw) != {"items"} or not isinstance(raw["items"], list):
                        raise ValueError("invalid render response")
                    rows = raw["items"]
                except (TypeError, ValueError):
                    rows = []
                errors = {}
                unknown = any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
                              or row["id"] not in remaining for row in rows)
                for ident in list(remaining):
                    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == ident]
                    try:
                        if unknown or len(matches) != 1 or set(matches[0]) != {"id", "utterances"}:
                            raise ValueError("missing, duplicate or unexpected render ID")
                        utterances = matches[0]["utterances"]
                        if not isinstance(utterances, list) or not utterances or any(not isinstance(text, str) for text in utterances):
                            raise ValueError("expected Korean utterance list")
                        utterances = [unicodedata.normalize("NFC", text) for text in utterances]
                        lengths = [len(text) for text in utterances]
                        if any(content_error(text) or any(c in text for c in "\r\n?？")
                               or text.startswith(("그 외에는", "그렇지 않으면", "이 경우에는"))
                               or not any("\uac00" <= c <= "\ud7a3" for c in text) for text in utterances):
                            raise ValueError(f"require standalone NFC 1-30 Korean statements; actual lengths={lengths}")
                        rendered[ident] = utterances
                        del remaining[ident]
                    except (TypeError, ValueError) as error:
                        errors[ident] = str(error)
                if not remaining or state.interaction.termination or not self.budget.model_allowance(state.session, "education_doctor"):
                    break
            progress.rendering_errors.update(errors)
            if state.interaction.termination:
                break
        order = 0
        for sentence in ordered:
            for number, text in enumerate(rendered.get(sentence.id, [])):
                self.questions.register(state, Question(item_id=f"Education:{sentence.id}:{number}",
                    field=f"P.{sentence.field}", purpose="education", text=text, order=order,
                    priority=0, plan_sentence_id=sentence.id))
                order += 1
            if sentence.id not in rendered:
                progress.rendering_errors.setdefault(sentence.id, "rendering_not_completed")

    def prepare_empathy(self, state, client, event):
        payload = {"task": "empathy", "emotion": event.emotion, "intent": event.intent,
                   "patient": CanonicalSnapshot.from_case(state.case).payload(),
                   "previous_deliveries": sum(entry.delivered and entry.question is not None
                       and entry.question.purpose == "empathy" for entry in state.interaction.history)}
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
