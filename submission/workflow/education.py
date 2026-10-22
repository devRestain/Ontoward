import json
import logging
import re
from dataclasses import dataclass, field
from knowledge.guideline_passages import json_bytes, pack_passages, project_documents, source_contexts
from .rules.limits import LIMITS, PLAN_FIELDS, PLAN_SECTIONS
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

def parse_plan(raw, contexts, progress, *, fields=PLAN_FIELDS):
    errors = []
    # Normalize only the missing wrapper; keep all sentence and citation checks.
    if isinstance(raw, dict) and set(raw) == set(fields) and all(isinstance(v, list) for v in raw.values()):
        raw = {'P': raw}
    if not isinstance(raw, dict) or set(raw) != {'P'} or (not isinstance(raw['P'], dict)):
        return ([], ['expected P object with assigned sentence arrays'])
    if set(raw['P']) - set(fields):
        errors.append('unexpected P fields')
    accepted = []
    existing = {(sentence.field, sentence.text) for sentence in progress.sentences}
    for field in fields:
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

def _request(state, client, model, config, progress, payload, parser, *, reserve_calls=0):
    routes = ['plan.' + payload['section']]
    if payload['phase'] == 'repair':
        routes.append('plan.repair')
    request = messages(config.prompt(*routes), payload)
    if json_bytes(request) > LIMITS.education_max_messages_bytes:
        return [], ['education_model_error:LOCAL_EDUCATION_MESSAGE_LIMIT'], False
    response = model.complete(state, client, role='education', messages=request, reserve_calls=reserve_calls)
    if response.error:
        return [], [f'education_model_error:{response.error}'], response.error in {
            'PROVIDER_RESPONSE_INVALID', 'OUTPUT_TRUNCATED'}
    try:
        raw = json.loads(response.content)
    except (TypeError, ValueError):
        raw = None
    values, errors = parser(raw)
    return values, errors, bool(errors)

def generate_plan(state, client, knowledge, config, model):
    if state.interview.education_status != 'not_started':
        return {}
    state.interview.education_status = 'failed'
    progress = _EducationWork()
    fixed = state.case.primary()
    capacity = model.budget.action_capacity(state)
    section_budgets = dict.fromkeys(PLAN_SECTIONS, 0)
    for index in range(capacity):
        section_budgets[tuple(PLAN_SECTIONS)[index % len(PLAN_SECTIONS)]] += 1
    base = {'task': 'education', **fixed_case_payload(state.case)}
    documents = []
    if fixed.kind == 'disease':
        if knowledge.guidelines is None:
            logging.getLogger(__name__).warning('Guideline index unavailable for Education')
        else:
            documents, failures = knowledge.guidelines.read(knowledge.term_id(fixed.name, 'Disease'),
                                                          max_documents=LIMITS.education_documents)
            for item in failures:
                logging.getLogger(__name__).warning('Skip guideline %s: %s', item['document_id'], item['error'])
    selected = pack_passages(documents[:LIMITS.education_documents])
    direct = {**base, 'phase': 'direct', 'documents': project_documents(selected)}
    def section_payload(section, fields):
        return {**direct, 'section': section, 'fields': list(fields),
                'delivery_turn_budget': section_budgets[section],
                'accepted_plan': [dict(field=s.field, text=s.text) for s in progress.sentences]}
    def planning_size(section, fields, repair):
        payload = section_payload(section, fields)
        routes = ['plan.' + section]
        if repair:
            routes.append('plan.repair')
            payload.update(phase='repair', repair_phase='direct', accepted=[],
                           validation_errors=['expected P object with assigned sentence arrays'])
        return json_bytes(messages(config.prompt(*routes), payload))
    # Include the repair envelope and leave 2 KiB for accepted summaries/errors.
    # Fixed patient content still uses the existing hard guard when no excerpt fits.
    while selected and any(planning_size(section, fields, repair)
            > LIMITS.education_max_messages_bytes - 2048
            for section, fields in PLAN_SECTIONS.items() for repair in (False, True)):
        selected.pop()
        direct['documents'] = project_documents(selected)
    contexts = source_contexts(selected)
    results = {}
    # Complete all initial sections before spending optional repair calls.
    for index, (section, fields) in enumerate(PLAN_SECTIONS.items()):
        if state.session.termination or state.session.budget_sync_required:
            results[section] = ([], ['education_model_error:MODEL_UNAVAILABLE'], False)
            continue
        results[section] = _request(state, client, model, config, progress,
            section_payload(section, fields), lambda raw: parse_plan(raw, contexts, progress, fields=fields),
            reserve_calls=len(PLAN_SECTIONS) - index - 1)
        state.case.plan = list(progress.sentences)
    for section, fields in PLAN_SECTIONS.items():
        accepted, errors, repairable = results[section]
        if (errors and repairable and not state.session.termination and not state.session.budget_sync_required
                and model.budget.model_allowance(state.session, 'education', state=state)):
            initial_errors = errors
            progress.repairs += 1
            payload = {**section_payload(section, fields), 'phase': 'repair', 'repair_phase': 'direct',
                       'validation_errors': errors, 'accepted': accepted}
            if any(error.startswith('education_model_error:') for error in errors):
                payload['generation_error'] = errors[0].split(':', 1)[1]
                payload['validation_errors'] = []
            _, errors, _ = _request(state, client, model, config, progress, payload,
                lambda raw: parse_plan(raw, contexts, progress, fields=fields))
            if errors:
                errors = [f'{initial_errors[0]}; repair: {error}' for error in errors]
            state.case.plan = list(progress.sentences)
        progress.errors.extend(f'{section}: {error}' for error in errors)
    populated = {sentence.field for sentence in progress.sentences}
    state.interview.education_status = 'complete' if populated == set(PLAN_FIELDS) and (not progress.errors) else 'partial' if populated else 'failed'
    state.interview.education_reason = progress.errors[0] if progress.errors else None
    return progress.utterances
