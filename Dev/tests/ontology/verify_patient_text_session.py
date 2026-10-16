from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from Dev.ontology.database import file_hash
from Dev.ontology.korean import validate
from Dev.ontology.v5 import write


def verify(directory):
    checks, accepted, proofs, requests, failures, runs = [], {}, {}, set(), [], []
    usage = Counter()
    original = json.loads((directory / 'workset.json').read_text())
    expected = {job['job_id']:job for job in original['jobs']}
    custody = json.loads((directory / 'code-custody.json').read_text())

    def require(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    for entry in custody['worksets']:
        workset_path = ROOT / entry['workset']
        workset = json.loads(workset_path.read_text())
        output = directory / 'nova' if workset_path == directory / 'workset.json' else workset_path.parent / 'results'
        report = json.loads((output / 'report.json').read_text())
        require(report['workset_sha256'] == file_hash(workset_path), 'retain_workset_' + entry['workset'])
        require(workset['build_id'] == original['build_id'] and workset['label_jobs'] == 0,
                'retain_graph_and_patient_only_scope_' + entry['workset'])
        for name, sha in workset['files'].items():
            source = workset_path.parent / 'generator-snapshot' / name if name.startswith('Dev/') else ROOT / name
            require(file_hash(source) == sha, 'preserve_versioned_input_' + entry['workset'] + ':' + name)
        jobs = {job['job_id']:job for job in workset['jobs']}
        require(all(job == expected[key] for key, job in jobs.items()), 'preserve_original_action_bindings_' + entry['workset'])
        prior = workset.get('prior_accepted_jobs', {})
        require(prior == accepted, 'carry_only_previous_reviewed_results_' + entry['workset'])
        with sqlite3.connect(f'file:{output}/requests.sqlite3?mode=ro', uri=True) as ledger:
            calls = ledger.execute('SELECT id,stage,batch,state,request,response,error FROM calls ORDER BY rowid').fetchall()
            results = dict(ledger.execute('SELECT job_id,text FROM results'))
        require(len(calls) == report['calls_total'] <= workset['max_calls'], 'account_for_reserved_calls_' + entry['workset'])
        require(dict(Counter(row[3] for row in calls)) == report['call_states'], 'retain_call_states_' + entry['workset'])
        generated, reviewed, run_proofs = {}, {}, {}
        for ident, stage, batch, state, request, response, error in calls:
            require(ident not in requests and state != 'reserved', 'retain_unique_terminal_request_' + ident)
            requests.add(ident)
            packets = json.loads(request)
            selected = workset['jobs'][batch * 20:(batch + 1) * 20]
            require([item['job_id'] for item in packets] == [job['job_id'] for job in selected], 'bind_frozen_batch_' + ident)
            audit = json.loads((output / 'calls' / ident / 'request.json').read_text())
            require(audit['model'] == 'openai/gpt-6-luna' and audit['reasoning_effort'] == 'medium'
                    and audit['authentication']['mode'] == 'nova_dev_key' and 'session_id' not in audit,
                    'retain_nova_only_medium_route_' + ident)
            raw_path = output / 'calls' / ident / 'response.json'
            raw_response = json.loads(raw_path.read_text()) if raw_path.exists() else None
            if raw_response:
                for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                    usage[key] += raw_response.get('usage', {}).get(key, 0)
            if state != 'completed':
                require(bool(error), 'retain_failed_request_reason_' + ident)
                failures.append({'request_id':ident, 'stage':stage, 'workset':entry['workset'], 'error':error})
                continue
            require(raw_response is not None and audit['max_tokens'] == 8000, 'retain_complete_provider_response_' + ident)
            body = json.loads(response)
            raw_body = json.loads(raw_response['choices'][0]['message']['content'])
            if 'job_id_bindings' in audit:
                aliases = audit['job_id_bindings']
                require(set(aliases.values()) == {job['job_id'] for job in selected}, 'retain_compact_id_bijection_' + ident)
                for item in raw_body['items']:
                    item['job_id'] = aliases[item['job_id']]
            require(raw_body == body, 'preserve_provider_wording_without_repair_' + ident)
            found = validate(body, selected, review=stage == 'review')
            if stage == 'generation':
                generated[batch] = (ident, found)
            else:
                generation_id, candidates = generated[batch]
                require(all(item['proposed_text'] == candidates[item['job_id']]['text'] for item in packets),
                        'review_exact_generated_wording_' + ident)
                for key in found:
                    require(key not in reviewed, 'accept_action_once_' + key)
                    reviewed[key] = candidates[key]['text']
                    run_proofs[key] = {'generation_request_id':generation_id, 'review_request_id':ident,
                                      'workset':entry['workset'], 'workset_sha256':report['workset_sha256']}
        require(results == reviewed and len(results) == report['accepted_jobs'], 'accept_only_reviewed_sqlite_results_' + entry['workset'])
        require(not accepted.keys() & results.keys(), 'avoid_regenerating_previous_results_' + entry['workset'])
        accepted.update(results)
        proofs.update(run_proofs)
        runs.append({'workset':entry['workset'], 'status':report['status'], 'requests':len(calls),
                     'new_accepted_jobs':len(results), 'failure_resumptions':report.get('authorized_failure_resumptions', 0)})
        last_output, last_report = output, report

    require(last_report['status'] == 'complete' and accepted.keys() == expected.keys(), 'complete_every_selected_patient_action')
    require(len(requests) <= 1000, 'respect_the_same_session_request_ceiling')
    questions = json.loads((last_output / 'questions.ko.json').read_text())
    exams = json.loads((last_output / 'exam-requests.ko.json').read_text())
    rows = []
    for key, job in expected.items():
        text = accepted[key]
        require(unicodedata.normalize('NFC', text) == text and 1 <= len(text) <= 30
                and not any(char in text for char in '\r\n'), 'validate_final_patient_text_' + key)
        exported = exams[job['method']] if job['action'] == 'EXAM' else questions[job['key']]['text']
        require(exported == text, 'export_exact_reviewed_text_' + key)
        rows.append({**job, 'text':text, 'codepoints':len(text), 'normalization':'NFC',
                     'origin':'model_generated_patient_action', **proofs[key]})
    require(all(not questions[item['target']]['interviewable'] and not questions[item['target']]['text']
                for item in original['exclusions']), 'retain_all_diagnosis_qualified_exclusions')
    require(sum(item['interviewable'] for item in questions.values()) + len(exams) == len(expected),
            'exclude_unselected_patient_actions')

    for name in ('questions.ko.json', 'exam-requests.ko.json'):
        (directory / name).write_bytes((last_output / name).read_bytes())
    write(directory / 'accepted-review.json', rows)
    write(directory / 'accepted-questions.ko.json', questions)
    write(directory / 'accepted-exam-requests.ko.json', exams)
    summary = {'status':'complete', 'build_id':original['build_id'], 'provider':'nova_dev_key',
               'model':'openai/gpt-6-luna', 'reasoning_effort':'medium', 'accepted_jobs':len(accepted),
               'remaining_jobs':0, 'by_purpose':dict(Counter(job['purpose'] for job in expected.values())),
               'excluded_targets':len(original['exclusions']), 'label_jobs':0, 'total_requests':len(requests),
               'failed_requests_preserved':len(failures), 'successful_validation_stages':len(requests) - len(failures),
               'authorized_failure_resumptions':sum(run['failure_resumptions'] for run in runs),
               'reported_token_usage':dict(usage), 'minimum_codepoints':min(map(len, accepted.values())),
               'maximum_codepoints':max(map(len, accepted.values())), 'all_texts_nfc':True,
               'request_ceiling':1000, 'service_limit_reached':False, 'stop_reason':'selected_workset_complete',
               'runtime_admission':'not_run', 'independent_clinical_validation':'not_run',
               'runs':runs, 'finished_at':datetime.now(timezone.utc).isoformat()}
    write(directory / 'execution-summary.json', summary)
    write(directory / 'failed-requests.json', failures)
    assets = {'status':'generated_text_ready', 'build_id':original['build_id'], 'accepted_jobs':len(accepted),
              'runtime_admission':'not_run', 'independent_clinical_validation':'not_run',
              'text_assets':{key:{'path':str((directory / name).relative_to(ROOT)), 'sha256':file_hash(directory / name)}
                             for key,name in (('questions','questions.ko.json'), ('exam_requests','exam-requests.ko.json'))}}
    write(directory / 'text-assets.json', assets)
    result = {'status':'pass', 'check_count':len(checks), 'checks':checks, 'accepted_jobs':len(accepted),
              'requests':len(requests), 'failed_requests_preserved':len(failures),
              'minimum_codepoints':summary['minimum_codepoints'], 'maximum_codepoints':summary['maximum_codepoints'],
              'source_graph_and_generator_pins':'pass', 'runtime_admission':'not_run',
              'independent_clinical_validation':'not_run', 'text_assets_sha256':file_hash(directory / 'text-assets.json')}
    write(directory / 'verification.json', result)
    print(json.dumps({key:value for key,value in result.items() if key != 'checks'}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    arguments = parser.parse_args()
    verify(arguments.directory.resolve())
