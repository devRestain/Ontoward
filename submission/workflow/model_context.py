import json


def messages(prompt, payload):
    rows = []
    def emit(path, value):
        if isinstance(value, dict) and value:
            for key, item in value.items():
                emit(f'{path}.{key}' if path else key, item)
        elif isinstance(value, (tuple, list)) and value and any(isinstance(item, dict) for item in value):
            for index, item in enumerate(value):
                emit(f'{path}[{index}]', item)
        else:
            rows.append(f'{path} = {json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)}')
    emit('', payload)
    return [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': '\n'.join(rows)}]


def compact_row(row):
    return '; '.join(f'{key}={json.dumps(value, ensure_ascii=False, separators=(",", ":"))}' for key, value in row.items())


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
