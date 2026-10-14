import json

from knowledge.graph import ClinicalKnowledge
from pydantic import ValidationError

from .model import complete
from .state import ClinicalValue, Fact, InteractionEntry, ParsedInput, RecordItem, WorkflowState


class InputGateway:
    def __init__(self, config):
        self.config = config

    def ingest(self, state: WorkflowState, knowledge: ClinicalKnowledge, client) -> None:
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
            interaction.history.append(InteractionEntry(id=source_id, kind="initial", response=raw))
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
            parsed = self._validated({"facts": (incoming["initial"] if initial else incoming)["facts"]}, state, knowledge, text)
        else:
            parsed = ParsedInput() if initial and not text.strip() else (None if initial else self._fixed_reply(state, text))
            if parsed is None:
                parsed = self._parse(state, knowledge, client, text)
        if interaction.termination:
            return
        if parsed is not None:
            self._apply(state, parsed, source_id)
        elif not incoming.get("error"):
            interaction.needs_clarification = True
            interaction.clarification_target = action.question.model_copy(deep=True) if action else None
        if action:
            item = state.case.get(action.question.item_id)
            if item and item.status == "unasked":
                item.status = "done"
                delivered = action.question.purpose == "education" and not incoming.get("error")
                item.value = ClinicalValue(
                    kind="education" if delivered else "text",
                    text=action.content if delivered else (text or self.config.texts.unknown_text),
                    status="present" if delivered else "unknown",
                    concept_ids=[action.question.target_id] if action.question.target_id and not delivered else [],
                    attribute_id=action.question.attribute_id if not delivered else None,
                    observation_id=action.question.observation_id,
                    episode_id=action.question.episode_id,
                    subject=action.question.subject,
                    time_context=action.question.time_context,
                )
                item.source_refs = [source_id]
        interaction.pending = None
        interaction.incoming = None

    def _fixed_reply(self, state: WorkflowState, text: str) -> ParsedInput | None:
        question = state.interaction.pending.question
        texts = self.config.texts
        reply = text.strip().rstrip(texts.reply_trailing_punctuation)
        if reply in texts.unknown_replies:
            return ParsedInput()
        if question.purpose == "education" and reply in texts.education_acknowledgements:
            return ParsedInput()
        if state.interaction.pending.render_source == "doctor":
            return None
        statuses = {**dict.fromkeys(texts.present_replies, "present"), **dict.fromkeys(texts.absent_replies, "absent")}
        if (not question.affirmative_presence or question.purpose not in {"context", "feature", "ros"}
                or question.attribute_id or question.kind != "SAY" or reply not in statuses):
            return None
        kind = "context" if question.purpose == "context" else "symptom"
        return ParsedInput(facts=[Fact(field=question.field, record_id=question.item_id, quote=text,
            value=ClinicalValue(kind=kind, text=text, status=statuses[reply], concept_ids=[question.target_id],
                observation_id=question.observation_id or question.item_id,
                episode_id=question.episode_id or question.item_id, subject=question.subject,
                time_context=question.time_context))])

    def _parse(self, state: WorkflowState, knowledge: ClinicalKnowledge, client, text: str) -> ParsedInput | None:
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
        content = complete(state, client, role="gateway", messages=messages)
        if content is None:
            return None
        try:
            return self._validated(json.loads(content), state, knowledge, text)
        except (TypeError, ValueError):
            state.interaction.issues.append("invalid_gateway_output")
        return None

    def _validated(self, raw, state: WorkflowState, knowledge: ClinicalKnowledge, text: str) -> ParsedInput | None:
        try:
            parsed = ParsedInput.model_validate(raw)
            pending = state.interaction.pending
            dialogue_ids = {entry["id"] for entry in state.interaction.dialogue()}
            for fact in parsed.facts:
                value = fact.value
                if not set(fact.context_refs) <= dialogue_ids:
                    raise ValueError("Unknown dialogue context reference")
                if fact.quote not in text or value.text != fact.quote or fact.field.startswith(("A.", "P.")) or fact.field == "O.tests":
                    raise ValueError("Fact is not grounded in an allowed current input")
                if fact.field == "O.exam" and (pending is None or pending.question.kind != "EXAM"):
                    raise ValueError("Patient speech cannot create examination findings")
                if value.kind == "finding" and fact.field != "O.exam":
                    raise ValueError("Examination findings require an actual examination")
                if value.kind == "attribute" and not value.attribute_id:
                    raise ValueError("Attribute fact requires an attribute")
                if value.kind in {"plan", "education"}:
                    raise ValueError("Input cannot create plans or delivered education")
                if fact.record_id:
                    existing = state.case.get(fact.record_id)
                    question = next((q for q in state.questions.questions if q.item_id == fact.record_id), None)
                    if existing is None or (existing.value and existing.value.kind in {"plan", "education"}) or (
                        question and question.purpose == "education"
                    ):
                        raise ValueError("Invalid observation record reference")
                    previous = existing.value
                    if question and question.purpose in {"hpi", "context", "feature", "ros", "clarification"} and (
                        value.subject != question.subject or value.attribute_id != question.attribute_id
                        or (question.target_id and question.target_id not in value.concept_ids)
                        or (question.observation_id and value.observation_id not in {None, question.observation_id})
                        or (question.episode_id and value.episode_id not in {None, question.episode_id})
                    ):
                        raise ValueError("Answer does not match its question target and episode")
                    if previous and previous.kind in {"symptom", "finding", "attribute"} and (
                        value.subject != previous.subject or value.observation_id != previous.observation_id
                        or value.episode_id != previous.episode_id
                    ):
                        raise ValueError("Correction must preserve its observation and episode")
                expected_type = {"symptom": "Symptom", "finding": "ExamFinding", "context": "ContextFactor"}
                for concept in value.concept_ids:
                    if value.kind in expected_type and not knowledge.has_type(concept, expected_type[value.kind]):
                        raise ValueError("Unknown or mistyped clinical concept")
                    if value.kind == "attribute" and not any(knowledge.has_type(concept, kind) for kind in ("Symptom", "ExamFinding")):
                        raise ValueError("Attribute requires a finding target")
                if len(value.concept_ids) > 1 and value.status == "present":
                    raise ValueError("Multiple interpretations must remain uncertain")
                if value.attribute_id:
                    if not value.concept_ids or not all(value.attribute_id in knowledge.get_symptom_attributes(c) for c in value.concept_ids):
                        raise ValueError("Attribute is not applicable")
                    if not set(value.values) <= set(knowledge.get_attribute_values(value.attribute_id)):
                        raise ValueError("Categorical values are not admitted")
                elif value.values:
                    raise ValueError("Categorical values require an attribute")
                if value.kind == "context" and value.concept_ids:
                    context = value.concept_ids[0]
                    context_type = knowledge.get_context_type(context)
                    fact.field = "S.fh" if context_type == "family_history" else (
                        "S.sh" if context_type in {"social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh")
                    if (context_type == "family_history") != (value.subject == "family"):
                        raise ValueError("Context subject does not match its clinical meaning")
            return parsed
        except (ValidationError, ValueError, TypeError):
            state.interaction.issues.append("invalid_input_facts")
            return None

    def _apply(self, state: WorkflowState, parsed: ParsedInput, source_id: str) -> None:
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
