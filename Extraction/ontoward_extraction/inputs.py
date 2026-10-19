import csv
import hashlib
import io
import json
import re
import tarfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from .models import canonical

CSV_FIELD_LIMIT = 16 * 1024 * 1024

BODHI_HEADERS = {
    'nodes_condition': {'snomed_id', 'concept_type', 'name'},
    'nodes_symptom': {'uuid', 'root_snomed_id', 'name'},
    'nodes_speciality': {'id', 'name'},
    'edges_present_in': {'symptom_uuid', 'condition_snomed_id'},
    'edges_has_prerequisite': {'condition_snomed_id_src', 'condition_snomed_id_dst'},
    'edges_is_influenced_by': {'condition_snomed_id_src', 'condition_snomed_id_dst'},
    'edges_related_to': {'src_type', 'src_id', 'dst_type', 'dst_id'},
    'edges_treated_by': {'condition_snomed_id', 'speciality_id'},
}


@contextmanager
def stream(entry):
    path, member = Path(entry['path']), entry.get('member')
    if not member:
        with path.open('rb') as source:
            yield source
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive, archive.open(member) as source:
            yield source
    else:
        with tarfile.open(path) as archive:
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f'Invalid archive member: {member}')
            with source:
                yield source


def members(path):
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            return [name for name in archive.namelist() if not name.endswith('/')]
    if path.name.endswith(('.tar.gz', '.tgz', '.tar')):
        with tarfile.open(path) as archive:
            return [item.name for item in archive if item.isfile()]
    return [None]


def discover(root, configured=None, boundary=lambda: None):
    root = Path(root).resolve()
    selected = []
    for path in sorted(root.rglob('*')):
        boundary()
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {'.txt','.csv','.json','.zip','.gz','.tgz','.tar'}:
            continue
        if configured and not any(path.is_relative_to((root/value).resolve()) or path == (root/value).resolve()
            for value in configured.values()):
            continue
        for member in members(path):
            name = member or path.as_posix()
            entry = {'path':str(path),'member':member}
            role = None
            if name.endswith('.txt') and 'Snapshot' in name:
                with stream(entry) as source:
                    header = source.readline().decode('utf-8-sig').strip().split('\t')
                if {'id','effectiveTime','active'} <= set(header):
                    role = 'rf2'
            elif name.endswith('.csv'):
                with stream(entry) as source:
                    header = next(csv.reader([source.readline().decode('utf-8-sig')]))
                matches = [key for key,required in BODHI_HEADERS.items() if required <= set(header)]
                stem = Path(name).stem
                role = 'bodhi:' + (stem if stem in matches else matches[0]) if matches else None
                if stem in {'edges_has_prerequisite','edges_is_influenced_by'} and stem in matches:
                    role = 'bodhi:' + stem
            elif name.endswith('.json'):
                with stream(entry) as source:
                    data = json.load(source)
                if isinstance(data,dict):
                    first = next(iter(data.values()),None)
                    if {'nodes','attribute_bindings','cpx_topics'} <= data.keys():
                        role = 'astra'
                    elif isinstance(first,dict) and {'question_en','data_type','possible-values'} <= first.keys():
                        role = 'ddx:evidences'
                    elif isinstance(first,dict) and {'condition_name','symptoms','antecedents'} <= first.keys():
                        role = 'ddx:conditions'
                    elif Path(name).name == 'release_package_information.json':
                        role = 'rf2:release'
            if role:
                with stream(entry) as source:
                    value = hashlib.sha256()
                    while chunk := source.read(1024*1024):
                        value.update(chunk)
                        boundary()
                selected.append({**entry,'role':role,'sha256':value.hexdigest(),
                    'relative_path':str(path.relative_to(root))})
    roles = {entry['role'] for entry in selected}
    required = {'rf2','astra','ddx:evidences','ddx:conditions',*('bodhi:'+name for name in BODHI_HEADERS)}
    if missing := required - roles:
        raise ValueError('missing_or_corrupt_inputs:' + ','.join(sorted(missing)))
    return selected


