import json

from nova_sdk import empty_record

from .collection import CATEGORY_FIELDS
from .limits import LIMITS
from .record import dd_ros_facts
from .submission import validate_wire_payload


def minimal_payload(case, interview, diagnosis, *, compact=False):
    """Assemble only preserved information, without models, graph queries or projections."""
    note = empty_record()
    note['A']['evidence'] = 'Working diagnosis: ' + diagnosis + '\nAssessment incomplete; only preserved information is recorded.'

    def append(field, text):
        section, key = field.split('.')
        if not isinstance(text, str) or not text.strip() or field == 'O.tests':
            return
        old = note[section][key]
        if text in old.split('\n'):
            return
        note[section][key] = old + ('\n' if old else '') + text
        if len(json.dumps(note, ensure_ascii=False).encode('utf-8')) > LIMITS.record_bytes:
            note[section][key] = old

    if case.assessment:
        for limitation in case.assessment.limitations:
            append('A.evidence', 'Incomplete assessment: ' + limitation)
        for entry in case.assessment.differential[1:1 + LIMITS.soap_differentials]:
            append('A.differential', 'r/o ' + entry.name)
    if case.presenting_text.strip():
        # Keep complete quoted lines; never cut a quantity, negation or UTF-8 name.
        for line in case.presenting_text.splitlines()[:1 if compact else None]:
            append('S.cc', 'Presenting report (initial opening): ' + line)
    if case.initial_vital_signs:
        value = case.initial_vital_signs
        append('O.exam', 'Initial vital signs (verbatim, not further interpreted): ' +
               (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))
    suppressed = {ident for fact in case.facts.values() if fact.status in {'present', 'absent'}
                  for ident in fact.resolves if ident in case.facts and case.facts[ident].status in {'unknown', 'uncertain'}}
    facts = list(case.facts.values())
    ros = dd_ros_facts(case, interview)
    for fact in facts[:10 if compact else None]:
        if fact.id in suppressed:
            continue
        content = fact.target or fact.value
        if fact.attribute:
            content += ' - ' + fact.attribute
        if fact.values:
            content += ': ' + '; '.join(fact.values)
        if fact.measurement:
            content += ' ' + json.dumps(fact.measurement.model_dump(exclude_none=True), ensure_ascii=False)
        if not content:
            continue
        context = f'{fact.status}; {fact.subject}' + (': ' + fact.subject_member if fact.subject_member else '')
        context += f'; {fact.time_context}; source={fact.source_ref}; turn={fact.turn}'
        if fact.observation_id:
            context += '; observation=' + fact.observation_id
        if fact.episode_id:
            context += '; episode=' + fact.episode_id
        field = ('O.exam' if (fact.acquisition == 'EXAM' or fact.acquisition == 'initial' and fact.source_ref == 'initial:vital_signs')
                 and fact.subject == 'patient' else 'S.fh' if fact.subject == 'family'
                 else 'S.ros' if fact.id in ros else CATEGORY_FIELDS.get(fact.category, 'S.hpi'))
        append(field, content + ' (' + context + ')')
    for answer in ([] if compact else interview.answers):
        raw = answer.response
        if (answer.scope == 'Education' or answer.outcome != 'unknown' or not raw
                or raw.get('error') or raw.get('status') != 'OK'):
            continue
        value = raw.get('result' if answer.key and answer.key[0] == 'EXAM' else 'content')
        if isinstance(value, str):
            append('O.exam' if answer.key and answer.key[0] == 'EXAM' else 'S.hpi',
                   f'Uninterpreted received reply ({answer.source_ref}; turn={answer.turn}): ' + value)
    for sentence in ([] if compact else case.plan):
        append('P.' + sentence.field, 'Planned: ' + sentence.text)
    payload = dict(note=note, diagnosis=diagnosis)
    validate_wire_payload(payload)
    return payload
