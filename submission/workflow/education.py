import json
import re
from dataclasses import dataclass, field
from .rules.limits import LIMITS, PLAN_FIELDS
from .state.models import PlanSentence, SourceReference
from .state.evidence import patient_payload

@dataclass
class _EducationWork:
    repairs: int = 0
    sentences: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

def messages(prompt, payload):
    return [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}]

def message_bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))

def references(raw, contexts):
    if not isinstance(raw, list):
        raise ValueError('references must be a list')
    accepted = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {'document_id', 'quote'}:
            raise ValueError('invalid source reference')
        document_id, quote = (item['document_id'], item['quote'])
        if not isinstance(document_id, str) or not isinstance(quote, str) or (not quote.strip()):
            raise ValueError('empty source reference')
        for start, text in contexts.get(document_id, []):
            position = text.find(quote)
            if position >= 0:
                offset = start + len(text[:position].encode('utf-8'))
                accepted.append(dict(document_id=document_id, quote=quote, start_byte=offset, end_byte=offset + len(quote.encode('utf-8'))))
                break
        else:
            raise ValueError('reference is outside the supplied source context')
    return accepted

def note_context(notes):
    contexts = {}
    for note in notes:
        for ref in note['references']:
            contexts.setdefault(ref['document_id'], []).append((ref['start_byte'], ref['quote']))
    return contexts

def wire_notes(notes):
    return [{'text': note['text'], 'references': [{key: ref[key] for key in ('document_id', 'quote')} for ref in note['references']]} for note in notes]

def parse_notes(raw, contexts):
    accepted, errors = ([], [])
    if not isinstance(raw, dict) or set(raw) != {'notes'} or (not isinstance(raw['notes'], list)):
        return (accepted, ['expected notes array'])
    for index, note in enumerate(raw['notes']):
        try:
            if not isinstance(note, dict) or set(note) != {'text', 'references'}:
                raise ValueError('invalid note')
            text = note['text']
            if not isinstance(text, str) or not text.strip():
                raise ValueError('empty note')
            refs = references(note['references'], contexts)
            if not refs:
                raise ValueError('source notes require references')
            accepted.append({'text': text.strip(), 'references': refs})
        except (TypeError, ValueError) as error:
            errors.append(f'note {index}: {error}')
    return (accepted, errors)

def parse_plan(raw, contexts, progress):
    errors = []
    if not isinstance(raw, dict) or set(raw) != {'P'} or (not isinstance(raw['P'], dict)):
        return ([], ['expected P object with five sentence arrays'])
    if set(raw['P']) - set(PLAN_FIELDS):
        errors.append('unexpected P fields')
    accepted = []
    existing = {(sentence.field, sentence.text) for sentence in progress.sentences}
    for field in PLAN_FIELDS:
        rows = raw['P'].get(field, [])
        if not isinstance(rows, list):
            errors.append(f'{field}: expected sentence array')
            continue
        for index, row in enumerate(rows):
            try:
                if not isinstance(row, dict) or set(row) != {'text', 'basis', 'references', 'priority'}:
                    raise ValueError('invalid sentence fields')
                text = row['text']
                if not isinstance(text, str) or not text.strip() or '\n' in text or ('\r' in text) or (not re.search('[A-Za-z]', text)):
                    raise ValueError('require a nonempty English sentence on one line')
                if re.match('^(otherwise|else|in that case)\\b', text.strip(), re.I):
                    raise ValueError('include the treatment prerequisite in this sentence')
                refs = references(row['references'], contexts)
                if row['basis'] in {'guideline', 'mixed'} and (not refs) or (row['basis'] == 'model_knowledge' and refs):
                    raise ValueError('basis differs from source references')
                if (field, text.strip()) in existing:
                    continue
                sentence = PlanSentence(id=f'plan:{field}:{sum((s.field == field for s in progress.sentences))}', field=field, text=text.strip(), basis=row['basis'], references=tuple((SourceReference(**{k: v for k, v in ref.items() if k != 'quote'}) for ref in refs)), priority=row['priority'])
                progress.sentences.append(sentence)
                accepted.append(sentence.model_dump())
                existing.add((field, sentence.text))
            except (TypeError, ValueError) as error:
                errors.append(f'{field}[{index}]: {error}')
        if not any((sentence.field == field for sentence in progress.sentences)):
            errors.append(f'{field}: empty')
    return (accepted, errors)

def _request(state, client, model, config, progress, payload, parser):
    accepted = []
    for attempt in range(2):
        request = messages(config.education_prompt, payload)
        if message_bytes(request) > LIMITS.education_request_bytes:
            progress.errors.append('education_context_overflow')
            return (accepted, False)
        response = model.complete(state, client, role='education', messages=request)
        content = response.content
        if response.error:
            values, errors = ([], [f'education_model_error:{response.error}'])
            if response.error != 'PROVIDER_RESPONSE_INVALID':
                progress.errors.extend(errors)
                return (accepted, False)
        else:
            try:
                raw = json.loads(content)
            except (TypeError, ValueError):
                raw = None
            values, errors = parser(raw)
        accepted.extend((value for value in values if value not in accepted))
        if not errors:
            return (accepted, True)
        if attempt or progress.repairs or state.session.termination or (not model.budget.model_allowance(state.session, 'education')):
            progress.errors.extend((f"{payload['phase']}: {error}" for error in errors))
            return (accepted, False)
        progress.repairs += 1
        payload = {**payload, 'phase': 'repair', 'repair_phase': payload['phase'], 'validation_errors': [] if response.error else errors, 'accepted': accepted}
        if response.error:
            payload['generation_error'] = response.error
    return (accepted, False)

