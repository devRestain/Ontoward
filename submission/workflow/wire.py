"""Lossless request-local row tables. Never select or truncate clinical records."""
from copy import deepcopy
import json


def json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'))


def row_table(value):
    keyed = isinstance(value, dict)
    items = list(value.items()) if keyed else list(enumerate(value)) if isinstance(value, list) else []
    if not items or not all(isinstance(row, dict) for _, row in items):
        return value
    groups = {}
    for index, (key, row) in enumerate(items):
        fields = tuple(sorted(row))
        if fields not in groups:
            groups[fields] = dict(fields=['$index', *(['$key'] if keyed else []), *fields], rows=[])
        groups[fields]['rows'].append([index, *([key] if keyed else []), *[row[field] for field in fields]])
    table = dict(table='dict' if keyed else 'list', groups=list(groups.values()))
    return table if json_bytes(table) < json_bytes(value) else value


def table_payload(payload, fields):
    result = deepcopy(payload)
    for field in fields:
        if field in result:
            result[field] = row_table(result[field])
    return result
