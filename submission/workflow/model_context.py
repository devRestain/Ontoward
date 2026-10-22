import json


def messages(prompt, payload):
    return [{'role': 'system', 'content': prompt}, {'role': 'user', 'content':
        json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)}]


def message_metrics(role, messages):
    """Measure final input bytes, never estimate tokens or retain message contents."""
    def size(value):
        return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'))
    result = dict(role=role, task=None, phase=None, stage=None,
        system_content_utf8_bytes=0, user_content_utf8_bytes=0, messages_json_bytes=size(messages),
        blocks={}, counts={})
    blocks = {'facts', 'scopes', 'records', 'dialogue', 'statements', 'candidates', 'relations', 'patterns',
        'conditions', 'evidence', 'questions', 'documents', 'repair', 'validation_error', 'validation_errors',
        'known_context_records', 'input_segments', 'patient', 'fixed_diagnosis', 'invalid_groups', 'generation_error'}
    counts = result['counts']
    def count(key, amount):
        counts[key] = counts.get(key, 0) + amount
    def visit(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                location = f'{path}.{key}'
                if key in blocks:
                    result['blocks'][location] = dict(json_bytes=size(item),
                        count=len(item) if isinstance(item, (dict, list)) else None)
                    if isinstance(item, (dict, list)):
                        count(key, len(item))
                if key == 'full_pattern' and isinstance(item, list):
                    count('features', len(item))
                elif key == 'patterns' and isinstance(item, dict):
                    count('features', sum(len(pattern) for pattern in item.values() if isinstance(pattern, list)))
                elif key == 'expected_by_disease' and isinstance(item, dict):
                    amount = sum(len(entries) for entries in item.values() if isinstance(entries, list))
                    count('expectations', amount)
                    count('disease_expectations', amount)
                elif key == 'expected_groups' and isinstance(item, list):
                    groups = [group for group in item if isinstance(group, dict)
                              and isinstance(group.get('entries'), list) and isinstance(group.get('diseases'), list)]
                    count('expectations', sum(len(group['entries']) for group in groups))
                    count('disease_expectations', sum(len(group['entries']) * len(group['diseases']) for group in groups))
                elif key == 'conditions' and isinstance(item, dict):
                    count('applicability_requirements', sum(len(rows) for rows in item.values() if isinstance(rows, list)))
                visit(item, location)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f'{path}[{index}]')
    for index, message in enumerate(messages):
        content = message.get('content')
        if not isinstance(content, str):
            continue
        if message.get('role') in {'system', 'user'}:
            result[message['role'] + '_content_utf8_bytes'] += len(content.encode('utf-8'))
        if message.get('role') == 'user':
            try:
                payload = json.loads(content)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                phase = ('response_repair' if payload.get('generation_error') else 'repair'
                    if payload.get('validation_error') or payload.get('validation_errors') or payload.get('repair') else 'initial')
                result.update(task=payload.get('task'), stage=payload.get('stage'),
                    phase=payload.get('phase') or phase)
                visit(payload, f'user[{index}]')
    return result


def fact_record(fact, ident=None):
    row = {'id': ident or fact.id, 'status': fact.status}
    if fact.graph_binding:
        row.update(kind=fact.kind, target=fact.target)
        if fact.attribute:
            row['attribute'] = fact.attribute
        if fact.values:
            row['values'] = fact.values
    if fact.value:
        row['value'] = fact.value
    if fact.measurement:
        row['measurement'] = {key: value for key, value in fact.measurement.model_dump(exclude_defaults=True).items()
                              if value is not None}
    for key in ('category', 'context_key', 'subject_member', 'observation_id', 'episode_id', 'acquisition'):
        value = getattr(fact, key)
        if value is not None:
            row[key] = value
    row.update(subject=fact.subject, reported_by=fact.reported_by, time_context=fact.time_context)
    if fact.polarity_scope == 'qualified':
        row['polarity_scope'] = 'qualified'
    return row
