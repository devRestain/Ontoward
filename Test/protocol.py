"""Decode recorded JSON or current key/value model inputs for offline doubles."""
import json
import re


def expand_tables(value):
    """Test-only expansion of current lossless input tables, preserving old traces."""
    if isinstance(value, list):
        return [expand_tables(row) for row in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {'table', 'groups'} and value['table'] in {'dict', 'list'}:
        rows = []
        for group in value['groups']:
            for cells in group['rows']:
                if len(cells) != len(group['fields']):
                    raise ValueError('Invalid row table')
                row = dict(zip(group['fields'], map(expand_tables, cells)))
                index, key = row.pop('$index'), row.pop('$key', None)
                rows.append((index, key, row))
        rows.sort(key=lambda item: item[0])
        return {key: row for _, key, row in rows} if value['table'] == 'dict' else [row for _, _, row in rows]
    return {key: expand_tables(item) for key, item in value.items()}


def decode_context(content):
    if content.lstrip().startswith(('{', '[')):
        result = expand_tables(json.loads(content))
        if isinstance(result, dict) and result.get('task') == 'input_context' and 'scopes' in result:
            for record in [*result['records'], *result.get('pending_questions', []), *result.get('asked_questions', [])]:
                if 'scope' in record:
                    record.update(result['scopes'][record.pop('scope')])
        return result
    result = {}
    for line in content.splitlines():
        key, separator, value = line.partition(' = ')
        if not separator:
            raise ValueError('Invalid model context line')
        parts = [int(index) if index else name for name, index in re.findall(r'([^.[\]]+)|\[([0-9]+)\]', key)]
        current = result
        for position, part in enumerate(parts):
            last = position == len(parts) - 1
            if isinstance(current, list):
                while len(current) <= part:
                    current.append(None)
            if last:
                current[part] = json.loads(value)
            else:
                child = [] if isinstance(parts[position + 1], int) else {}
                if isinstance(current, list):
                    if current[part] is None:
                        current[part] = child
                elif part not in current:
                    current[part] = child
                current = current[part]
    return result
