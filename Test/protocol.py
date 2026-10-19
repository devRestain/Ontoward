"""Decode recorded JSON or current key/value model inputs for offline doubles."""
import json
import re


def decode_context(content):
    if content.lstrip().startswith(('{', '[')):
        return json.loads(content)
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
