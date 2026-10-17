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
        elif text.strip() and not state.session.doctor_successes:
            parsed = self._parse_text(state, knowledge, client, text)
        elif "facts" in facts:
            parsed = self._validate_facts({"facts": facts["facts"]}, state, knowledge, text)
        else:
            fixed = ParsedInput() if initial and not text.strip() else (None if initial else fixed_reply(self.config, state, text, knowledge))
            parsed = ParseResult(accepted_facts=fixed.facts) if fixed is not None else self._parse_text(state, knowledge, client, text)
        if parsed is not None:
            self._apply_facts(state, parsed, source_id)
            interaction.parse_rejections.extend({"source_id": source_id, **item} for item in parsed.rejected_facts)
            if parsed.rejected_facts:
                interaction.issues.append("partial_input_facts")
        if interaction.termination:
            return
        unresolved = parsed is None or (parsed.rejected_facts or parsed.needs_context) and not any(
            action and (fact.record_id == action.question.item_id or (
                action.question.target_id in fact.value.concept_ids
                and fact.value.attribute_id == action.question.attribute_id)) for fact in parsed.accepted_facts)
        if unresolved and not incoming.get("error"):
            self.interactions.request_clarification(state, action.question if action else None)
        if action:
            self.questions.complete_unresolved(state, action, text, source_id)
        self.interactions.consume_input(state)

    @staticmethod
    def _chief_input(state):
        if any(item.value.concept_ids for item in state.case.chief_complaints()):
            return False
        pending = state.interaction.pending
        return pending is None or (pending.question.purpose in {"chief", "clarification"}
                                   and pending.question.field == "S.cc")

    def _search(self, state, knowledge, text):
        kind = "Symptom" if self._chief_input(state) else None
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
        if not (parsed.unresolved_links or parsed.rejected_facts or parsed.needs_context):
            return parsed
        expanded = self._request_parse(state, knowledge, client, text, previous=parsed, compact=parsed.context_limited)
        if expanded is None:
            return parsed
        accepted = list(parsed.accepted_facts)
        unresolved = set(parsed.unresolved_links)
        repaired_indices = set()
        def repair_key(raw):
            value = raw.get("value") if isinstance(raw, dict) else None
            if not isinstance(value, dict):
                return None
            return (raw.get("quote"), raw.get("record_id"), value.get("kind"), value.get("attribute_id"),
                    value.get("subject", "patient"), value.get("observation_id"), value.get("episode_id"))
        for fact in expanded.accepted_facts:
            matches = [index for index in unresolved if
                       fact.model_dump(exclude={"value"}) == accepted[index].model_dump(exclude={"value"})
                       and fact.value.model_dump(exclude={"concept_ids"}) == accepted[index].value.model_dump(exclude={"concept_ids"})]
            if len(matches) == 1 and fact.value.concept_ids:
                accepted[matches[0]] = fact
                unresolved.remove(matches[0])
            elif (parsed.needs_context or any(repair_key(item["raw"]) == repair_key(fact.model_dump())
                                             for item in parsed.rejected_facts)) and not any(
                    (fact.record_id is not None and fact.record_id == original.record_id)
                    or (fact.value.subject, fact.value.observation_id, fact.value.episode_id, fact.value.concept_ids, fact.value.attribute_id)
                    == (original.value.subject, original.value.observation_id, original.value.episode_id,
                        original.value.concept_ids, original.value.attribute_id) for original in accepted):
                if not any(f.model_dump() == fact.model_dump() for f in accepted):
                    accepted.append(fact)
                matching = [item["index"] for item in parsed.rejected_facts
                            if repair_key(item["raw"]) == repair_key(fact.model_dump())]
                if len(matching) == 1:
                    repaired_indices.add(matching[0])
            else:
                state.interaction.issues.append("invalid_gateway_expansion")
        return ParseResult(accepted_facts=accepted, unresolved_links=sorted(unresolved),
            rejected_facts=[item for item in parsed.rejected_facts if item["index"] not in repaired_indices] + expanded.rejected_facts,
            needs_context=expanded.needs_context, lookup_terms=expanded.lookup_terms)

    def _vocabulary(self, state, knowledge, text, *, expanded=False, lookup_terms=()):
        pending = state.interaction.pending
        chief_input = self._chief_input(state)
        required = list(filter(None, (pending.question.target_id, pending.question.attribute_id))) if pending else []
        def candidates():
            for term in lookup_terms:
                yield from self._search(state, knowledge, term)
            yield from self._search(state, knowledge, text)
            if pending and pending.question.target_id:
                question = pending.question
                attrs = [question.attribute_id] if question.attribute_id else knowledge.get_symptom_attributes(question.target_id)
                for attribute in attrs:
                    yield attribute
                    yield from knowledge.get_target_values(question.target_id, attribute)
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
            if concept is None or (chief_input and concept["kind"] != "Symptom"):
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
                payload["schema"]["anyOf"] = [selected]
                if payload["parser_pass"] == "primary":
                    payload["schema"]["anyOf"].append({"properties": {
                        "needs_context": {"const": True}, "lookup_terms": {"minItems": 1}},
                        "required": ["needs_context", "lookup_terms"]})
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            messages = [{"role": "system", "content": self.config.parser_prompt}, {"role": "user", "content": encoded}]
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
            elif len(vocabulary) > required_count:
                vocabulary.pop()
            else:
                return None

    def _request_parse(self, state, knowledge, client, text, *, previous=None, compact=False):
        expanded = previous is not None
        pending = state.interaction.pending
        context = self.interactions.project_context(state, pending.question if pending else None,
                                                    self._search(state, knowledge, text), expanded=expanded)
        try:
            vocabulary, vocabulary_bytes = self._vocabulary(state, knowledge, text, expanded=expanded,
                lookup_terms=previous.lookup_terms if previous else ())
        except ValueError:
            state.interaction.issues.append("gateway_required_vocabulary_overflow")
            return None
        payload = {"input": text, "question": pending.question.model_dump(exclude={"order", "priority", "selection_value"}) if pending else None,
                   "spoken_question": pending.content if pending else None, **context,
                   "schema": deepcopy(parser_schema()), "vocabulary": vocabulary,
                   "parser_pass": "expansion" if expanded else "primary"}
        if self._chief_input(state):
            payload["chief_mapping_required"] = True
        if previous:
            payload["unlinked_facts"] = [previous.accepted_facts[i].model_dump() for i in previous.unresolved_links]
            payload["rejected_facts"] = previous.rejected_facts
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
        content = self.model.complete(state, client, role="gateway", messages=messages)
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
                supplied_records={item["id"] for item in context["records"]},
                allowed={concept["id"] for concept in vocabulary})
            parsed = parsed if parsed is not None else ParseResult(needs_context=True)
            linked_chiefs = [fact for fact in parsed.accepted_facts if fact.field == "S.cc"
                and fact.value.kind == "symptom" and fact.value.subject == "patient"
                and fact.value.time_context != "past" and fact.value.status in {"present", "uncertain"}
                and len(fact.value.concept_ids) == 1]
            if self._chief_input(state) and text.strip() and not linked_chiefs:
                parsed.needs_context = True
                state.interaction.issues.append("chief_mapping_unresolved")
            if len(state.interaction.model_history) > previous_calls:
                state.interaction.model_history[-1]["parser_result"] = {
                    "accepted_facts": len(parsed.accepted_facts), "linked_chief_facts": len(linked_chiefs),
                    "unlinked_facts": len(parsed.unresolved_links), "rejected_facts": len(parsed.rejected_facts),
                    "needs_context": parsed.needs_context, "lookup_terms": parsed.lookup_terms}
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
                    value.model_dump(exclude={"text"}) != existing.value.model_dump(exclude={"text"}))
            refs = list(dict.fromkeys([*(existing.source_refs if existing else []), source_id]))
            scope = existing.scope if existing else state.session.current
            context_refs = list(dict.fromkeys([*(existing.context_refs if existing else []), *fact.context_refs]))
            state.case.put(field, RecordItem(id=item_id, scope=scope, status="done", value=value,
                                            source_refs=refs, context_refs=context_refs))

        if changed:
            state.differential.clinical_revision += 1
