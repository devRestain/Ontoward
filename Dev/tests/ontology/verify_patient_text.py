from __future__ import annotations

import argparse
from collections import Counter
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


def verify(workset_path, directory):
    workset = json.loads(workset_path.read_text())
    report = json.loads((directory / 'report.json').read_text())
    checks = []
    def require(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    require(report['workset_sha256'] == file_hash(workset_path), 'retain_exact_workset_identity')
    for name, sha in workset['files'].items():
        require(file_hash(ROOT / name) == sha, 'preserve_pin_' + name)
    require(workset['label_jobs'] == 0 and report['label_jobs'] == 0, 'exclude_internal_label_translation')
    base_calls = 2 * ((len(workset['jobs']) + 19) // 20)
    require((base_calls <= workset['max_calls'] <= 1000 if workset.get('continue_on_failure') else workset['max_calls'] == base_calls),
            'bind_finite_budget_to_patient_actions_and_explicit_continuation')
    expected, generations, accepted = {}, {}, {}
    jobs = {job['job_id']:job for job in workset['jobs']}
    with sqlite3.connect(f'file:{directory}/requests.sqlite3?mode=ro', uri=True) as ledger:
        calls = ledger.execute('SELECT id,stage,batch,state,request,response,error FROM calls ORDER BY rowid').fetchall()
        results = dict(ledger.execute('SELECT job_id,text FROM results'))
    require(len(calls) == report['calls_total'] <= workset['max_calls'], 'account_for_every_reserved_request')
    require(dict(Counter(row[3] for row in calls)) == report['call_states'], 'retain_exact_call_outcomes')
    require(len({row[0] for row in calls}) == len(calls), 'preserve_unique_request_ids_without_retransmission')
    for ident, stage, batch, state, request, response, error in calls:
        packets = json.loads(request)
        selected = [jobs[packet['job_id']] for packet in packets]
        require([job['job_id'] for job in selected] == [job['job_id'] for job in
                workset['jobs'][batch * 20:(batch + 1) * 20]], 'bind_request_to_frozen_batch_' + ident)
        if state != 'completed':
            require(error is not None, 'retain_failure_reason_' + ident)
            continue
        found = validate(json.loads(response), selected, review=stage == 'review')
        if stage == 'generation':
            generations[batch] = found
        else:
            require(batch in generations, 'review_only_existing_generated_text_' + ident)
            require(all(packet['proposed_text'] == generations[batch][packet['job_id']]['text'] for packet in packets),
                    'compare_exact_generated_text_without_rewrite_' + ident)
            accepted.update({key:generations[batch][key]['text'] for key in found})
        audit = json.loads((directory / 'calls' / ident / 'request.json').read_text())
        require(audit['model'] == 'openai/gpt-6-luna' and audit['reasoning_effort'] == 'medium'
                and audit['max_tokens'] == 8000 and 'session_id' not in audit,
                'verify_actual_nova_model_reasoning_ceiling_and_session_' + ident)
        if 'job_id_bindings' in audit:
            aliases = audit['job_id_bindings']
            require(set(aliases.values()) == {job['job_id'] for job in selected}, 'bind_wire_ids_to_frozen_jobs_' + ident)
            wire = json.loads((directory / 'calls' / ident / 'response.json').read_text())
            wire_content = json.loads(wire['choices'][0]['message']['content'])
            for item in wire_content['items']:
                item['job_id'] = aliases[item['job_id']]
            require(wire_content == json.loads(response), 'preserve_raw_provider_text_with_only_id_translation_' + ident)
    require(results == accepted and len(results) == report['accepted_jobs'], 'accept_only_separately_reviewed_results')
    if 'accepted_total' in report:
        require(report['accepted_total'] == len(results) + len(workset.get('prior_accepted_jobs', {})),
                'account_for_previously_reviewed_actions_without_new_requests')
    require(all(unicodedata.normalize('NFC', text) == text and 1 <= len(text) <= 30
                and not any(char in text for char in '\r\n') for text in results.values()),
            'independently_validate_all_accepted_nfc_1_to_30_codepoints')
    questions = json.loads((directory / 'accepted-questions.ko.json').read_text())
    exams = json.loads((directory / 'accepted-exam-requests.ko.json').read_text())
    for key, text in results.items():
        job = jobs[key]
        actual = exams[job['method']] if job['action'] == 'EXAM' else questions[job['key']]['text']
        require(actual == text, 'export_exact_reviewed_wording_' + key)
    require(all(not questions[item['target']]['interviewable'] and not questions[item['target']]['text']
                for item in workset['exclusions']), 'retain_noninterviewable_target_exclusions')
    require(report['automatic_retries'] == 0 and report['automatic_resume'] == workset.get('continue_on_failure', False),
            'bind_resumption_policy_to_explicit_user_selection')
    complete = report['status'] == 'complete'
    require(complete == (len(results) == len(jobs) and
            (workset.get('continue_on_failure') or all(row[3] == 'completed' for row in calls))),
            'distinguish_complete_generation_from_partial_results')
    require(all((directory / name).exists() == complete for name in ('questions.ko.json', 'exam-requests.ko.json')),
            'export_complete_assets_only_after_the_whole_workset_passes')
    output = {'status':'pass', 'check_count':len(checks), 'checks':checks, 'generation_status':report['status'],
              'provider':report['provider'], 'calls':len(calls), 'accepted_jobs':len(results),
              'remaining_jobs':len(jobs) - len(results), 'max_accepted_codepoints':max(map(len, results.values()), default=0),
              'runtime_admission':'not_run', 'independent_clinical_validation':'not_run'}
    write(directory / 'verification.json', output)
    print(json.dumps({key:value for key,value in output.items() if key != 'checks'}, indent=2))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workset', required=True, type=Path)
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    verify(args.workset.resolve(), args.directory.resolve())
