import hashlib
import json
import re
from copy import deepcopy
from functools import lru_cache

from pydantic import ValidationError

from .rules.input import validate_facts
from .rules.limits import LIMITS
from .rules.normalization import (candidate_contracts, compact_schema, force_mapping,
                                  mapping_schema, measurement_value, numeric_schema, statement_outcome, strict_json, validate_mapping)
from .state.models import (ClinicalValue, ContextInput, ContextStatement, Fact, InputOutcome,
                           EmpathySignal, ParseResult, PatientContextEntry, PatientContextFact, PatientReport, RecordItem)


@lru_cache(maxsize=1)
def parser_schema():
    schema = compact_schema(ContextInput.model_json_schema())
    schema["$defs"]["ExpectedValue"] = numeric_schema()
    schema["required"] = ["statements"]
    return schema


class InputInterpreter:
    def __init__(self, config, model, questions, interactions):
        self.config, self.model = config, model
        self.questions, self.interactions = questions, interactions

    def process_input(self, state, knowledge, client):
        interaction = state.interaction
        if interaction.termination:
            return
        incoming, action = interaction.incoming, interaction.pending
        if incoming is None:
            if action:
                state.stop("unknown", "missing_action_response")
            return
        initial = "initial" in incoming
        if not initial and action is None:
            state.stop("failed", "unexpected_action_response")
            return
        source = "initial" if initial else action.request_id
        if initial:
            self.interactions.record_initial(state, incoming["initial"])
            text = str(incoming["initial"].get("opening", ""))
            initial_data = incoming["initial"].get("vital_signs")
            if initial_data:
                text += "\n" + (initial_data if isinstance(initial_data, str) else json.dumps(initial_data, ensure_ascii=False))
        else:
            text = incoming.get("content" if action.question.kind == "SAY" else "result", "")
            text = text if isinstance(text, str) else ""
        if action and (action.question.purpose == "education" or state.session.current == "Education"):
            if action.question.purpose == "education":
                self.questions.complete_unresolved(state, action, "", source)
            elif (item := state.case.get(action.question.item_id)) and item.status == "unasked":
                state.case.remove({item.id})
            self.interactions.consume_input(state)
            return
        parsed = self._parse_text(state, knowledge, client, text) if not incoming.get("error") else ParseResult()
        if parsed is not None:
            self._apply_facts(state, parsed, source)
            interaction.parse_rejections.extend({"source_id": source, **item} for item in parsed.rejected_facts)
            interaction.parse_recoveries.extend({"source_id": source, **item} for item in parsed.recovery_history)
            if parsed.empathy:
                self.interactions.queue_empathy(state, parsed.empathy, source)
        if not any(report.source_id == source for report in interaction.patient_reports):
            interaction.patient_reports.append(PatientReport(source_id=source, text=text))
        if action and not interaction.termination:
            self.questions.complete_unresolved(state, action, "", source)
            if (action.question.purpose == "context" and action.question.coverage and action.question.target_id
                    and any(e.id == source and e.delivered for e in interaction.history)
                    and action.question.target_id not in state.questions.context_coverage):
                state.questions.context_coverage.append(action.question.target_id)
        self.interactions.consume_input(state)
        if action and action.question.purpose in {"greeting", "empathy"}:
            item = state.case.get(action.question.item_id)
            if item and (item.status == "unasked" or not item.value or not item.value.concept_ids):
                state.case.remove({item.id})

    @staticmethod
    def _size(messages):
        return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))

    def _fit_request(self, prompt, payload, byte_limit):
        while True:
            messages = [{"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)}]
            if self._size(messages) <= byte_limit:
                return messages
            if payload.get("dialogue"):
                payload["dialogue"].pop()
            elif payload.get("records"):
                payload["records"].pop()
            elif payload.get("patient_context"):
                payload["patient_context"].pop(next(iter(payload["patient_context"])))
            else:
                return None

    def _call(self, state, client, payload, prompt, *, limit, max_tokens=None):
        fitted = self._fit_request(prompt, payload, limit)
        if fitted is None:
            state.interaction.issues.append("gateway_request_overflow")
            return None
        previous = len(state.interaction.model_history)
        content = self.model.complete(state, client, role="gateway", messages=fitted, max_tokens=max_tokens)
        if len(state.interaction.model_history) > previous:
            state.interaction.model_history[-1]["parser_payload"] = {
                "pass": payload["phase"], "request_bytes": self._size(fitted), "request_byte_limit": limit,
                "statement_indices": payload.get("statement_indices", []),
                "context_records": len(payload.get("records", [])), "context_turns": len(payload.get("dialogue", []))}
        return content

    def _read_context(self, state, raw, payload, text, question, previous=None, indices=None):
        if not isinstance(raw, dict) or not isinstance(raw.get("statements"), list):
            raise ValueError("context_requires_statement_array")
        ContextInput.model_validate({**raw, "statements": [], "empathy": None, "patient_context": []})
        rows = raw["statements"]
        if indices is not None and len(rows) != len(indices):
            raise ValueError("context_repair_length_mismatch")
        context = previous.model_copy(deep=True) if previous else ContextInput(
            statements=[ContextStatement(quote=text or " ", role="unknown") for _ in rows])
        positions = indices if indices is not None else list(range(len(rows)))
        supplied = {item["id"] for item in payload["records"]}
        observations = {item["value"].get("observation_id") for item in payload["records"] if item.get("value")}
        episodes = {item["value"].get("episode_id") for item in payload["records"] if item.get("value")}
        if question:
            observations.add(question.observation_id)
            episodes.add(question.episode_id)
        errors = []
        for index, row in zip(positions, rows):
            try:
                statement = ContextStatement.model_validate(row)
                if not statement.quote.strip() or statement.quote not in text:
                    raise ValueError("statement_not_in_current_input")
                if statement.correction_id and statement.correction_id not in supplied:
                    raise ValueError("correction_outside_transmitted_context")
                if statement.observation_id and statement.observation_id not in observations:
                    raise ValueError("observation_outside_transmitted_context")
                if statement.episode_id and statement.episode_id not in episodes:
                    raise ValueError("episode_outside_transmitted_context")
                if statement.measurement and statement.measurement.kind not in {"quantity", "interval"}:
                    raise ValueError("context_measurement_must_be_numeric")
                if statement.anchor is not None and statement.anchor >= len(context.statements):
                    raise ValueError("unknown_statement_anchor")
                context.statements[index] = statement
            except (TypeError, ValueError, ValidationError) as error:
                reason = str(error) if not isinstance(error, ValidationError) else json.dumps(
                    [{"field": list(e["loc"]), "reason": e["msg"]} for e in error.errors()], ensure_ascii=False)
                errors.append({"index": index, "reason": reason[:320], "raw": row})
        for index in positions:
            statement = context.statements[index]
            if statement.anchor is not None:
                anchor = context.statements[statement.anchor]
                if (statement.measurement or statement.focus == "attribute") and anchor.focus == "target" and (
                        anchor.subject, anchor.subject_member) == (statement.subject, statement.subject_member):
                    statement.target_terms = list(dict.fromkeys([*anchor.target_terms, *statement.target_terms]))[:8]
                if statement.role != "clinical" or (anchor.subject, anchor.subject_member, anchor.time_context) != (
                        statement.subject, statement.subject_member, statement.time_context):
                    statement.anchor = None
                    state.interaction.parse_recoveries.append({"stage": payload["phase"], "index": index,
                                                              "reason": "detach_cross_scope_anchor"})
        for row in raw.get("patient_context", []) if isinstance(raw.get("patient_context", []), list) else []:
            try:
                fact = PatientContextFact.model_validate(row)
                if fact.quote not in text:
                    raise ValueError("ungrounded_patient_context")
                context.patient_context.append(fact)
            except (TypeError, ValueError, ValidationError):
                state.interaction.issues.append("invalid_patient_context")
        ambiguous = {fact.key for fact in context.patient_context
                     if len({f.value for f in context.patient_context if f.key == fact.key}) > 1}
        if ambiguous:
            state.interaction.issues.append("conflicting_patient_context")
        context.patient_context = list({fact.key: fact for fact in context.patient_context if fact.key not in ambiguous}.values())
        if raw.get("empathy") is not None:
            try:
                signal = EmpathySignal.model_validate(raw["empathy"])
                if signal.quote not in text or question and question.kind == "EXAM":
                    raise ValueError("ungrounded_empathy")
                context.empathy = signal
            except (TypeError, ValueError, ValidationError):
                state.interaction.issues.append("invalid_empathy_signal")
        return context, errors

    def _context(self, state, knowledge, client, text):
        pending = state.interaction.pending
        question = pending.question if pending else None
        projected = self.interactions.project_context(state, question, knowledge.search_concepts(text), expanded=True)
        payload = {"task": "input_context", "phase": "context", "input": text,
            "input_kind": "initial" if pending is None else "reply", "turn": LIMITS.turns - state.session.turns_remaining,
            "question": question.model_dump(exclude={"assessment"}) if question else None,
            "spoken_question": pending.content if pending else None,
            "patient_context": {key: value.model_dump() for key, value in state.case.patient_context.items()},
            "schema": deepcopy(parser_schema()), **projected}
        if pending is None and state.interaction.incoming:
            payload["initial_data"] = state.interaction.incoming.get("initial", {}).get("vital_signs", {})
        context, indices = None, None
        for attempt in range(2):
            payload["phase"] = "context_repair" if attempt else "context"
            limit = LIMITS.expanded_gateway_request_bytes if attempt else LIMITS.gateway_request_bytes
            if attempt and state.interaction.model_history and state.interaction.model_history[-1].get("error") == "CONTEXT_LIMIT_EXCEEDED":
                limit = LIMITS.compact_gateway_request_bytes
            content = self._call(state, client, payload, self.config.parser_prompt, limit=limit,
                                 max_tokens=LIMITS.gateway_recovery_tokens if attempt else LIMITS.gateway_tokens)
            if state.interaction.termination:
                break
            try:
                context, errors = self._read_context(state, strict_json(content), payload, text, question, context, indices)
                if not errors:
                    break
                state.interaction.parse_rejections.extend({"stage": payload["phase"], **error} for error in errors)
                indices = [error["index"] for error in errors]
                payload["statement_indices"] = indices
                payload["repair_statements"] = errors
                payload["validation_errors"] = [f"{e['index']}: {e['reason']}" for e in errors]
                payload["frozen_statements"] = [{"index": i, "quote": s.quote, "subject": s.subject,
                    "subject_member": s.subject_member, "time_context": s.time_context}
                    for i, s in enumerate(context.statements) if i not in indices]
                payload["schema"]["properties"]["statements"].update(minItems=len(indices), maxItems=len(indices))
            except (TypeError, ValueError, ValidationError) as error:
                reason = state.interaction.model_history[-1].get("error", str(error)) if content is None and state.interaction.model_history else str(error)
                payload["validation_errors"] = [reason[:320]]
                state.interaction.parse_rejections.append({"stage": payload["phase"], "reason": reason[:320]})
        if context is None:
            context = ContextInput(statements=[ContextStatement(quote=text, role="unknown")] if text.strip() else [])
        # Exact nonanswers are a post-model guard, never a model-call shortcut.
        reply = text.strip().rstrip(self.config.texts.reply_trailing_punctuation)
        if reply in self.config.texts.unknown_replies:
            context.statements = [ContextStatement(quote=text, role="unknown")]
        elif reply in set(self.config.texts.education_acknowledgements) - set(self.config.texts.present_replies):
            context.statements = [ContextStatement(quote=text, role="nonclinical")]
        ambiguous_chief = [i for i, s in enumerate(context.statements) if s.primary_concern
            and s.subject == "patient" and s.time_context != "past" and s.focus == "target"
            and statement_outcome(s) == "unknown"]
        if pending is None and ambiguous_chief:
            repair = deepcopy(payload)
            repair.update(phase="initial_chief_repair", statement_indices=ambiguous_chief,
                repair_statements=[{"index": i, "statement": context.statements[i].model_dump(exclude_defaults=True)}
                                   for i in ambiguous_chief],
                validation_errors=["Separate the reported presenting observation from uncertainty about its cause. Preserve genuinely unresolved existence as unknown."])
            repair["frozen_statements"] = [{"index": i, "quote": s.quote, "subject": s.subject,
                "subject_member": s.subject_member, "time_context": s.time_context}
                for i, s in enumerate(context.statements) if i not in ambiguous_chief]
            repair["schema"]["properties"]["statements"].update(minItems=len(ambiguous_chief), maxItems=len(ambiguous_chief))
            content = self._call(state, client, repair, self.config.parser_prompt,
                                 limit=LIMITS.expanded_gateway_request_bytes, max_tokens=LIMITS.gateway_tokens)
            try:
                context, errors = self._read_context(state, strict_json(content), repair, text, question, context, ambiguous_chief)
                state.interaction.parse_rejections.extend({"stage": repair["phase"], **error} for error in errors)
            except (TypeError, ValueError, ValidationError) as error:
                state.interaction.parse_rejections.append({"stage": repair["phase"], "reason": str(error)[:320]})
        state.interaction.interpretations.append({"source_ref": pending.request_id if pending else "initial",
            "context": context.model_dump(), "input": text,
            "source_spans": [{"statement_index": i, "positions": [[m.start(), m.end()]
                for m in re.finditer(re.escape(s.quote), text)]} for i, s in enumerate(context.statements)]})
        return context, payload

    def _mapping_payload(self, context_payload, statements, indices, contracts, phase, feedback=None):
        rows = []
        for i in indices:
            row = statements[i].model_dump(exclude_none=True, exclude_defaults=True)
            row["focus"] = "attribute" if any(c["attributes"] for c in contracts[i]) else statements[i].focus
            if statements[i].measurement:
                row["measurement"] = measurement_value(statements[i].measurement)
            rows.append({**row, "candidates": contracts[i]})
        payload = {"task": "input_mapping", "phase": phase, "input": context_payload["input"],
            "question": context_payload["question"], "spoken_question": context_payload["spoken_question"],
            "dialogue": deepcopy(context_payload.get("dialogue", [])), "statement_indices": indices,
            "statements": rows,
            "schema": {"type": "array", "prefixItems": [mapping_schema(contracts[i]) for i in indices],
                       "minItems": len(indices), "maxItems": len(indices)}}
        if feedback:
            payload["validation_errors"] = [{"statement_index": i, **feedback[i]} for i in indices if i in feedback]
        return payload

    def _map_batch(self, state, knowledge, client, context_payload, statements, batch, contracts, mappings, forced, result):
        question = state.interaction.pending.question if state.interaction.pending else None
        remaining, format_used, feedback = list(batch), False, {}
        for phase in ("mapping", "binding_repair", "forced"):
            if not remaining or state.interaction.termination:
                break
            if phase != "mapping":
                for i in remaining:
                    contracts[i] = candidate_contracts(knowledge, statements[i], question, expanded=True,
                                                       complete=phase == "forced")[:32]
            payload = self._mapping_payload(context_payload, statements, remaining, contracts, phase, feedback)
            limit = LIMITS.gateway_request_bytes if phase == "mapping" else LIMITS.expanded_gateway_request_bytes
            while self._fit_request(self.config.normalization_prompt, payload, limit) is None:
                largest = max(remaining, key=lambda i: len(contracts[i]))
                if len(contracts[largest]) <= 1:
                    break
                contracts[largest].pop()
                payload = self._mapping_payload(context_payload, statements, remaining, contracts, phase, feedback)
            content = self._call(state, client, payload, self.config.normalization_prompt, limit=limit,
                max_tokens=LIMITS.gateway_recovery_tokens if phase == "forced" else LIMITS.gateway_tokens)
            for attempt in range(2 if not format_used else 1):
                try:
                    wire = strict_json(content)
                    if not isinstance(wire, list) or len(wire) != len(remaining):
                        raise ValueError("mapping_batch_length_or_type")
                    break
                except (TypeError, ValueError) as error:
                    result.rejected_facts.append({"stage": phase, "reason": str(error)})
                    wire = [{} for _ in remaining]
                    if attempt or format_used or state.interaction.termination:
                        break
                    format_used = True
                    payload.update(phase="format_repair", repair_phase=phase, validation_errors=[str(error)])
                    if state.interaction.model_history and state.interaction.model_history[-1].get("error") == "CONTEXT_LIMIT_EXCEEDED":
                        limit = LIMITS.compact_gateway_request_bytes
                        while self._fit_request(self.config.normalization_prompt, payload, limit) is None:
                            largest = max(remaining, key=lambda i: len(contracts[i]))
                            if len(contracts[largest]) <= 1:
                                break
                            contracts[largest].pop()
                            payload = self._mapping_payload(context_payload, statements, remaining, contracts, "format_repair")
                            payload["repair_phase"] = phase
                    content = self._call(state, client, payload, self.config.normalization_prompt, limit=limit,
                                         max_tokens=LIMITS.gateway_recovery_tokens)
            unresolved = []
            for i, mapping in zip(remaining, wire):
                try:
                    if not validate_mapping(mapping, statements[i], contracts[i]):
                        feedback[i] = {"reason": "unresolved_mapping"}
                        unresolved.append(i)
                        continue
                    mappings[i] = mapping
                    if phase == "forced":
                        forced[i] = "model"
                except (TypeError, ValueError, ValidationError) as error:
                    feedback[i] = {"reason": str(error)[:240]}
                    result.rejected_facts.append({"index": i, "stage": phase, "raw": mapping, "reason": str(error)})
                    unresolved.append(i)
            result.recovery_history.append({"pass": phase, "accepted_facts": len(remaining) - len(unresolved),
                                            "rejected_facts": [], "unresolved_links": unresolved})
            remaining = unresolved
        if not state.interaction.termination:
            for i in remaining:
                contracts[i] = candidate_contracts(knowledge, statements[i], question, expanded=True, complete=True)
                mappings[i] = force_mapping(statements[i], contracts[i])
                if mappings[i]:
                    forced[i] = "deterministic"

    def _parse_text(self, state, knowledge, client, text):
        pending = state.interaction.pending
        question = pending.question if pending else None
        source = pending.request_id if pending else "initial"
        context, context_payload = self._context(state, knowledge, client, text)
        statements = context.statements
        result = ParseResult(patient_context=context.patient_context, empathy=context.empathy,
                             valid_output=True, clinical_content=any(s.role == "clinical" for s in statements), audit_refs=[source])
        contracts = {i: candidate_contracts(knowledge, s, question) for i, s in enumerate(statements)}
        mappings, forced = [{} for _ in statements], {}
        waiting = [i for i, s in enumerate(statements) if statement_outcome(s) is None]
        batches, batch = [], []
        for index in waiting:
            trial = self._mapping_payload(context_payload, statements, [*batch, index], contracts, "mapping")
            if batch and self._fit_request(self.config.normalization_prompt, trial, LIMITS.gateway_request_bytes) is None:
                batches.append(batch)
                batch = []
            batch.append(index)
        if batch:
            batches.append(batch)
        for batch in batches:
            self._map_batch(state, knowledge, client, context_payload, statements, batch, contracts, mappings, forced, result)
        facts = []
        for index, statement in enumerate(statements):
            decoded = validate_mapping(mappings[index], statement, contracts[index])
            statement_id = f"{source}:statement:{index}"
            for target, attribute, values, measurement, status in decoded:
                occurrence = statement.anchor if statement.anchor is not None else index
                same_question = question and target == question.target_id and statement.subject == question.subject
                observation = statement.observation_id or (question.observation_id if same_question else None)
                episode = statement.episode_id or (question.episode_id if same_question else None)
                if attribute and not observation:
                    previous = [item.value for _, item in state.case.current_entries() if item.value and target in item.value.concept_ids
                        and item.value.kind in {"symptom", "finding"} and item.value.subject == statement.subject
                        and item.value.subject_member == statement.subject_member and item.value.time_context == statement.time_context]
                    keys = {(v.observation_id, v.episode_id) for v in previous}
                    if len(keys) == 1:
                        observation, episode = next(iter(keys))
                observation = observation or "observation:" + hashlib.sha256(f"{source}:{occurrence}".encode()).hexdigest()[:24]
                episode = episode or observation
                kind = "attribute" if attribute else "context" if knowledge.has_type(target, "ContextFactor") else (
                    "finding" if question and question.kind == "EXAM" else "symptom")
                field = "O.exam" if question and question.kind == "EXAM" else "S.hpi" if attribute else (
                    "S.cc" if kind == "symptom" and status == "present" and statement.subject == "patient" and statement.time_context != "past"
                    and (not state.case.primary_chief or statement.primary_concern or question and question.purpose == "chief") else "S.ros")
                value = ClinicalValue(kind=kind, text=statement.quote, status=status, concept_ids=[target],
                    attribute_id=attribute, values=values, measurement=measurement,
                    observation_id=observation, episode_id=episode, subject=statement.subject,
                    subject_member=statement.subject_member, reported_by=statement.reported_by,
                    time_context=statement.time_context,
                    record_category=None if field == "S.cc" else statement.record_category,
                    primary_concern=statement.primary_concern and kind == "symptom" and statement.time_context != "past",
                    polarity_scope=statement.polarity_scope,
                    mapping_status="forced" if index in forced else "exact", forced_by=forced.get(index))
                facts.append(Fact(field=field, quote=statement.quote, value=value, statement_id=statement_id,
                    record_id=statement.correction_id, correction=bool(statement.correction_id), mapping=mappings[index]))
            outcome = statement_outcome(statement) or ("forced" if index in forced else "mapped" if decoded else "unsupported")
            result.outcomes.append(InputOutcome(source_ref=source, statement_id=statement_id, state=outcome,
                question_id=question.item_id if question else None,
                record_category=statement.record_category or (question.record_category if question else None),
                target_id=question.target_id if question else None, attribute_id=question.attribute_id if question else None,
                reason="no_compatible_database_slot" if outcome == "unsupported" else None))
        bases = {(v.subject, v.subject_member, v.observation_id, v.episode_id, v.time_context, target)
                 for v in [*(f.value for f in facts), *(item.value for _, item in state.case.current_entries() if item.value)]
                 if v.kind in {"symptom", "finding"} and v.status == "present" for target in v.concept_ids}
        for fact in facts:
            value = fact.value
            if value.measurement and not all((value.subject, value.subject_member, value.observation_id,
                    value.episode_id, value.time_context, target) in bases for target in value.concept_ids):
                value.evidence_use = "record_only"
        validated = self._validate_facts({"facts": [f.model_dump() for f in facts]}, state, knowledge, text)
        if validated:
            result.accepted_facts = validated.accepted_facts
            result.rejected_facts.extend(validated.rejected_facts)
        admitted = {f.statement_id for f in result.accepted_facts}
        for i, outcome in enumerate(result.outcomes):
            if outcome.state in {"mapped", "forced"} and outcome.statement_id not in admitted:
                mappings[i] = {}
                outcome.state, outcome.reason = "unsupported", "fact_validation_rejected"
        result.mappings = mappings
        result.fact_metadata = [{"statement_id": o.statement_id, "subject": s.subject,
            "subject_member": s.subject_member, "time_context": s.time_context, "polarity_scope": s.polarity_scope,
            "forced_by": forced.get(i)} for i, (s, o) in enumerate(zip(statements, result.outcomes))]
        json.dumps(result.mappings, ensure_ascii=False, allow_nan=False)
        state.interaction.interpretations[-1]["result"] = result.model_dump(exclude={"accepted_facts", "patient_context", "empathy"})
        return result

    def _validate_facts(self, raw, state, knowledge, text, **kwargs):
        try:
            return validate_facts(raw, state, knowledge, text, **kwargs)
        except (ValidationError, ValueError, TypeError):
            state.interaction.issues.append("invalid_input_facts")
            return None

    def _apply_facts(self, state, parsed, source):
        pending, assigned = state.interaction.pending, {}
        for context in parsed.patient_context:
            state.case.patient_context[context.key] = PatientContextEntry(value=context.value, quote=context.quote, source_refs=[source])
        for index, fact in enumerate(parsed.accepted_facts):
            value = fact.value.model_copy(deep=True)
            value.text, value.record_details, value.quantities = "", [], []
            prior = state.case.get(fact.record_id) if fact.record_id else None
            ident = fact.record_id if prior and prior.status == "done" and prior.value else f"{source}:fact:{index}"
            existing = state.case.get(ident)
            item = RecordItem(id=ident, scope=existing.scope if existing else state.session.current, status="done", value=value,
                source_refs=list(dict.fromkeys([*(existing.source_refs if existing else []), source])),
                context_refs=fact.context_refs, resolves=[pending.question.clarifies_id] if pending and pending.question.clarifies_id else [],
                acquisition=pending.question.kind if pending else "initial", mapping=fact.mapping)
            state.case.put(fact.field, item)
            if fact.statement_id:
                assigned.setdefault(fact.statement_id, []).append(ident)
            if pending:
                q = pending.question
                if ((q.target_id in value.concept_ids and q.attribute_id == value.attribute_id and q.subject == value.subject)
                        or q.record_category and q.record_category == value.record_category):
                    state.questions.answered_fact_ids.setdefault(q.item_id, []).append(ident)
        for outcome in parsed.outcomes:
            outcome.fact_ids = assigned.get(outcome.statement_id, [])
            if outcome.state in {"mapped", "forced"} and not outcome.fact_ids:
                outcome.state, outcome.reason = "unsupported", "fact_validation_rejected"
            state.case.outcomes.append(outcome)
        if pending:
            outcomes = [o.state for o in parsed.outcomes]
            state.questions.answer_outcomes[pending.question.item_id] = (
                "mapped" if state.questions.answered_fact_ids.get(pending.question.item_id) else
                "not_applicable" if "not_applicable" in outcomes else "unknown" if "unknown" in outcomes else
                "unsupported" if "unsupported" in outcomes else "nonclinical")
        if parsed.accepted_facts:
            state.differential.clinical_revision += 1
        conflicts = [item.id for _, item in state.case.current_entries() if item.value
                     and item.value.status == "uncertain" and state.case.get(item.id).value.status in {"present", "absent"}]
        if conflicts:
            state.case.outcomes.append(InputOutcome(source_ref=source, statement_id=f"{source}:conflict", state="conflict",
                question_id=pending.question.item_id if pending else None, fact_ids=conflicts, reason="conflicting_current_facts"))
            self.interactions.request_clarification(state, pending.question if pending else None)
        if not state.case.fixed_diagnosis:
            chiefs = state.case.chief_complaints()
            if sum(item.value.primary_concern for item in chiefs) == 1 or len(chiefs) > 1 and not any(
                    item.value.primary_concern for item in chiefs):
                state.case.primary_chief = None
            state.case.select_primary()
        if state.interaction.interpretations:
            state.interaction.interpretations[-1]["result"] = parsed.model_dump(exclude={"accepted_facts", "patient_context", "empathy"})
