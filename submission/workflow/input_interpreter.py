import hashlib
import json
from copy import deepcopy
from functools import lru_cache

from knowledge.graph import ClinicalKnowledge
from pydantic import ValidationError

from .rules.input import fixed_reply, validate_facts
from .rules.limits import LIMITS
from .state.models import ClinicalValue, ParsedInput, ParseResult, RecordItem, WorkflowState


@lru_cache(maxsize=1)
def parser_schema():
    def compact(value):
        if isinstance(value, dict):
            return {key: compact(item) for key, item in value.items() if key not in {"title", "default"}}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value
    return compact(ParsedInput.model_json_schema())


@lru_cache(maxsize=1)
def terminology_schema():
    schema = deepcopy(parser_schema())
    value = schema["$defs"]["ClinicalValue"]
    for key in ("concept_ids", "attribute_id", "values", "measurement"):
        value["properties"].pop(key)
    value["properties"]["kind"] = {"const": "text"}
    schema["$defs"].pop("ExpectedValue", None)
    schema["$defs"]["Fact"]["properties"]["record_id"] = {"type": "null"}
    return schema


class InputInterpreter:
    def __init__(self, config, model, questions, interactions):
        self.config = config
        self.model = model
        self.questions = questions
        self.interactions = interactions

    def process_input(self, state, knowledge, client):
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
        facts = incoming["initial"] if initial else incoming
        if incoming.get("error"):
            parsed = ParseResult()
        elif text.strip() and not state.session.gateway_successes:
            parsed = self._parse_text(state, knowledge, client, text)
        elif "facts" in facts:
            parsed = self._validate_facts({key: facts[key] for key in
                ("facts", "clinical_content", "empathy") if key in facts}, state, knowledge, text)
        else:
            fixed = ParsedInput() if initial and not text.strip() else (None if initial else fixed_reply(self.config, state, text, knowledge))
            parsed = ParseResult(accepted_facts=fixed.facts, clinical_content=fixed.clinical_content) if fixed is not None else self._parse_text(state, knowledge, client, text)
        if parsed is not None:
            self._apply_facts(state, parsed, source_id)
            audited = [item for step in parsed.recovery_history for item in step["rejected_facts"]]
            interaction.parse_rejections.extend({"source_id": source_id, **item} for item in (audited or parsed.rejected_facts))
            interaction.parse_recoveries.extend({"source_id": source_id, **step} for step in parsed.recovery_history)
            if parsed.empathy:
                self.interactions.queue_empathy(state, parsed.empathy, source_id)
            if parsed.rejected_facts:
                interaction.issues.append("partial_input_facts")
        if interaction.termination:
            return
        unresolved = parsed is None or parsed.binding_unresolved or (parsed.rejected_facts or parsed.needs_context) and not any(
            action and (fact.record_id == action.question.item_id or (
                action.question.target_id in fact.value.concept_ids
                and fact.value.attribute_id == action.question.attribute_id)) for fact in parsed.accepted_facts)
        if unresolved and not incoming.get("error"):
            self.interactions.request_clarification(state, action.question if action else None)
        if action:
            self.questions.complete_unresolved(state, action, text, source_id)
            if incoming.get("error") and action.empathy_source_id:
                self.interactions.skip_empathy(state, "action_response_error", action.empathy_source_id)
        self.interactions.consume_input(state)

    @staticmethod
    def _chief_input(state):
        if any(item.value.concept_ids for item in state.case.chief_complaints()):
            return False
        pending = state.interaction.pending
        return pending is None or pending.question.purpose == "empathy" or (pending.question.purpose in {"chief", "clarification"}
                                   and pending.question.field == "S.cc")

    def _search(self, state, knowledge, text, *, kind=None):
        kind = kind or ("Symptom" if self._chief_input(state) else None)
        key = hashlib.sha256(((kind or "*") + "\0" + knowledge.normalize_alias(text)).encode()).hexdigest()
        cache = state.differential.search_cache
        if key not in cache:
            if len(cache) >= 128:
                cache.pop(next(iter(cache)))
            cache[key] = knowledge.search_concepts(text, kind=kind)
        return cache[key]

    def _parse_text(self, state, knowledge, client, text):
        parsed = self._request_parse(state, knowledge, client, text)
        if parsed is None or state.interaction.termination:
            return parsed
        history = [self._recovery_audit("primary", parsed)]
        if parsed.unresolved_links or parsed.rejected_facts or parsed.needs_context or parsed.binding_unresolved:
            expanded = self._request_parse(state, knowledge, client, text, previous=parsed, compact=parsed.context_limited)
            if expanded is not None:
                history.append(self._recovery_audit("expansion", expanded))
                parsed = self._merge_recovery(state, parsed, expanded)
                self._mark_missing_binding(parsed, state, text)
        if (not state.interaction.termination and not parsed.context_limited and parsed.clinical_content
                and self._needs_terminology(parsed, text)):
            fallback = self._request_parse(state, knowledge, client, text, previous=parsed, terminology=True)
            if fallback is not None:
                history.append(self._recovery_audit("terminology", fallback))
                for fact in fallback.accepted_facts:
                    if not any(fact.quote == old.quote and old.value.kind == "text"
                               and old.value.record_details for old in parsed.accepted_facts):
                        parsed.accepted_facts.append(fact)
                parsed.empathy = parsed.empathy or fallback.empathy
        parsed.recovery_history = history
        return parsed

    @staticmethod
    def _recovery_audit(stage, parsed):
        return {"pass": stage, "accepted_facts": len(parsed.accepted_facts),
                "rejected_facts": deepcopy(parsed.rejected_facts), "unresolved_links": list(parsed.unresolved_links),
                "binding_unresolved": parsed.binding_unresolved}

    @staticmethod
    def _needs_terminology(parsed, text):
        reports = [fact.quote for fact in parsed.accepted_facts if fact.value.kind == "text" and fact.value.record_details]
        unresolved = [parsed.accepted_facts[i].quote for i in parsed.unresolved_links]
        unresolved.extend(item["raw"].get("quote", "") for item in parsed.rejected_facts if isinstance(item["raw"], dict))
        unresolved = [quote for quote in unresolved if isinstance(quote, str) and quote.strip() and quote in text]
        if unresolved:
            return any(not any(quote in report for report in reports) for quote in unresolved)
        return (parsed.needs_context or parsed.binding_unresolved) and not reports

    @staticmethod
    def _mark_missing_binding(parsed, state, text):
        if not parsed.clinical_content or not text.strip():
            parsed.binding_unresolved = False
            return
        question = state.interaction.pending.question if state.interaction.pending else None
        if InputInterpreter._chief_input(state):
            resolved = any(f.field == "S.cc" and f.value.kind == "symptom" and len(f.value.concept_ids) == 1
                and f.value.subject == "patient" and f.value.time_context != "past"
                and f.value.status in {"present", "uncertain"} for f in parsed.accepted_facts)
        elif question and question.target_id:
            resolved = any(question.target_id in f.value.concept_ids and f.value.attribute_id == question.attribute_id
                and f.value.status in {"present", "absent", "uncertain"}
                and f.value.subject == question.subject and (question.time_context == "unspecified" or f.value.time_context == question.time_context)
                and (not question.observation_id or f.value.observation_id in {None, question.observation_id})
                and (not question.episode_id or f.value.episode_id in {None, question.episode_id})
                and (not question.attribute_id or f.value.values or f.value.measurement)
                for f in parsed.accepted_facts)
        else:
            resolved = bool(parsed.accepted_facts)
        parsed.binding_unresolved = not resolved

    @staticmethod
    def _merge_recovery(state, original, expanded):
        accepted = list(original.accepted_facts)
        unresolved = set(original.unresolved_links)
        repaired = set()
        for fact in expanded.accepted_facts:
            linked = [i for i in unresolved if (fact.repair_of is None or fact.repair_of == accepted[i].repair_of)
                      and fact.quote == accepted[i].quote and fact.record_id == accepted[i].record_id]
            rejected = [item for item in original.rejected_facts if isinstance(item["raw"], dict)
                        and (fact.repair_of is None or fact.repair_of == item["index"])
                        and fact.quote == item["raw"].get("quote")]
            if len(linked) == 1 and not rejected:
                index, old = linked[0], accepted[linked[0]]
                same_fact = fact.model_dump(exclude={"value", "repair_of"}) == old.model_dump(exclude={"value", "repair_of"})
                same_value = fact.value.model_dump(exclude={"concept_ids", "status"}) == old.value.model_dump(exclude={"concept_ids", "status"})
                conservative = fact.value.status == old.value.status or (old.value.status == "present" and fact.value.status == "uncertain")
                if same_fact and same_value and conservative and fact.value.concept_ids:
                    fact.repair_of = old.repair_of
                    accepted[index] = fact
                    unresolved.remove(index)
                    continue
            elif len(rejected) == 1 and not linked:
                item = rejected[0]
                if not any(fact.record_id and fact.record_id == old.record_id for i, old in enumerate(accepted) if i not in unresolved):
                    fact.repair_of = item["index"]
                    accepted.append(fact)
                    repaired.add(item["index"])
                    continue
            elif fact.repair_of is None and (original.needs_context or original.binding_unresolved):
                if not any((fact.record_id and fact.record_id == old.record_id) or
                    (fact.value.subject, fact.value.observation_id, fact.value.episode_id, fact.value.concept_ids, fact.value.attribute_id)
                    == (old.value.subject, old.value.observation_id, old.value.episode_id, old.value.concept_ids, old.value.attribute_id)
                    for old in accepted):
                    accepted.append(fact)
                    continue
            state.interaction.issues.append("invalid_gateway_expansion")
        return ParseResult(accepted_facts=accepted,
            unresolved_links=sorted(unresolved) + [i for i in range(len(original.accepted_facts), len(accepted))
                if accepted[i].value.kind in {"symptom", "finding"} and not accepted[i].value.concept_ids
                and accepted[i].value.status in {"present", "uncertain"}],
            rejected_facts=[item for item in original.rejected_facts if item["index"] not in repaired] + expanded.rejected_facts,
            needs_context=expanded.needs_context, lookup_terms=expanded.lookup_terms,
            context_limited=expanded.context_limited, clinical_content=bool(accepted) or expanded.clinical_content,
            empathy=original.empathy or expanded.empathy)

    def _vocabulary(self, state, knowledge, text, *, expanded=False, lookup_terms=()):
        pending = state.interaction.pending
        chief_input = self._chief_input(state)
        required = list(filter(None, (pending.question.target_id, pending.question.attribute_id))) if pending else []
        def candidates():
            attribute = pending.question.attribute_id if pending else None
            allowed_values = set(knowledge.get_attribute_values(attribute)) if attribute else set()
            for term in lookup_terms:
                if attribute:
                    yield from (c for c in self._search(state, knowledge, term, kind="AttributeValue") if c in allowed_values)
                yield from self._search(state, knowledge, term)
            if attribute:
                yield from (c for c in knowledge.resolve_concept(text) if c in allowed_values)
                yield from (c for c in self._search(state, knowledge, text, kind="AttributeValue") if c in allowed_values)
            matches = self._search(state, knowledge, text)
            yield from matches[:8]
            if pending and pending.question.target_id:
                question = pending.question
                attrs = [question.attribute_id] if question.attribute_id else knowledge.get_symptom_attributes(question.target_id)
                for attribute in attrs:
                    yield attribute
                    yield from knowledge.get_target_values(question.target_id, attribute)
                    yield from knowledge.get_attribute_values(attribute)
            if chief_input:
                yield from self._search(state, knowledge, text, kind="FindingAttribute")[:8]
                yield from self._search(state, knowledge, text, kind="AttributeValue")[:8]
            yield from matches[8:]
            projected = self.interactions.project_context(state, pending.question if pending else None,
                                                          self._search(state, knowledge, text), expanded=expanded)
            for item in projected["records"]:
                value = item["value"]
                if value:
                    yield from value["concept_ids"]
                    yield from value["values"]
                    if value["attribute_id"]:
                        yield value["attribute_id"]
            for hypothesis in state.differential.hypotheses[:5]:
                for profile in knowledge.get_disease_patterns(hypothesis.disease_id):
                    yield profile.target
            yield from (concept["id"] for concept in knowledge.iter_concepts())
        count_limit = LIMITS.expanded_parser_concepts if expanded else LIMITS.parser_concepts
        byte_limit = LIMITS.expanded_parser_vocabulary_bytes if expanded else LIMITS.parser_vocabulary_bytes
        vocabulary = list(knowledge.iter_concepts(dict.fromkeys(required)))
        size = len(json.dumps(vocabulary, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if len(vocabulary) > count_limit or size > byte_limit:
            raise ValueError("Required question vocabulary exceeds parser limits")
        seen = {concept["id"] for concept in vocabulary}
        for ident in candidates():
            if len(vocabulary) >= count_limit:
                break
            if ident in seen:
                continue
            seen.add(ident)
            concept = next(knowledge.iter_concepts([ident]), None)
            if concept is None:
                continue
            extra = len(json.dumps(concept, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + bool(vocabulary)
            if size + extra > byte_limit:
                continue
            vocabulary.append(concept)
            size += extra
        return vocabulary, size

    def _fit_request(self, payload, *, required_count, byte_limit):
        vocabulary = payload["vocabulary"]
        if payload.get("chief_mapping_required"):
            first_symptom = next((i for i, c in enumerate(vocabulary) if c["kind"] == "Symptom"), None)
            if first_symptom is None:
                return None
            required_count = max(required_count, first_symptom + 1)
        preferred_count = min(len(vocabulary), max(required_count, 32))
        while True:
            binding = payload.get("binding_contract")
            if binding:
                value_ids = [c["id"] for c in vocabulary if c["id"] in binding["value_ids"]]
                binding["value_ids"] = value_ids
                properties = {"concept_ids": {"const": [binding["target_id"]]}}
                if binding["attribute_id"]:
                    properties.update(kind={"const": "attribute"}, attribute_id={"const": binding["attribute_id"]},
                                      values={"items": {"enum": value_ids} if value_ids else {"not": {}}})
                payload["schema"]["properties"]["facts"]["items"]["allOf"] = [{
                    "if": {"properties": {"record_id": {"const": payload["question"]["item_id"]}}, "required": ["record_id"]},
                    "then": {"properties": {"value": {"properties": properties}}}}]
            if payload.get("chief_mapping_required"):
                chief = {"properties": {"field": {"const": "S.cc"}, "value": {"properties": {
                    "kind": {"const": "symptom"}, "subject": {"const": "patient"},
                    "status": {"enum": ["present", "uncertain"]},
                    "time_context": {"enum": ["current", "unspecified"]},
                    "concept_ids": {"minItems": 1, "maxItems": 1,
                        "items": {"enum": [c["id"] for c in vocabulary if c["kind"] == "Symptom"]}}},
                    "required": ["kind", "subject", "status", "time_context", "concept_ids"]}},
                    "required": ["field", "value"]}
                selected = {"properties": {"facts": {"contains": chief}}, "required": ["facts"]}
                payload["schema"]["anyOf"] = [selected, {"properties": {"clinical_content": {"const": False}},
                                                        "required": ["clinical_content"]}]
                if payload["parser_pass"] == "primary":
                    payload["schema"]["anyOf"].append({"properties": {
                        "needs_context": {"const": True}, "lookup_terms": {"minItems": 1}},
                        "required": ["needs_context", "lookup_terms"]})
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            prompt = self.config.terminology_prompt if payload.get("task") == "terminology" else self.config.parser_prompt
            messages = [{"role": "system", "content": prompt}, {"role": "user", "content": encoded}]
            size = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if size <= byte_limit:
                return messages, size
            # Keep the current input, question, schema and required IDs intact.
            if len(vocabulary) > preferred_count:
                vocabulary.pop()
            elif payload["dialogue"]:
                payload["dialogue"].pop()
            elif payload["records"]:
                payload["records"].pop()
            elif payload.get("frozen_facts"):
                payload["frozen_facts"].pop()
            elif len(vocabulary) > required_count:
                vocabulary.pop()
            else:
                return None

    def _request_parse(self, state, knowledge, client, text, *, previous=None, compact=False, terminology=False):
        expanded = previous is not None
        pending = state.interaction.pending
        context = self.interactions.project_context(state, pending.question if pending else None,
                                                    self._search(state, knowledge, text), expanded=expanded)
        try:
            vocabulary, vocabulary_bytes = ([], 2) if terminology else self._vocabulary(state, knowledge, text, expanded=expanded,
                lookup_terms=previous.lookup_terms if previous else ())
        except ValueError:
            state.interaction.issues.append("gateway_required_vocabulary_overflow")
            return None
        payload = {"input": text, "question": pending.question.model_dump(exclude={"order", "priority", "selection_value"}) if pending else None,
                   "spoken_question": pending.content if pending else None, **context,
                   "schema": deepcopy(terminology_schema() if terminology else parser_schema()), "vocabulary": vocabulary,
                   "task": "terminology" if terminology else "gateway",
                   "parser_pass": "terminology" if terminology else "expansion" if expanded else "primary"}
        if pending and pending.question.target_id and not terminology:
            question = pending.question
            payload["binding_contract"] = {"target_id": question.target_id, "attribute_id": question.attribute_id,
                "value_ids": knowledge.get_attribute_values(question.attribute_id) if question.attribute_id else [],
                "answer_type": question.answer_type, "subject": question.subject, "time_context": question.time_context,
                "observation_id": question.observation_id, "episode_id": question.episode_id}
        event = next((event for event in reversed(state.interaction.empathy_events)
                      if event.status in {"pending", "attempted", "delivered"}), None)
        if event:
            payload["last_empathy"] = {"quote": event.quote, "intent": event.intent, "status": event.status}
        frozen_chief = previous and any(f.field == "S.cc" and f.value.kind == "symptom"
            and len(f.value.concept_ids) == 1 and f.value.subject == "patient"
            and f.value.time_context != "past" and f.value.status in {"present", "uncertain"}
            for f in previous.accepted_facts)
        if self._chief_input(state) and not terminology and not frozen_chief:
            payload["chief_mapping_required"] = True
        if previous:
            payload["unlinked_facts"] = [previous.accepted_facts[i].model_dump() for i in previous.unresolved_links]
            payload["rejected_facts"] = [{**item, "reason": str(item["reason"])[:240]} for item in previous.rejected_facts]
            payload["frozen_facts"] = [fact.model_dump() for i, fact in enumerate(previous.accepted_facts) if i not in previous.unresolved_links]
            payload["needs_context"] = previous.needs_context
            payload["lookup_terms"] = previous.lookup_terms
        byte_limit = (LIMITS.compact_gateway_request_bytes if compact else
                      LIMITS.expanded_gateway_request_bytes if expanded else LIMITS.gateway_request_bytes)
        if compact:
            byte_limit = min(byte_limit, state.interaction.model_history[-1]["parser_payload"]["request_bytes"] - 1)
        required = set(filter(None, (pending.question.target_id, pending.question.attribute_id))) if pending else set()
        fitted = self._fit_request(payload, required_count=len(required), byte_limit=byte_limit)
        if fitted is None:
            state.interaction.issues.append("gateway_request_overflow")
            return None
        messages, request_bytes = fitted
        vocabulary_bytes = len(json.dumps(vocabulary, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        previous_calls = len(state.interaction.model_history)
        content = self.model.complete(state, client, role="terminology" if terminology else "gateway", messages=messages)
        if len(state.interaction.model_history) > previous_calls:
            state.interaction.model_history[-1]["parser_payload"] = {
                "pass": payload["parser_pass"], "vocabulary_count": len(vocabulary), "vocabulary_bytes": vocabulary_bytes,
                "payload_bytes": len(messages[1]["content"].encode("utf-8")),
                "request_bytes": request_bytes, "request_byte_limit": byte_limit, "compact": compact,
                "context_bytes": len(json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
                "context_records": len(context["records"]), "context_turns": len(context["dialogue"])}
        if content is None:
            if (len(state.interaction.model_history) > previous_calls
                    and state.interaction.model_history[-1].get("error") == "CONTEXT_LIMIT_EXCEEDED"):
                return ParseResult(needs_context=True, context_limited=True)
            return None
        try:
            parsed = self._validate_facts(json.loads(content), state, knowledge, text,
                dialogue_ids={turn["id"] for turn in context["dialogue"]},
                supplied_records={item["id"] for item in context["records"]} | ({pending.question.item_id} if pending else set()),
                allowed={concept["id"] for concept in vocabulary},
                frozen_facts=previous.accepted_facts if previous else ())
            parsed = parsed if parsed is not None else ParseResult(needs_context=True)
            if terminology:
                allowed_facts = []
                for index, fact in enumerate(parsed.accepted_facts):
                    value = fact.value
                    if (value.kind != "text" or value.concept_ids or value.attribute_id or value.values
                            or value.measurement or fact.record_id is not None or not value.record_details):
                        parsed.rejected_facts.append({"index": index, "raw": fact.model_dump(), "reason": "not_record_only_terminology"})
                    elif not previous or not any(fact.quote == old.quote for i, old in enumerate(previous.accepted_facts)
                                                 if i not in previous.unresolved_links):
                        allowed_facts.append(fact)
                parsed.accepted_facts = allowed_facts
            elif not expanded:
                rejected_indices = {item["index"] for item in parsed.rejected_facts}
                indices = (i for i in range(len(parsed.accepted_facts) + len(rejected_indices)) if i not in rejected_indices)
                for fact, index in zip(parsed.accepted_facts, indices):
                    fact.repair_of = index
            self._mark_missing_binding(parsed, state, text)
            linked_chiefs = [fact for fact in parsed.accepted_facts if fact.field == "S.cc"
                and fact.value.kind == "symptom" and fact.value.subject == "patient"
                and fact.value.time_context != "past" and fact.value.status in {"present", "uncertain"}
                and len(fact.value.concept_ids) == 1]
            if payload.get("chief_mapping_required") and parsed.clinical_content and text.strip() and not linked_chiefs:
                parsed.needs_context = True
                state.interaction.issues.append("chief_mapping_unresolved")
            if len(state.interaction.model_history) > previous_calls:
                state.interaction.model_history[-1]["parser_result"] = {
                    "accepted_facts": len(parsed.accepted_facts), "linked_chief_facts": len(linked_chiefs),
                    "unlinked_facts": len(parsed.unresolved_links), "rejected_facts": len(parsed.rejected_facts),
                    "needs_context": parsed.needs_context, "binding_unresolved": parsed.binding_unresolved,
                    "clinical_content": parsed.clinical_content, "empathy": parsed.empathy.model_dump() if parsed.empathy else None,
                    "lookup_terms": parsed.lookup_terms}
            return parsed
        except (TypeError, ValueError):
            state.interaction.issues.append("invalid_gateway_output")
            return ParseResult(needs_context=True)

    def _validate_facts(self, raw, state, knowledge, text, **kwargs):
        try:
            return validate_facts(raw, state, knowledge, text, **kwargs)
        except (ValidationError, ValueError, TypeError):
            state.interaction.issues.append("invalid_input_facts")
            return None

    def _apply_facts(self, state: WorkflowState, parsed: ParseResult, source_id: str) -> None:
        pending = state.interaction.pending
        changed = False
        for index, fact in enumerate(parsed.accepted_facts):
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
            if value.kind in {"symptom", "finding", "attribute", "context"}:
                changed = changed or existing is None or existing.value is None or (
                    value.model_dump(exclude={"text", "record_category", "record_details"})
                    != existing.value.model_dump(exclude={"text", "record_category", "record_details"}))
            refs = list(dict.fromkeys([*(existing.source_refs if existing else []), source_id]))
            scope = existing.scope if existing else state.session.current
            context_refs = list(dict.fromkeys([*(existing.context_refs if existing else []), *fact.context_refs]))
            state.case.put(field, RecordItem(id=item_id, scope=scope, status="done", value=value,
                                            source_refs=refs, context_refs=context_refs))

        if changed:
            state.differential.clinical_revision += 1
