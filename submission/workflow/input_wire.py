"""Reversible Ear references, owned by one Context extraction and its repair."""
from copy import deepcopy

from .wire import table_payload


class InputProjection:
    def __init__(self, payload):
        self.refs = {key: {} for key in ('id', 'observation_id', 'episode_id', 'source_ref')}
        for record in payload['records']:
            for key in self.refs:
                if record.get(key):
                    self.reference(key, record[key])
        for row in [payload.get('question'), *payload.get('pending_questions', []), *payload.get('asked_questions', [])]:
            if row:
                for key in ('observation_id', 'episode_id'):
                    if row.get(key):
                        self.reference(key, row[key])
        for row in payload.get('dialogue', []):
            self.reference('source_ref', row['id'])

    def reference(self, kind, value):
        prefix = {'id': 'f', 'observation_id': 'o', 'episode_id': 'ep', 'source_ref': 'u'}[kind]
        return self.refs[kind].setdefault(value, f'{prefix}_{len(self.refs[kind]) + 1}')

    def references(self, value, *, restore=False):
        maps = {**self.refs, 'correction_id': self.refs['id'], 'clarifies_id': self.refs['id']}
        if restore:
            maps = {key: {ref: original for original, ref in entries.items()} for key, entries in maps.items()}
        def visit(item):
            if isinstance(item, list):
                return [visit(row) for row in item]
            if not isinstance(item, dict):
                return item
            return {key: maps[key].get(val, val) if key in maps and isinstance(val, str) else visit(val)
                    for key, val in item.items()}
        return visit(value)

    def payload(self, payload):
        result = self.references(deepcopy(payload))
        result.pop('known_patient_context', None)
        scopes, scope_refs = {}, {}
        def scope(row):
            fields = ('subject', 'subject_member', 'time_context', 'observation_id', 'episode_id')
            values = {key: row.pop(key) for key in fields if key in row}
            key = tuple(values.items())
            if key not in scope_refs:
                ident = f's_{len(scope_refs) + 1}'
                scope_refs[key] = ident
                scopes[ident] = values
            row['scope'] = scope_refs[key]
        for row in result['records']:
            scope(row)
        for row in [*result.get('pending_questions', []), *result.get('asked_questions', [])]:
            scope(row)
        result['scopes'] = scopes
        for row in result.get('dialogue', []):
            row['id'] = self.refs['source_ref'].get(row['id'], row['id'])
        return table_payload(result, ('records', 'scopes', 'pending_questions', 'asked_questions'))

    def restore(self, raw):
        return self.references(raw, restore=True)
