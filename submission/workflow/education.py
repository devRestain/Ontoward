import json
import re

from .rules.limits import LIMITS, PLAN_FIELDS
from .state.models import ClinicalValue, PlanSentence, RecordItem, SourceReference


def messages(prompt, payload):
    return [{"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]


def message_bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def references(raw, contexts):
    if not isinstance(raw, list):
        raise ValueError("references must be a list")
    accepted = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"document_id", "quote"}:
            raise ValueError("invalid source reference")
        document_id, quote = item["document_id"], item["quote"]
        if not isinstance(document_id, str) or not isinstance(quote, str) or not quote.strip():
            raise ValueError("empty source reference")
        for start, text in contexts.get(document_id, []):
            position = text.find(quote)
            if position >= 0:
                offset = start + len(text[:position].encode("utf-8"))
                accepted.append(SourceReference(document_id=document_id, quote=quote,
                    start_byte=offset, end_byte=offset + len(quote.encode("utf-8"))))
                break
        else:
            raise ValueError("reference is outside the supplied source context")
    return accepted


def note_context(notes):
    contexts = {}
    for note in notes:
        for ref in note["references"]:
            contexts.setdefault(ref["document_id"], []).append((ref["start_byte"], ref["quote"]))
    return contexts


def wire_notes(notes):
    return [{"text": note["text"], "references": [
        {key: ref[key] for key in ("document_id", "quote")} for ref in note["references"]]} for note in notes]


def parse_notes(raw, contexts):
    accepted, errors = [], []
    if not isinstance(raw, dict) or set(raw) != {"notes"} or not isinstance(raw["notes"], list):
        return accepted, ["expected notes array"]
    for index, note in enumerate(raw["notes"]):
        try:
            if not isinstance(note, dict) or set(note) != {"text", "references"}:
                raise ValueError("invalid note")
            text = note["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty note")
            refs = references(note["references"], contexts)
            if not refs:
                raise ValueError("source notes require references")
            accepted.append({"text": text.strip(), "references": [ref.model_dump() for ref in refs]})
        except (TypeError, ValueError) as error:
            errors.append(f"note {index}: {error}")
    return accepted, errors


def parse_plan(raw, contexts, progress):
    errors = []
    if not isinstance(raw, dict) or set(raw) != {"P"} or not isinstance(raw["P"], dict):
        return [], ["expected P object with five sentence arrays"]
    if set(raw["P"]) - set(PLAN_FIELDS):
        errors.append("unexpected P fields")
    accepted = []
    existing = {(sentence.field, sentence.text) for sentence in progress.sentences}
    for field in PLAN_FIELDS:
        rows = raw["P"].get(field, [])
        if not isinstance(rows, list):
            errors.append(f"{field}: expected sentence array")
            continue
        for index, row in enumerate(rows):
            try:
                if not isinstance(row, dict) or set(row) != {"text", "basis", "references", "priority"}:
                    raise ValueError("invalid sentence fields")
                text = row["text"]
                if (not isinstance(text, str) or not text.strip() or "\n" in text or "\r" in text
                        or not re.search(r"[A-Za-z]", text)):
                    raise ValueError("require a nonempty English sentence on one line")
                if re.match(r"^(otherwise|else|in that case)\b", text.strip(), re.I):
                    raise ValueError("include the treatment prerequisite in this sentence")
                refs = references(row["references"], contexts)
                if (row["basis"] in {"guideline", "mixed"} and not refs
                        or row["basis"] == "model_knowledge" and refs):
                    raise ValueError("basis differs from source references")
                if (field, text.strip()) in existing:
                    continue
                sentence = PlanSentence(id=f"plan:{field}:{sum(s.field == field for s in progress.sentences)}",
                    field=field, text=text.strip(), basis=row["basis"], references=refs, priority=row["priority"])
                progress.sentences.append(sentence)
                accepted.append(sentence.model_dump())
                existing.add((field, sentence.text))
            except (TypeError, ValueError) as error:
                errors.append(f"{field}[{index}]: {error}")
        if not any(sentence.field == field for sentence in progress.sentences):
            errors.append(f"{field}: empty")
    return accepted, errors


def _request(state, client, model, config, payload, parser):
    progress = state.interaction.education
    accepted = []
    for attempt in range(2):
        request = messages(config.education_prompt, payload)
        if message_bytes(request) > LIMITS.education_request_bytes:
            progress.errors.append("education_context_overflow")
            return accepted, False
        before = len(state.interaction.model_history)
        content = model.complete(state, client, role="education", messages=request)
        if content is None:
            exchange = state.interaction.model_history[-1] if len(state.interaction.model_history) > before else {}
            error = exchange.get("error")
            if not exchange or error not in {None, "PROVIDER_RESPONSE_INVALID"}:
                progress.errors.append(f"education_model_error:{error}" if exchange else "education_model_unavailable")
                return accepted, False
        try:
            raw = json.loads(content)
        except (TypeError, ValueError):
            raw = None
        values, errors = parser(raw)
        accepted.extend(value for value in values if value not in accepted)
        if not errors:
            return accepted, True
        if (attempt or progress.repairs or state.interaction.termination
                or not model.budget.model_allowance(state.session, "education")):
            progress.errors.extend(f"{payload['phase']}: {error}" for error in errors)
            return accepted, False
        progress.repairs += 1
        payload = {**payload, "phase": "repair", "repair_phase": payload["phase"],
                   "validation_errors": errors, "accepted": accepted}
    return accepted, False


def _fragments(document, base, prompt):
    text, cursor, offset = document["text"], 0, 0
    while cursor < len(text):
        low, high = 1, len(text) - cursor
        length = 0
        while low <= high:
            middle = (low + high) // 2
            part = {**document, "text": text[cursor:cursor + middle], "start_byte": offset,
                    "end_byte": offset + len(text[cursor:cursor + middle].encode("utf-8"))}
            if message_bytes(messages(prompt, {**base, "phase": "read", "documents": [part]})) <= LIMITS.education_request_bytes:
                length, low = middle, middle + 1
            else:
                high = middle - 1
        if not length:
            raise ValueError("education_context_overflow")
        boundary = text.rfind("\n\n", cursor, cursor + length)
        if cursor + length < len(text) and boundary >= cursor + length // 2:
            length = boundary + 2 - cursor
        chunk = text[cursor:cursor + length]
        end = offset + len(chunk.encode("utf-8"))
        yield {**document, "text": chunk, "start_byte": offset, "end_byte": end}
        cursor, offset = cursor + length, end


def generate_plan(state, client, knowledge, config, model):
    progress = state.interaction.education
    if progress.attempted:
        return
    progress.attempted = True
    fixed = state.case.fixed_diagnosis
    base = {"task": "education", "fixed_diagnosis": fixed.model_dump(),
            "patient_context": {key: entry.model_dump() for key, entry in state.case.patient_context.items()},
            "delivery_turn_budget": model.budget.action_capacity(state),
            "dialogue": state.interaction.dialogue(),
            "records": [{"field": field, **item.model_dump(exclude_none=True)} for field, item in state.case.current_entries()
                        if field.startswith(("S.", "O.")) and item.status == "done" and item.source_refs]}
    documents = []
    if fixed.kind == "disease":
        if knowledge.guidelines is None:
            progress.errors.append("guideline_index_unavailable")
        else:
            documents, failures = knowledge.guidelines.read(fixed.disease_id)
            progress.documents.extend(failures)
            progress.errors.extend(f"guideline_unavailable:{item['document_id']}" for item in failures)
    for document in documents:
        progress.documents.append({key: document[key] for key in ("document_id", "path", "sha256", "relation", "scope", "evidence_use")}
            | {"bytes": len(document["text"].encode("utf-8")), "reads": [], "status": "pending"})
    audits = {row["document_id"]: row for row in progress.documents}
    direct = {**base, "phase": "direct", "documents": documents}
    if message_bytes(messages(config.education_prompt, direct)) <= LIMITS.education_request_bytes:
        contexts = {doc["document_id"]: [(0, doc["text"])] for doc in documents}
        _, valid = _request(state, client, model, config, direct, lambda raw: parse_plan(raw, contexts, progress))
        for doc in documents:
            audit = audits[doc["document_id"]]
            audit["reads"] = [{"start_byte": 0, "end_byte": audit["bytes"], "accepted": valid}]
            audit["status"] = "read" if valid else "failed"
    else:
        complete = True
        try:
            for document in documents:
                audit = audits[document["document_id"]]
                for fragment in _fragments(document, base, config.education_prompt):
                    contexts = {document["document_id"]: [(fragment["start_byte"], fragment["text"])]}
                    notes, valid = _request(state, client, model, config,
                        {**base, "phase": "read", "documents": [fragment]}, lambda raw: parse_notes(raw, contexts))
                    progress.notes.extend(note for note in notes if note not in progress.notes)
                    audit["reads"].append({"start_byte": fragment["start_byte"], "end_byte": fragment["end_byte"], "accepted": valid})
                    if not valid:
                        complete = False
                    if (state.interaction.termination or not model.budget.model_allowance(state.session, "education")
                            or any(error.startswith(("education_model_error:", "education_model_unavailable")) for error in progress.errors)):
                        raise ValueError("education_reading_incomplete")
                audit["status"] = "read" if all(row["accepted"] for row in audit["reads"]) else "partial"
            notes = list(progress.notes)
            while message_bytes(messages(config.education_prompt, {**base, "phase": "synthesize", "notes": wire_notes(notes)})) > LIMITS.education_request_bytes:
                reduced, batch = [], []
                for note in notes:
                    proposed = {**base, "phase": "combine", "notes": wire_notes([*batch, note])}
                    if message_bytes(messages(config.education_prompt, proposed)) > LIMITS.education_request_bytes:
                        if not batch:
                            raise ValueError("education_notes_overflow")
                        contexts = note_context(batch)
                        values, valid = _request(state, client, model, config,
                            {**base, "phase": "combine", "notes": wire_notes(batch)}, lambda raw: parse_notes(raw, contexts))
                        if not valid or not values:
                            raise ValueError("education_combination_failed")
                        reduced.extend(values)
                        batch = []
                    batch.append(note)
                if batch:
                    contexts = note_context(batch)
                    values, valid = _request(state, client, model, config,
                        {**base, "phase": "combine", "notes": wire_notes(batch)}, lambda raw: parse_notes(raw, contexts))
                    if not valid or not values:
                        raise ValueError("education_combination_failed")
                    reduced.extend(values)
                if len(json.dumps(reduced)) >= len(json.dumps(notes)):
                    raise ValueError("education_combination_not_smaller")
                notes = reduced
            if not state.interaction.termination:
                contexts = note_context(notes)
                _request(state, client, model, config, {**base, "phase": "synthesize", "notes": wire_notes(notes)},
                         lambda raw: parse_plan(raw, contexts, progress))
            if not complete:
                progress.errors.append("education_source_processing_partial")
        except ValueError as error:
            progress.errors.append(str(error))
    for audit in progress.documents:
        if "bytes" not in audit:
            continue
        cursor, unread = 0, []
        for span in audit["reads"]:
            if span["accepted"]:
                if span["start_byte"] > cursor:
                    unread.append([cursor, span["start_byte"]])
                cursor = span["end_byte"]
        if cursor < audit["bytes"]:
            unread.append([cursor, audit["bytes"]])
        audit["unread_ranges"] = unread
        if unread:
            audit["status"] = "partial" if cursor else "not_read"
    for sentence in progress.sentences:
        state.case.put(f"P.{sentence.field}", RecordItem(id=sentence.id, scope="Education", status="done",
            value=ClinicalValue(kind="plan", text=sentence.text, status="present",
                                concept_ids=[fixed.disease_id] if fixed.disease_id else [])))
    populated = {sentence.field for sentence in progress.sentences}
    progress.status = ("complete" if populated == set(PLAN_FIELDS) and not progress.errors else
                       "partial" if populated else "failed")
    if progress.status != "complete":
        state.interaction.issues.append(f"education_generation_{progress.status}")
