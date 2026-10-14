import json

from knowledge.graph import ClinicalKnowledge
from pydantic import ValidationError

from .rules.input import fixed_reply, validate_facts
from .state.models import ClinicalValue, ParsedInput, RecordItem, WorkflowState


class InputInterpreter:
    def __init__(self, config, model, questions, interactions):
        self.config = config
        self.model = model
        self.questions = questions
        self.interactions = interactions

    def process_input(self, state: WorkflowState, knowledge: ClinicalKnowledge, client) -> None:
        interaction = state.interaction
        if interaction.termination:
            return
        if interaction.incoming is None:
            if interaction.pending:
                state.stop("unknown", "missing_action_response")
            return
        incoming, action = interaction.incoming, interaction.pending
        initial = "initial" in incoming
        if not initial and action is None:
            state.stop("failed", "unexpected_action_response")
            return
        source_id = "initial" if initial else action.request_id
        if initial:
            raw = incoming["initial"]
            text = str(raw.get("opening", ""))
            self.interactions.record_initial(state, raw)
            vitals = raw.get("vital_signs")
            if vitals:
                state.case.put("O.exam", RecordItem(id="initial:vitals", scope="Initiation", status="done",
                    value=ClinicalValue(kind="finding", text=json.dumps(vitals, ensure_ascii=False) if not isinstance(vitals, str) else vitals,
                                        status="present"), source_refs=[source_id]))
        else:
            text = incoming.get("content" if action.question.kind == "SAY" else "result", "")
            text = text if isinstance(text, str) else ""
        if incoming.get("error"):
            parsed = ParsedInput()
        elif "facts" in (incoming["initial"] if initial else incoming):
            parsed = self._validate_facts({"facts": (incoming["initial"] if initial else incoming)["facts"]}, state, knowledge, text)
        else:
            parsed = ParsedInput() if initial and not text.strip() else (None if initial else fixed_reply(self.config, state, text))
            if parsed is None:
                parsed = self._parse_text(state, knowledge, client, text)
        if interaction.termination:
            return
        if parsed is not None:
            self._apply_facts(state, parsed, source_id)
        elif not incoming.get("error"):
            self.interactions.request_clarification(state, action.question if action else None)
        if action:
            self.questions.complete_unresolved(state, action, text, source_id)
        self.interactions.consume_input(state)

    def _parse_text(self, state: WorkflowState, knowledge: ClinicalKnowledge, client, text: str) -> ParsedInput | None:
        pending = state.interaction.pending
        payload = {
            "input": text, "question": pending.question.model_dump() if pending else None,
            "spoken_question": pending.content if pending else None,
            "records": [{"field": field, **item.model_dump()} for field, item in state.case.entries()],
            "dialogue": state.interaction.dialogue(),
            "vocabulary": knowledge.concepts(), "schema": ParsedInput.model_json_schema(),
        }
        messages = [{"role": "system", "content": self.config.parser_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        content = self.model.complete(state, client, role="gateway", messages=messages)
        if content is None:
            return None
        try:
            return self._validate_facts(json.loads(content), state, knowledge, text)
        except (TypeError, ValueError):
            state.interaction.issues.append("invalid_gateway_output")
        return None

    def _validate_facts(self, raw, state: WorkflowState, knowledge: ClinicalKnowledge, text: str) -> ParsedInput | None:
        try:
            return validate_facts(raw, state, knowledge, text)
        except (ValidationError, ValueError, TypeError):
            state.interaction.issues.append("invalid_input_facts")
            return None

    def _apply_facts(self, state: WorkflowState, parsed: ParsedInput, source_id: str) -> None:
        pending = state.interaction.pending
        for index, fact in enumerate(parsed.facts):
            value = fact.value.model_copy(deep=True)
            item_id = fact.record_id
            if item_id is None:
                matches = [q for q in state.questions.questions if q.target_id in value.concept_ids
                           and q.attribute_id == value.attribute_id and q.subject == value.subject
                           and (not q.observation_id or q.observation_id == value.observation_id)
                           and (not q.episode_id or q.episode_id == value.episode_id)]
                if len(matches) == 1:
                    item_id = matches[0].item_id
            item_id = item_id or f"{source_id}:fact:{index}"
            existing = state.case.get(item_id)
            if value.kind in {"symptom", "finding", "attribute"}:
                question = next((q for q in state.questions.questions if q.item_id == item_id), None)
                value.observation_id = value.observation_id or (question.observation_id if question else None) or item_id
                value.episode_id = value.episode_id or (question.episode_id if question else None) or value.observation_id
            field = fact.field
            if existing:
                field = next(field for field, item in state.case.entries() if item.id == existing.id)
            elif value.kind == "symptom" and value.subject == "patient" and value.time_context != "past" and pending and pending.question.purpose == "chief":
                field = "S.cc"
            elif value.kind == "symptom" and pending and pending.question.purpose in {"ros", "open_inquiry"} and not existing:
                field = "S.ros"
            elif value.kind == "symptom" and pending and pending.question.purpose == "clarification" and not existing:
                field = pending.question.field
            refs = list(dict.fromkeys([*(existing.source_refs if existing else []), source_id]))
            scope = existing.scope if existing else state.session.current
            context_refs = list(dict.fromkeys([*(existing.context_refs if existing else []), *fact.context_refs]))
            state.case.put(field, RecordItem(id=item_id, scope=scope, status="done", value=value,
                                            source_refs=refs, context_refs=context_refs))