def _fragments(document, base, prompt):
    text, cursor, offset = (document['text'], 0, 0)
    while cursor < len(text):
        low, high = (1, len(text) - cursor)
        length = 0
        while low <= high:
            middle = (low + high) // 2
            part = {**document, 'text': text[cursor:cursor + middle], 'start_byte': offset, 'end_byte': offset + len(text[cursor:cursor + middle].encode('utf-8'))}
            if message_bytes(messages(prompt, {**base, 'phase': 'read', 'documents': [part]})) <= LIMITS.education_request_bytes:
                length, low = (middle, middle + 1)
            else:
                high = middle - 1
        if not length:
            raise ValueError('education_context_overflow')
        boundary = text.rfind('\n\n', cursor, cursor + length)
        if cursor + length < len(text) and boundary >= cursor + length // 2:
            length = boundary + 2 - cursor
        chunk = text[cursor:cursor + length]
        end = offset + len(chunk.encode('utf-8'))
        yield {**document, 'text': chunk, 'start_byte': offset, 'end_byte': end}
        cursor, offset = (cursor + length, end)

def generate_plan(state, client, knowledge, config, model):
    if state.interview.education_status != 'not_started':
        return
    state.interview.education_status = 'failed'
    progress = _EducationWork()
    fixed = state.case.primary()
    base = {'task': 'education', 'fixed_diagnosis': state.case.fixed_diagnosis(), 'patient': patient_payload(state.case), 'delivery_turn_budget': model.budget.action_capacity(state)}
    documents = []
    if fixed.kind == 'disease':
        if knowledge.guidelines is None:
            progress.errors.append('guideline_index_unavailable')
        else:
            documents, failures = knowledge.guidelines.read(knowledge.term_id(fixed.name, 'Disease'))
            progress.errors.extend((f"guideline_unavailable:{item['document_id']}" for item in failures))
    direct = {**base, 'phase': 'direct', 'documents': documents}
    if message_bytes(messages(config.education_prompt, direct)) <= LIMITS.education_request_bytes:
        contexts = {doc['document_id']: [(0, doc['text'])] for doc in documents}
        _, valid = _request(state, client, model, config, progress, direct, lambda raw: parse_plan(raw, contexts, progress))
    else:
        complete = True
        try:
            for document in documents:
                for fragment in _fragments(document, base, config.education_prompt):
                    contexts = {document['document_id']: [(fragment['start_byte'], fragment['text'])]}
                    notes, valid = _request(state, client, model, config, progress, {**base, 'phase': 'read', 'documents': [fragment]}, lambda raw: parse_notes(raw, contexts))
                    progress.notes.extend((note for note in notes if note not in progress.notes))
                    if not valid:
                        complete = False
                    if state.session.termination or not model.budget.model_allowance(state.session, 'education') or any((error.startswith(('education_model_error:', 'education_model_unavailable')) for error in progress.errors)):
                        raise ValueError('education_reading_incomplete')
            notes = list(progress.notes)
            while message_bytes(messages(config.education_prompt, {**base, 'phase': 'synthesize', 'notes': wire_notes(notes)})) > LIMITS.education_request_bytes:
                reduced, batch = ([], [])
                for note in notes:
                    proposed = {**base, 'phase': 'combine', 'notes': wire_notes([*batch, note])}
                    if message_bytes(messages(config.education_prompt, proposed)) > LIMITS.education_request_bytes:
                        if not batch:
                            raise ValueError('education_notes_overflow')
                        contexts = note_context(batch)
                        values, valid = _request(state, client, model, config, progress, {**base, 'phase': 'combine', 'notes': wire_notes(batch)}, lambda raw: parse_notes(raw, contexts))
                        if not valid or not values:
                            raise ValueError('education_combination_failed')
                        reduced.extend(values)
                        batch = []
                    batch.append(note)
                if batch:
                    contexts = note_context(batch)
                    values, valid = _request(state, client, model, config, progress, {**base, 'phase': 'combine', 'notes': wire_notes(batch)}, lambda raw: parse_notes(raw, contexts))
                    if not valid or not values:
                        raise ValueError('education_combination_failed')
                    reduced.extend(values)
                if len(json.dumps(reduced)) >= len(json.dumps(notes)):
                    raise ValueError('education_combination_not_smaller')
                notes = reduced
            if not state.session.termination:
                contexts = note_context(notes)
                _request(state, client, model, config, progress, {**base, 'phase': 'synthesize', 'notes': wire_notes(notes)}, lambda raw: parse_plan(raw, contexts, progress))
            if not complete:
                progress.errors.append('education_source_processing_partial')
        except ValueError as error:
            progress.errors.append(str(error))
    state.case.plan = progress.sentences
    populated = {sentence.field for sentence in progress.sentences}
    state.interview.education_status = 'complete' if populated == set(PLAN_FIELDS) and (not progress.errors) else 'partial' if populated else 'failed'
    state.interview.education_reason = progress.errors[0] if progress.errors else None
