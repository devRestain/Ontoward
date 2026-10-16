from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from rdflib import Graph, RDF, RDFS, URIRef

from .database import file_hash, json_text
from .korean import BATCH_SIZE, MODEL, PROMPTS, response_schema, validate
from .source_catalog import clinical_question_status
from .v5 import OW, ROOT, digest, workspace_path, write


def graph_inputs(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    graph, files = Graph(), {str(manifest_path.relative_to(ROOT)):file_hash(manifest_path)}
    for asset in (manifest['schema'], manifest['vocabulary'], *manifest['bundles']):
        path = workspace_path(manifest_path.parent.parent / asset['path'])
        if file_hash(path) != asset['sha256']:
            raise ValueError('Runtime graph asset differs from its manifest')
        files[str(path.relative_to(ROOT))] = asset['sha256']
        graph.parse(path, format='turtle')
    return manifest, graph, files


def freeze(graph_directory, output, *, provider, exclude_accepted=None, continue_on_failure=False, max_calls=None):
    graph_directory, output = workspace_path(graph_directory), workspace_path(output)
    if output.exists() or not output.is_relative_to(ROOT / 'data/preparation/v5'):
        raise ValueError('Freeze patient wording into a fresh data-owned path')
    manifest, graph, files = graph_inputs(ROOT / 'submission/knowledge/manifest.json')
    receipt_path = graph_directory / 'review-approved.json'
    receipt = json.loads(receipt_path.read_text())
    if (receipt['build_id'] != manifest['build_id'] or digest(receipt) != manifest['review_receipt_sha256']
            or not receipt['approved'] or manifest['preparation_status'] != 'graph_admitted_text_pending'):
        raise ValueError('Patient wording requires the exact admitted D20 graph and approval')
    registry_path = graph_directory / 'preview/registry.json'
    registry = json.loads(registry_path.read_text())['entries']
    if isinstance(registry, list):
        registry = {entry['uri']:entry for entry in registry}
    files[str(receipt_path.relative_to(ROOT))] = file_hash(receipt_path)
    files[str(registry_path.relative_to(ROOT))] = file_hash(registry_path)
    jobs, excluded = [], []

    def label(node, language='en'):
        return next((str(term) for term in graph.objects(node, RDFS.label) if term.language == language), None)

    def add(target, purpose, *, attribute=None, method=None, context_type=None):
        key = str(method or target) + ('|' + str(attribute) if attribute else '')
        entry = registry[str(target)]
        proof = [digest(entry['source_refs'])]
        if attribute:
            proof.append(digest(registry[str(attribute)]['source_refs']))
        if method:
            proof.append(digest(registry[str(method)]['source_refs']))
        job = {'kind':'question', 'key':key, 'target':str(target),
               'action':'EXAM' if method else 'SAY', 'purpose':purpose,
               'english_label':label(target), 'source_korean_label':label(target, 'ko'),
               'attribute':str(attribute) if attribute else None,
               'attribute_label':label(attribute) if attribute else None,
               'method':str(method) if method else None, 'method_label':label(method) if method else None,
               'context_type':context_type, 'source_proof_sha256':digest(proof)}
        if not job['english_label']:
            raise ValueError('An action target has no English source label')
        job['job_id'] = digest([manifest['build_id'], job])
        jobs.append(job)

    for target in sorted(graph.subjects(RDF.type, OW.Symptom), key=str):
        status = clinical_question_status('Symptom', label(target) or '')
        if status != 'pending_clinical_question':
            excluded.append({'target':str(target), 'reason':status})
            continue
        add(target, 'presence')
        for attribute in sorted(graph.objects(target, OW.hasAttribute), key=str):
            add(target, 'attribute', attribute=attribute)
    for target in sorted(graph.subjects(RDF.type, OW.ContextFactor), key=str):
        add(target, 'context', context_type=str(graph.value(target, OW.contextType)))
    for method in sorted(graph.subjects(RDF.type, OW.ExamMethod), key=str):
        targets = sorted(graph.subjects(OW.detectedBy, method), key=str)
        if len(targets) != 1:
            raise ValueError('A shared examination method needs distinct approved request semantics')
        add(targets[0], 'examination', method=method)
    if len({job['key'] for job in jobs}) != len(jobs):
        raise ValueError('Patient action keys must be unique')
    prior_accepted, prior_bindings = {}, []
    if exclude_accepted is not None:
        previous = workspace_path(exclude_accepted)
        previous_report = json.loads((previous / 'report.json').read_text())
        previous_verification = json.loads((previous / 'verification.json').read_text())
        with sqlite3.connect(f'file:{previous}/requests.sqlite3?mode=ro', uri=True) as ledger:
            prior_accepted = dict(ledger.execute('SELECT job_id,text FROM results'))
        if (previous_report['build_id'] != manifest['build_id'] or previous_verification['status'] != 'pass'
                or previous_verification['accepted_jobs'] != len(prior_accepted)
                or previous_report['accepted_jobs'] != len(prior_accepted)
                or not prior_accepted.keys() <= {job['job_id'] for job in jobs}):
            raise ValueError('Reuse only verified accepted actions from the identical graph')
        for filename in ('requests.sqlite3', 'report.json', 'verification.json'):
            source = previous / filename
            files[str(source.relative_to(ROOT))] = file_hash(source)
        previous_workset_path = previous.parent / 'workset.json'
        previous_workset = json.loads(previous_workset_path.read_text())
        if file_hash(previous_workset_path) != previous_report['workset_sha256']:
            raise ValueError('Previous accepted actions lost their frozen workset identity')
        carried = previous_workset.get('prior_accepted_jobs', {})
        if carried.keys() & prior_accepted.keys():
            raise ValueError('Previously accepted actions were generated again')
        prior_accepted = {**carried, **prior_accepted}
        if not prior_accepted.keys() <= {job['job_id'] for job in jobs}:
            raise ValueError('Prior accepted bindings differ from the current graph')
        files[str(previous_workset_path.relative_to(ROOT))] = file_hash(previous_workset_path)
        prior_bindings = [job for job in jobs if job['job_id'] in prior_accepted]
        jobs = [job for job in jobs if job['job_id'] not in prior_accepted]
    for path in (Path(__file__), Path(__file__).with_name('codex_cli.py'), Path(__file__).with_name('korean.py'),
                 PROMPTS / 'patient-generation.txt', PROMPTS / 'patient-review.txt'):
        files[str(path.relative_to(ROOT))] = file_hash(path)
    base_calls = 2 * math.ceil(len(jobs) / BATCH_SIZE)
    if continue_on_failure and (provider != 'nova_dev_key' or type(max_calls) is not int or not base_calls <= max_calls <= 1000):
        raise ValueError('D22 NOVA continuation requires a finite request ceiling up to 1000')
    workset = {'version':'d21-patient-actions-1', 'build_id':manifest['build_id'], 'model':MODEL,
               'reasoning_effort':'medium', 'provider':provider, 'scope':'patient_action_text_only',
               'files':files, 'jobs':jobs, 'exclusions':excluded, 'batch_size':BATCH_SIZE,
               'prior_accepted_jobs':prior_accepted,
               'prior_accepted_bindings':prior_bindings,
               'base_calls':base_calls, 'max_calls':max_calls if continue_on_failure else base_calls, 'label_jobs':0,
               'constraints':{'normalization':'NFC', 'min_codepoints':1, 'max_codepoints':30,
                              'count_spaces_and_punctuation':True, 'truncate':False},
               'continue_on_failure':continue_on_failure,
               'allowance_day':datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat(),
               'automatic_retries':0, 'automatic_resume':continue_on_failure, 'runtime_admission':'not_run'}
    write(output, workset)
    return {'status':'frozen', 'workset_sha256':file_hash(output), 'jobs':len(jobs),
            'by_purpose':dict(Counter(job['purpose'] for job in jobs)), 'exclusions':len(excluded),
            'label_jobs':0, 'previously_accepted_jobs':len(prior_accepted),
            'max_calls':workset['max_calls'], 'provider':provider}


def bounded_schema(jobs, *, review=False):
    schema = response_schema(review)
    items = schema['properties']['items']
    items.update(minItems=len(jobs), maxItems=len(jobs))
    fields = items['items']['properties']
    fields['job_id']['enum'] = [job['job_id'] for job in jobs]
    if not review:
        fields['text'] = {'anyOf':[{'type':'string', 'minLength':1, 'maxLength':30,
                                   'pattern':r'^[^\r\n]+$'}, {'type':'null'}]}
    return schema


class NovaDevClient:
    def __init__(self):
        origin = os.environ.get('NOVA_API_BASE', '').rstrip('/')
        key = os.environ.get('NOVA_DEV_KEY')
        if origin != 'https://nova.snubhai.org' or not key or os.environ.get('NOVA_SESSION_ID'):
            raise ValueError('Use the configured NOVA development key at the confirmed origin without a session')
        sys.path.insert(0, str(ROOT / 'submission'))
        from nova_sdk import Client
        self.client = Client(api_base=origin, token=key, timeout=240)
        self.identity = {'mode':'nova_dev_key', 'origin':origin, 'session':'none'}

    def chat(self, messages, *, model, request_id, output_schema, audit_directory):
        if model != MODEL:
            raise ValueError('Patient wording requires gpt-6-luna')
        directory = workspace_path(audit_directory)
        directory.mkdir(parents=True, exist_ok=False)
        canonical_ids = output_schema['properties']['items']['items']['properties']['job_id']['enum']
        aliases = {f'J{index:02d}':key for index,key in enumerate(canonical_ids, 1)}
        wire_ids = {value:key for key,value in aliases.items()}
        wire_schema = json.loads(json_text(output_schema))
        wire_schema['properties']['items']['items']['properties']['job_id']['enum'] = list(aliases)
        packets = json.loads(messages[-1]['content'])
        for packet in packets['items']:
            packet['job_id'] = wire_ids[packet['job_id']]
        wire_messages = [messages[0], {'role':'system', 'content':'Return JSON conforming exactly to this schema: ' + json_text(wire_schema)},
                         {'role':'user', 'content':json_text(packets)}]
        request = {'messages':wire_messages, 'model':'openai/' + model,
                   'request_id':request_id, 'reasoning_effort':'medium', 'max_tokens':8000}
        write(directory / 'request.json', {**request, 'authentication':self.identity,
              'automatic_retries':0, 'remote_response_schema_enforced':False,
              'output_schema':wire_schema, 'job_id_bindings':aliases,
              'constraint_enforcement':'independent_whole_response_validator'})
        try:
            response = self.client.chat(**request)
        except Exception as error:
            write(directory / 'error.json', {'error':str(error), 'status':getattr(error, 'status', None),
                                            'request_id':request_id, 'automatic_retries':0})
            raise
        write(directory / 'response.json', response)
        if response['choices'][0]['finish_reason'] != 'stop':
            raise ValueError('NOVA returned an incomplete response')
        content = json.loads(response['choices'][0]['message']['content'])
        items = content.get('items') if isinstance(content, dict) else None
        if (not isinstance(items, list) or len(items) != len(aliases)
                or any(not isinstance(item, dict) or item.get('job_id') not in aliases for item in items)
                or len({item['job_id'] for item in items}) != len(aliases)):
            raise ValueError('NOVA returned missing duplicate or foreign compact job IDs')
        for item in items:
            item['job_id'] = aliases[item['job_id']]
        mapped = json.loads(json_text(response))
        mapped['choices'][0]['message']['content'] = json_text(content)
        write(directory / 'bound-response.json', mapped)
        return mapped


def run(workset_path, output, *, client=None):
    workset_path, output = workspace_path(workset_path), workspace_path(output)
    if output.exists() or not output.is_relative_to(ROOT / 'data/preparation/v5'):
        raise ValueError('Use a new data-owned output and preserve existing request ledgers')
    workset = json.loads(workset_path.read_text())
    jobs = workset['jobs']
    base_calls = 2 * math.ceil(len(jobs) / BATCH_SIZE)
    continuing = workset.get('continue_on_failure', False)
    expected_calls = workset['max_calls']
    if (workset['version'] != 'd21-patient-actions-1' or workset['model'] != MODEL
            or workset['batch_size'] != BATCH_SIZE
            or (not continuing and expected_calls != base_calls)
            or (continuing and (workset['provider'] != 'nova_dev_key' or not base_calls <= expected_calls <= 1000))
            or len({job['job_id'] for job in jobs}) != len(jobs)):
        raise ValueError('Patient workset model budget or identity is invalid')
    for name, sha in workset['files'].items():
        if file_hash(workspace_path(ROOT / name)) != sha:
            raise ValueError('Patient workset input changed: ' + name)
    output.mkdir(parents=True)
    connection = sqlite3.connect(output / 'requests.sqlite3')
    connection.executescript('''CREATE TABLE calls(id TEXT PRIMARY KEY,stage TEXT NOT NULL,
        batch INTEGER NOT NULL,state TEXT NOT NULL,request TEXT NOT NULL,response TEXT,error TEXT);
        CREATE TABLE results(job_id TEXT PRIMARY KEY,text TEXT NOT NULL);''')
    accepted, failure, identity = {}, None, None
    resumptions = 0

    def attempt(batch, batch_number, feedback):
        proposed = None
        for stage in ('generation', 'review'):
            if continuing and datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat() != workset['allowance_day']:
                raise ValueError('NOVA daily allowance day changed; do not resume the next day')
            if connection.execute('SELECT COUNT(*) FROM calls').fetchone()[0] >= expected_calls:
                raise ValueError('Patient workset call budget exhausted')
            request_id = str(uuid4())
            packets = [{key:value for key,value in job.items() if key != 'kind'} for job in batch]
            if stage == 'review':
                packets = [{**packet, 'proposed_text':proposed[packet['job_id']]['text']} for packet in packets]
            elif feedback:
                packets = [{**packet, 'previous_batch_failure':feedback} for packet in packets]
            prompt = (PROMPTS / ('patient-' + stage + '.txt')).read_text()
            schema = bounded_schema(batch, review=stage == 'review')
            with connection:
                connection.execute('INSERT INTO calls VALUES(?,?,?,?,?,NULL,NULL)',
                                   (request_id, stage, batch_number, 'reserved', json_text(packets)))
            try:
                response = client.chat([{'role':'system', 'content':prompt},
                                        {'role':'user', 'content':json_text({'items':packets})}],
                                       model=MODEL, request_id=request_id, output_schema=schema,
                                       audit_directory=output / 'calls' / request_id)
                raw = response['choices'][0]['message']['content']
                with connection:
                    connection.execute('UPDATE calls SET response=? WHERE id=?', (raw, request_id))
                found = validate(json.loads(raw), batch, review=stage == 'review')
                with connection:
                    connection.execute("UPDATE calls SET state='completed' WHERE id=?", (request_id,))
                if stage == 'generation':
                    proposed = found
            except BaseException as error:
                with connection:
                    connection.execute("UPDATE calls SET state='failed_or_unknown',error=? WHERE id=?", (str(error), request_id))
                raise
            print(json_text({'stage':stage, 'batch':batch_number,
                             'calls_used':connection.execute('SELECT COUNT(*) FROM calls').fetchone()[0],
                             'max_calls':expected_calls, 'accepted_jobs':len(accepted)}), flush=True)
        return proposed

    try:
        if client is None:
            if workset['provider'] == 'nova_dev_key':
                client = NovaDevClient()
            elif workset['provider'] == 'snu_codex_cli':
                from .codex_cli import CodexClient
                client = CodexClient()
            else:
                raise ValueError('Unsupported wording provider')
        identity = client.identity
        for offset in range(0, len(jobs), BATCH_SIZE):
            batch = jobs[offset:offset + BATCH_SIZE]
            feedback = None
            while True:
                try:
                    proposed = attempt(batch, offset // BATCH_SIZE, feedback)
                    break
                except Exception as error:
                    reason = str(error)
                    code = str(getattr(error, 'code', ''))
                    if not code and reason == reason.upper() and reason.replace('_', '').isalnum():
                        code = reason
                    terminal = reason in {'Patient workset call budget exhausted',
                                          'NOVA daily allowance day changed; do not resume the next day'} or any(
                        term in code.upper() for term in
                        ('QUOTA', 'DAILY', 'CREDIT', 'RATE_LIMIT', 'CALL_LIMIT', 'BUDGET', 'TOKEN_LIMIT', 'INSUFFICIENT'))
                    if not continuing or terminal:
                        raise
                    resumptions += 1
                    feedback = reason
                    print(json_text({'stage':'authorized_nova_resumption', 'batch':offset // BATCH_SIZE,
                                     'resumptions':resumptions, 'failure':reason}), flush=True)
                    time.sleep(2)
            with connection:
                for job in batch:
                    text = proposed[job['job_id']]['text']
                    connection.execute('INSERT INTO results VALUES(?,?)', (job['job_id'], text))
                    accepted[job['job_id']] = text
    except Exception as error:
        failure = str(error)
    counts = dict(connection.execute('SELECT state,COUNT(*) FROM calls GROUP BY state'))
    calls = sum(counts.values())
    connection.close()
    questions, exams = {}, {}
    all_accepted = {**workset.get('prior_accepted_jobs', {}), **accepted}
    for job in jobs + workset.get('prior_accepted_bindings', []):
        if job['job_id'] not in all_accepted:
            continue
        text = all_accepted[job['job_id']]
        if job['action'] == 'EXAM':
            exams[job['method']] = text
        else:
            purpose = job['purpose']
            questions[job['key']] = {'text':text, 'answer_type':'presence' if purpose in {'presence', 'context'} else
                'duration' if job['attribute'] in {str(OW.TimeSinceOnset), str(OW.EpisodeDuration)} else 'category',
                'affirmative':purpose in {'presence', 'context'}, 'interviewable':True, 'reason':None}
    for item in workset['exclusions']:
        questions[item['target']] = {'text':'', 'answer_type':'free_text', 'affirmative':False,
                                     'interviewable':False, 'reason':item['reason']}
    write(output / 'accepted-questions.ko.json', questions)
    write(output / 'accepted-exam-requests.ko.json', exams)
    if not failure and len(accepted) == len(jobs):
        write(output / 'questions.ko.json', questions)
        write(output / 'exam-requests.ko.json', exams)
    report = {'status':'blocked' if failure else 'complete', 'failure':failure,
              'build_id':workset['build_id'], 'workset_sha256':file_hash(workset_path),
              'model':MODEL, 'reasoning_effort':'medium', 'provider':workset['provider'], 'authentication':identity,
              'jobs':len(jobs), 'accepted_jobs':len(accepted), 'unresolved_jobs':len(jobs) - len(accepted),
              'previously_accepted_jobs':len(workset.get('prior_accepted_jobs', {})), 'accepted_total':len(all_accepted),
              'calls_total':calls, 'call_states':counts, 'max_calls':expected_calls,
              'by_purpose':dict(Counter(job['purpose'] for job in jobs)), 'label_jobs':0,
              'constraints':workset['constraints'], 'automatic_retries':0, 'automatic_resume':continuing,
              'authorized_failure_resumptions':resumptions,
              'runtime_admission':'not_run', 'independent_clinical_validation':'not_run',
              'finished_at':datetime.now(timezone.utc).isoformat()}
    write(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description='Prepare only patient-reachable D20 Korean actions')
    commands = parser.add_subparsers(dest='command', required=True)
    freeze_command = commands.add_parser('freeze')
    freeze_command.add_argument('--graph', type=Path, required=True)
    freeze_command.add_argument('--output', type=Path, required=True)
    freeze_command.add_argument('--provider', choices=['nova_dev_key', 'snu_codex_cli'], required=True)
    freeze_command.add_argument('--exclude-accepted', type=Path)
    freeze_command.add_argument('--continue-on-failure', action='store_true')
    freeze_command.add_argument('--max-calls', type=int)
    run_command = commands.add_parser('run')
    run_command.add_argument('--workset', type=Path, required=True)
    run_command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = (freeze(args.graph, args.output, provider=args.provider, exclude_accepted=args.exclude_accepted,
                     continue_on_failure=args.continue_on_failure, max_calls=args.max_calls) if args.command == 'freeze'
              else run(args.workset, args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in {'frozen', 'complete'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
