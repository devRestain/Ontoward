import json
import logging
import re
from dataclasses import dataclass, field
from knowledge.guideline_passages import json_bytes, pack_passages, project_documents, source_contexts
from .rules.limits import LIMITS, PLAN_FIELDS
from .state.models import PlanSentence, SourceReference
from .state.evidence import fixed_case_payload
from .model_context import messages
from .output_types import PlanRow

@dataclass
class _EducationWork:
    repairs: int = 0
    sentences: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    utterances: dict = field(default_factory=dict)

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
        locations = set()
        for start, text in contexts.get(document_id, []):
            position = text.find(quote)
            while position >= 0:
                offset = start + len(text[:position].encode('utf-8'))
                locations.add((offset, offset + len(quote.encode('utf-8'))))
                position = text.find(quote, position + 1)
        if not locations:
            raise ValueError('reference is outside the supplied source context')
        if len(locations) != 1:
            raise ValueError('reference is ambiguous in the supplied source context')
        start, end = locations.pop()
        accepted.append(dict(document_id=document_id, quote=quote, start_byte=start, end_byte=end))
    return accepted

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
                if not isinstance(row, dict):
                    raise ValueError('invalid sentence fields')
                utterances = row.get('utterances')
                row = PlanRow.model_validate({k: v for k, v in row.items() if k != 'utterances'}).model_dump()
                if not isinstance(row, dict) or set(row) != {'text', 'basis', 'references', 'priority'}:
                    raise ValueError('invalid sentence fields')
                text = row['text']
                if not isinstance(text, str) or not text.strip() or '\n' in text or ('\r' in text) or (not re.search('[A-Za-z]', text)) or re.search('[가-힣]', text):
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
                progress.utterances[sentence.id] = utterances
                accepted.append(dict(id=sentence.id, field=field, text=sentence.text,
                    basis=sentence.basis, priority=sentence.priority, references=row['references']))
                existing.add((field, sentence.text))
            except (TypeError, ValueError) as error:
                errors.append(f'{field}[{index}]: {error}')
        if not any((sentence.field == field for sentence in progress.sentences)):
            errors.append(f'{field}: empty')
    return (accepted, errors)

def _request(state, client, model, config, progress, payload, parser):
    accepted = []
    for attempt in range(2):
        request = messages(config.prompt('plan.repair' if attempt else 'plan.generate'), payload)
        if json_bytes(request) > LIMITS.education_max_messages_bytes:
            progress.errors.append('education_model_error:LOCAL_EDUCATION_MESSAGE_LIMIT')
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

def generate_plan(state, client, knowledge, config, model):
    if state.interview.education_status != 'not_started':
        return {}
    state.interview.education_status = 'failed'
    progress = _EducationWork()
    fixed = state.case.primary()
    base = {'task': 'education', **fixed_case_payload(state.case), 'delivery_turn_budget': model.budget.action_capacity(state)}
    documents = []
    if fixed.kind == 'disease':
        if knowledge.guidelines is None:
            logging.getLogger(__name__).warning('Guideline index unavailable for Education')
        else:
            documents, failures = knowledge.guidelines.read(knowledge.term_id(fixed.name, 'Disease'))
            for item in failures:
                logging.getLogger(__name__).warning('Skip guideline %s: %s', item['document_id'], item['error'])
    selected = pack_passages(documents)
    direct = {**base, 'phase': 'direct', 'documents': project_documents(selected)}
    while selected and json_bytes(messages(config.prompt('plan.generate'), direct)) > LIMITS.education_max_messages_bytes:
        selected.pop()
        direct['documents'] = project_documents(selected)
    contexts = source_contexts(selected)
    _request(state, client, model, config, progress, direct, lambda raw: parse_plan(raw, contexts, progress))
    state.case.plan = progress.sentences
    populated = {sentence.field for sentence in progress.sentences}
    state.interview.education_status = 'complete' if populated == set(PLAN_FIELDS) and (not progress.errors) else 'partial' if populated else 'failed'
    state.interview.education_reason = progress.errors[0] if progress.errors else None
    return progress.utterances
