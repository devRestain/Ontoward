import json

from knowledge.graph import ClinicalKnowledge
from pydantic import ValidationError

from .rules.input import fixed_reply, validate_facts
from .rules.limits import LIMITS
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
        if parsed is not None:
            self._apply_facts(state, parsed, source_id)
        if interaction.termination:
            return
        if parsed is None and not incoming.get("error"):
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
            "schema": ParsedInput.model_json_schema(),
        }
        parsed = self._request_parse(state, knowledge, client, text, payload)
        if parsed is None:
            return None
        unlinked = [i for i, fact in enumerate(parsed.facts) if fact.value.kind in {"symptom", "finding"}
                    and not fact.value.concept_ids and fact.value.status in {"present", "uncertain"}]
        if not unlinked or state.interaction.termination:
            return parsed
        payload["unlinked_facts"] = [parsed.facts[i].model_dump() for i in unlinked]
        expanded = self._request_parse(state, knowledge, client, text, payload, expanded=True)
        if expanded is None:
            return parsed
        replacements = {}
        for fact in expanded.facts:
            matches = [i for i in unlinked if fact.model_dump(exclude={"value"}) == parsed.facts[i].model_dump(exclude={"value"})
                       and fact.value.model_dump(exclude={"concept_ids"}) == parsed.facts[i].value.model_dump(exclude={"concept_ids"})]
            if len(matches) != 1 or matches[0] in replacements or not fact.value.concept_ids:
                state.interaction.issues.append("invalid_gateway_expansion")
                return parsed
            replacements[matches[0]] = fact
        return ParsedInput(facts=[replacements.get(i, fact) for i, fact in enumerate(parsed.facts)])

    def _vocabulary(self, state, knowledge, text, *, expanded=False):
        pending = state.interaction.pending
        required, preferred = [], knowledge.search_concepts(text)
        if pending:
            question = pending.question
            required.extend(filter(None, (question.target_id, question.attribute_id)))
            if question.attribute_id:
                required.extend(knowledge.get_attribute_values(question.attribute_id))
            if question.target_id:
                for attribute in knowledge.get_symptom_attributes(question.target_id):
                    preferred.extend([attribute, *knowledge.get_target_values(question.target_id, attribute)])
        for _, item in state.case.entries():
            if item.value and item.status == "done":
                preferred.extend([*item.value.concept_ids, *item.value.values])
                if item.value.attribute_id:
                    preferred.append(item.value.attribute_id)
        for hypothesis in state.differential.hypotheses[:5]:
            for profile in knowledge.get_disease_patterns(hypothesis.disease_id):
                preferred.append(profile.target)
                for feature in knowledge.get_pattern_features(profile.id):
                    if feature.attribute:
                        preferred.extend([feature.attribute, *knowledge.get_target_values(profile.target, feature.attribute)])
        preferred.extend(concept["id"] for concept in knowledge.concepts())
        count_limit = LIMITS.expanded_parser_concepts if expanded else LIMITS.parser_concepts
        byte_limit = LIMITS.expanded_parser_vocabulary_bytes if expanded else LIMITS.parser_vocabulary_bytes
        required = knowledge.concepts(dict.fromkeys(required))
        vocabulary = list(required)
        size = len(json.dumps(vocabulary, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if len(vocabulary) > count_limit or size > byte_limit:
            raise ValueError("Required question vocabulary exceeds parser limits")
        seen = {concept["id"] for concept in vocabulary}
        for concept in knowledge.concepts(dict.fromkeys(preferred)):
            if concept["id"] in seen:
                continue
            extra = len(json.dumps(concept, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + bool(vocabulary)
            if len(vocabulary) >= count_limit or size + extra > byte_limit:
                continue
            vocabulary.append(concept)
            size += extra
            seen.add(concept["id"])
        return vocabulary, size

    def _request_parse(self, state, knowledge, client, text, payload, *, expanded=False):
        try:
            vocabulary, vocabulary_bytes = self._vocabulary(state, knowledge, text, expanded=expanded)
        except ValueError:
            state.interaction.issues.append("gateway_required_vocabulary_overflow")
            return None
        payload = {**payload, "vocabulary": vocabulary, "parser_pass": "expansion" if expanded else "primary"}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        messages = [{"role": "system", "content": self.config.parser_prompt},
                    {"role": "user", "content": encoded}]
        previous_calls = len(state.interaction.model_history)
        content = self.model.complete(state, client, role="gateway", messages=messages)
        if len(state.interaction.model_history) > previous_calls:
            state.interaction.model_history[-1]["parser_payload"] = {"pass": payload["parser_pass"],
                "vocabulary_count": len(vocabulary), "vocabulary_bytes": vocabulary_bytes,
                "payload_bytes": len(encoded.encode("utf-8"))}
        if content is None:
            return None
        try:
            parsed = self._validate_facts(json.loads(content), state, knowledge, text)
            allowed = {concept["id"] for concept in vocabulary}
            if parsed and any(not set([*fact.value.concept_ids, *fact.value.values,
                    *([fact.value.attribute_id] if fact.value.attribute_id else [])]) <= allowed for fact in parsed.facts):
                raise ValueError("Gateway used an identifier outside its supplied vocabulary")
            return parsed
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