def rows(entry):
    with stream(entry) as source:
        if entry['role'] == 'rf2' or entry['role'].startswith('bodhi:'):
            csv.field_size_limit(CSV_FIELD_LIMIT)
            with io.TextIOWrapper(source,encoding='utf-8-sig',newline='') as text:
                # RF2 is literal TSV: quotes are clinical text, not CSV delimiters.
                reader=csv.DictReader(text,delimiter='\t' if entry['role']=='rf2' else ',',
                    quoting=csv.QUOTE_NONE if entry['role']=='rf2' else csv.QUOTE_MINIMAL,strict=True)
                try:
                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            raise ValueError(f'input_column_count_mismatch:{entry["relative_path"]}:line={reader.line_num}')
                        yield row
                except csv.Error as error:
                    raise ValueError(f'input_parse_error:{entry["relative_path"]}:line={reader.line_num}:{error}') from error
        else:
            data = json.load(source)
            if entry['role'] == 'astra':
                node_keys = {'id','node_type','en','ko','preferred_en','preferred_ko','aliases','contextual_expressions',
                    'existing_uris','topics','domain','notes','additional_alias_candidates'}
                for node in data['nodes']:
                    yield {'section':'nodes', **{key:value for key,value in node.items() if key in node_keys}}
                for binding in data['attribute_bindings']:
                    yield {'section':'attribute_bindings', **{key:value for key,value in binding.items() if key in {
                        'attribute_candidate_id','template_key','target_terms','allowed_value_candidate_ids','value_kind','unit','unit_options','measurement_window'}}}
                for topic in data['cpx_topics']:
                    yield {'section':'cpx_topics', **{key:value for key,value in topic.items() if key in {
                        'topic_id','topic_name','topic_kind','disease_names','disease_candidate_ids','note'}}}
                for item in data.get('ambiguous_patient_expressions',[]):
                    yield {'section':'expressions', **item}
            elif entry['role'].startswith('ddx:'):
                for key,value in data.items():
                    yield {'key':key, **value}
            else:
                yield data


def index(jobs, entries, chunk_size=1000):
    for entry in entries:
        key = canonical([entry['relative_path'],entry['member']])
        cursor = jobs.get('cursor:'+key,0)
        if jobs.get('indexed:'+key):
            continue
        print(canonical({'event':'index_file_started','path':entry['relative_path'],'cursor':cursor}),flush=True)
        batch = []
        for offset,row in enumerate(rows(entry),1):
            if offset <= cursor:
                continue
            batch.append((offset,row))
            if len(batch) >= chunk_size:
                commit_rows(jobs,entry,key,batch)
                batch=[]
                if offset % 100000 == 0:
                    print(canonical({'event':'index_checkpoint','path':entry['relative_path'],'rows':offset}),flush=True)
                jobs.boundary()
        if batch:
            commit_rows(jobs,entry,key,batch)
        jobs.set('indexed:'+key,True)
        print(canonical({'event':'index_file_complete','path':entry['relative_path'],'rows':jobs.get('cursor:'+key,0)}),flush=True)
        jobs.boundary()
    validate_dependencies(jobs,entries)


def commit_rows(jobs, entry, key, batch):
    dates=re.findall(r'20\d{6}',entry['relative_path']+'/'+(entry.get('member') or ''))
    release=dates[-1] if dates else None
    with jobs.db:
        for offset,row in batch:
            if entry['role'] == 'rf2':
                if release and row['effectiveTime']>release:
                    raise ValueError('future_rf2_component:'+row['id'])
                if release and row.get('moduleId'):
                    jobs.db.execute('INSERT OR IGNORE INTO rf2_modules VALUES(?,?)',(row['moduleId'],release))
                previous = jobs.db.execute('SELECT effective,payload FROM rf2 WHERE id=?',(row['id'],)).fetchone()
                value = canonical(row)
                if previous and previous['effective'] == row['effectiveTime'] and previous['payload'] != value:
                    raise ValueError('conflicting_rf2_component:'+row['id'])
                if not previous or previous['effective'] < row['effectiveTime']:
                    jobs.db.execute('INSERT OR REPLACE INTO rf2 VALUES(?,?,?,?)',
                        (row['id'],row['effectiveTime'],row['active'],value))
            else:
                jobs.db.execute('INSERT OR REPLACE INTO source_rows VALUES(?,?,?)',
                    (entry['role'],key+':'+str(offset),canonical(row)))
        jobs.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('cursor:'+key,canonical(batch[-1][0])))
        jobs.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('updated_at',canonical(time.time())))


def validate_dependencies(jobs, entries):
    for row in jobs.db.execute("SELECT payload FROM rf2 WHERE active='1'"):
        item=json.loads(row[0])
        if 'targetEffectiveTime' not in item: continue
        for module,release in ((item['moduleId'],item['sourceEffectiveTime']),
            (item['referencedComponentId'],item['targetEffectiveTime'])):
            if not jobs.db.execute('SELECT 1 FROM rf2_modules WHERE module=? AND release=?',(module,release)).fetchone():
                raise ValueError('unsatisfied_rf2_module_dependency:'+module+'@'+release)


def source_records(jobs, role):
    return [json.loads(row[0]) for row in jobs.db.execute('SELECT payload FROM source_rows WHERE source=? ORDER BY row_id',(role,))]
