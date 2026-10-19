import csv
import hashlib
import io
import re
from pathlib import Path
from .models import identifier


def navigation(assets, nodes, boundary=lambda: None):
    root=Path(assets)/'guidelines'
    catalog=root/'catalog.csv'
    if not catalog.is_file(): return {}
    documents=list(csv.DictReader(io.StringIO(catalog.read_text(encoding='utf-8-sig'))))
    result,hashes={},{}
    for node in nodes:
        if node['kind']!='Disease': continue
        boundary();names={node['name'],node['korean'],*node['aliases']}
        pattern=re.compile('|'.join(r'(?<!\w)'+re.escape(name.casefold())+r'(?!\w)' for name in names if name.strip()))
        selections=[]
        seen=set()
        for row in documents:
            title=row.get('제목',row.get('title',''))
            relative=row.get('파일명',row.get('path',''))
            if not relative or relative in seen or not pattern.search(title.casefold()): continue
            path=(root/relative).resolve()
            if not path.is_relative_to(root.resolve()) or path.suffix!='.md' or not path.is_file():
                raise ValueError('invalid_selected_guideline:'+relative)
            if relative not in hashes:
                boundary();hashes[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
            seen.add(relative)
            exact=title.casefold() in {name.casefold() for name in names}
            selections.append(dict(document_id=identifier('Document',relative),path=relative,sha256=hashes[relative],
                relation='exact' if exact else 'related',evidence_use='care_navigation' if exact else 'background_only',
                scope='Fresh disease label or alias match in the supplied guideline catalog'))
        result[node['id']]=selections
    return result
