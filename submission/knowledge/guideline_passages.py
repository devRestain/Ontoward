"""Bounded, literal Markdown passages from already mapped guideline documents."""
import json
import re


GUIDELINE_MAX_DOCUMENT_BYTES = 1_048_576
GUIDELINE_TOTAL_READ_BYTES = 16_777_216
EDUCATION_MAX_EXCERPT_BYTES = 2_048
EDUCATION_MAX_EVIDENCE_BYTES = 8_192

_TOPICS = (
    'management', 'treatment', 'therapy', 'medication', 'care', 'investigation',
    'test', 'diagnos', 'warning', 'red flag', 'urgent', 'emergency', 'referral',
    'disposition', 'follow-up', 'follow up', 'monitor', 'patient education',
    'self-care', 'self care', 'lifestyle', '치료', '관리', '검사', '진단', '경고',
    '응급', '의뢰', '추적', '재진', '교육', '생활',
)
_WARNINGS = ('warning', 'red flag', 'urgent', 'emergency', '경고', '응급')
_EXCLUDED = ('references', 'bibliography', 'acknowledg', 'copyright', 'license',
             'licence', '참고문헌', '참고 문헌', '저작권', '라이선스')
_HEADING = re.compile(r'^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$')
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_UNSUPPORTED = re.compile(
    r'\||\[\^|^ {0,3}(?:`{3,}|~{3,})|'
    r'<(?:/?[a-z][\w:-]*(?:[\s/>])|!--|!doctype|\?)|'
    r'\[[^\]\n]+\]\s*(?:\[[^\]\n]*\]|\(\s*#)|^ {0,3}\[[^\]\n]+\]:|'
    r'\b(?:table|figure|appendix|section)\s+(?:\d|[a-z]\b)|'
    r'\b(?:see|refer to)\s+(?:(?:the|also)\s+)*(?:table|figure|appendix|section|above|below|elsewhere|conditions)\b|'
    r'\b(?:above|below|following|preceding)\s+(?:conditions|criteria|recommendations|section)\b|'
    r'\bas (?:described|specified|noted|detailed) (?:above|below)\b|'
    r'(?:표|그림)\s*\d|부록|(?:위|아래|상기|전술한|후술한)\s*(?:조건|기준|권고|참조|절|항목)',
    re.I | re.M,
)


def json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'))


def direct_source(source):
    return source['relation'] == 'exact' and source['evidence_use'] == 'care_navigation'


def excerpt_value(passage):
    return {'heading_path': passage['heading_path'],
            'spans': [{'text': text} for _, text in passage['spans']]}


def passages(text):
    """Keep complete ATX leaves and every nonempty ancestor introduction verbatim."""
    raw = text.encode('utf-8')
    root = dict(level=0, title='', start=0, body=0, intro_end=None, end=len(raw), parent=None)
    stack, sections = [root], []
    offset, fence = 0, None
    for line in text.splitlines(keepends=True):
        start, offset = offset, offset + len(line.encode('utf-8'))
        syntax = line.rstrip('\r\n')
        if start == 0:
            syntax = syntax.removeprefix('\ufeff')
        marker = _FENCE.match(syntax)
        if fence:
            if (marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1]
                    and not marker[2].strip()):
                fence = None
            continue
        if marker:
            fence = (marker[1][0], len(marker[1]))
            continue
        heading = _HEADING.match(syntax)
        if not heading:
            continue
        level = len(heading[1])
        while stack[-1]['level'] >= level:
            stack.pop()['end'] = start
        parent = stack[-1]
        if parent['intro_end'] is None:
            parent['intro_end'] = start
        title = re.sub(r'[ \t]+#+[ \t]*$', '', heading[2] or '').strip(' \t')
        section = dict(level=level, title=title, start=start, body=offset,
                       intro_end=None, end=len(raw), parent=parent)
        sections.append(section)
        stack.append(section)
    result = []
    for section in sections:
        if section['intro_end'] is not None or any(word in section['title'].casefold() for word in _EXCLUDED):
            continue
        ancestors, parent = [], section['parent']
        while parent is not None:
            ancestors.append(parent)
            parent = parent['parent']
        ancestors.reverse()
        path = [node['title'] for node in [*ancestors, section] if node['level']]
        title_path = ' / '.join(path).casefold()
        if not any(word in title_path for word in _TOPICS):
            continue
        if not raw[section['body']:section['end']].decode('utf-8').strip():
            continue
        spans = []
        for node in ancestors:
            end = node['intro_end']
            intro = raw[node['body']:end].decode('utf-8')
            if intro.strip('\ufeff \t\r\n'):
                spans.append((node['body'], intro))
        spans.append((section['start'], raw[section['start']:section['end']].decode('utf-8')))
        passage = {'heading_path': path, 'spans': spans}
        if (not any(_UNSUPPORTED.search(value) for _, value in spans)
                and json_bytes(excerpt_value(passage)) <= EDUCATION_MAX_EXCERPT_BYTES):
            result.append(passage)
    # Stable partition: warning leaves first, then original order.
    return sorted(result, key=lambda p: not any(word in ' / '.join(p['heading_path']).casefold() for word in _WARNINGS))


def project_documents(selected):
    projected = {}
    for source, passage in selected:
        ident = source['document_id']
        if ident not in projected:
            row = {key: source[key] for key in ('document_id', 'relation', 'evidence_use')}
            if source.get('scope') and source['scope'] != 'Fresh disease label or alias match in the supplied guideline catalog':
                row['scope'] = source['scope']
            projected[ident] = {**row, 'excerpts': []}
        projected[ident]['excerpts'].append(excerpt_value(passage))
    return list(projected.values())


def pack_passages(documents):
    selected, seen = [], set()
    for direct in (True, False):
        pending = [(doc, iter(passages(doc['text']))) for doc in documents if direct_source(doc) == direct]
        while pending:
            following = []
            for source, choices in pending:
                passage = next(choices, None)
                if passage is None:
                    continue
                following.append((source, choices))
                key = (source['path'], tuple((start, start + len(text.encode('utf-8')))
                                            for start, text in passage['spans']))
                if key in seen:
                    continue
                seen.add(key)
                candidate = [*selected, (source, passage)]
                if json_bytes(project_documents(candidate)) <= EDUCATION_MAX_EVIDENCE_BYTES:
                    selected = candidate
            pending = following
    return selected


def source_contexts(selected):
    contexts = {}
    for source, passage in selected:
        spans = contexts.setdefault(source['document_id'], [])
        for span in passage['spans']:
            if span not in spans:
                spans.append(span)
    return contexts
