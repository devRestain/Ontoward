"""Request-local text projection; retain originals for grounding and byte offsets."""
import re


QUOTES = frozenset('\"\'“”‘’«»')


def text_projection(text):
    # Paired numeric quotations are delimiters; unpaired numeric marks denote units.
    paired = set()
    for match in re.finditer(r'''(?<!\w)(["'])([^\n]*?)\1''', text):
        paired.update((match.start(), match.end() - 1))
    characters, positions = [], []
    for index, char in enumerate(text):
        if char in QUOTES:
            if char in "'’" and index and index + 1 < len(text) and text[index-1].isalpha() and text[index+1].isalpha():
                pass  # Keep word apostrophes, which do not need JSON escaping.
            elif char in "'’" and index and index + 1 < len(text) and text[index-1].isdigit() and text[index+1] == 's':
                pass  # Keep decades such as 60's distinct from a length unit.
            elif index not in paired and char in '\"\'' and index and text[index-1].isdigit():
                char = '″' if char == '"' else '′'
            else:
                continue
        characters.append(char)
        positions.append(index)
    return ''.join(characters), positions


def prompt_text(text):
    return text_projection(text)[0]


def prompt_payload(value, key=''):
    # Identity and typed units are contracts, not prose quotation delimiters.
    if key in {'id', '$key', 'unit', 'upper_unit', 'units', 'ref', 'source_ref'} or key.endswith(('_id', '_ids', '_refs')):
        return value
    if isinstance(value, str):
        return prompt_text(value)
    if isinstance(value, dict):
        if set(value) == {'table', 'groups'} and value['table'] in {'dict', 'list'}:
            return {'table': value['table'], 'groups': [dict(fields=list(group['fields']), rows=[
                [prompt_payload(cell, field) for field, cell in zip(group['fields'], row)]
                for row in group['rows']]) for group in value['groups']]}
        return {name: prompt_payload(item, name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [prompt_payload(item, key) for item in value]
    return value


def source_spans(text, quote):
    """Locate projected quotations in original character coordinates, including collisions."""
    projected, positions = text_projection(text)
    needle = prompt_text(quote)
    if not needle.strip():
        return []
    spans, start = [], 0
    while (start := projected.find(needle, start)) >= 0:
        spans.append((positions[start], positions[start + len(needle) - 1] + 1))
        start += 1
    return spans


def recover_quote(text, quote):
    spans = source_spans(text, quote)
    if len(spans) != 1:
        raise ValueError('quotation is absent or ambiguous after quote removal')
    start, end = spans[0]
    return text[start:end]
