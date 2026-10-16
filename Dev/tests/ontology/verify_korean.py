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
from Dev.ontology.korean import BATCH_SIZE, MODEL, check_catalog, validate
from Dev.ontology.v5 import digest, write


def verify(directory):
    directory = directory.resolve()
    workset_path = directory / 'korean-workset.json'
    workset = json.loads(workset_path.read_text())
    output = directory / 'korean'
    report = json.loads((output / 'report.json').read_text())
    checks = []
    def require(value, name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    check_catalog(directory / 'catalog')
    require(report['workset_sha256'] == file_hash(workset_path), 'executed_frozen_workset_identity')
    require(workset['catalog_manifest_sha256'] == file_hash(directory / 'catalog/manifest.json'), 'executed_catalog_identity')
    for name, sha in workset['generator_files'].items():
        require(file_hash(ROOT / 'Dev/ontology' / name) == sha, 'generator_pin:' + name)
    for name, sha in workset['prompt_files'].items():
        require(file_hash(ROOT / 'Dev/ontology/prompts' / name) == sha, 'prompt_pin:' + name)
    l, q = len(workset['label_jobs']), len(workset['question_jobs'])
    ceiling = 2 * ((l + 19) // 20 + (q + 19) // 20)
    require(report['max_calls'] == workset['max_calls'] == ceiling and workset['batch_size'] == BATCH_SIZE == 20,
            'complete_workset_budget_formula')
    jobs = {job['job_id']:job for job in workset['label_jobs'] + workset['question_jobs']}
    require(len(jobs) == l + q, 'no_duplicate_workset_job_ids')
    require(report['model'] == workset['model'] == MODEL and report['provider'] == 'docker_codex_cli', 'designated_cli_model')
    batches = {}
    for kind in ('label', 'question'):
        source = workset[kind + '_jobs']
        for offset in range(0, len(source), BATCH_SIZE):
            batch = source[offset:offset+BATCH_SIZE]
            batches[kind, digest([job['job_id'] for job in batch])] = batch
    with sqlite3.connect(output / 'requests.sqlite3') as ledger:
        ledger.row_factory = sqlite3.Row
        calls = list(ledger.execute('SELECT * FROM calls ORDER BY rowid'))
        results = dict(ledger.execute('SELECT job_id,text FROM results'))
    require(len(calls) == report['calls_total'] <= ceiling, 'every_reserved_attempt_counts_against_frozen_budget')
    require(len({row['id'] for row in calls}) == len(calls), 'unique_request_identity')
    completed = {}
    for row in calls:
        kind, phase = row['stage'].split('_', 1)
        batch = batches[kind, row['batch']]
        packets = json.loads(row['request'])
        require([packet['job_id'] for packet in packets] == [job['job_id'] for job in batch] and len(batch) <= 20,
                'exact_ordered_batch:' + row['id'])
        audit = output / 'calls' / row['id']
        request = json.loads((audit / 'request.json').read_text())
        argv = request['argv']
        require(request['request_id'] == row['id'] and argv[argv.index('--model')+1] == MODEL
                and 'web_search="disabled"' in argv and 'model_providers.openai.request_max_retries=0' in argv
                and 'model_providers.openai.stream_max_retries=0' in argv,
                'transport_identity_and_no_retry_settings:' + row['id'])
        if row['state'] == 'completed':
            found = validate(json.loads(row['response']), batch, review=phase == 'review')
            completed[kind, row['batch'], phase] = (row['id'], found)
        else:
            require(row['state'] in {'failed_or_unknown', 'reserved'} and row['id'] == calls[-1]['id'],
                    'failed_or_unknown_request_stops_without_retransmission')
    for key, text in results.items():
        job = jobs[key]
        kind = job['kind']
        batch_id = next(identity for (group, identity), batch in batches.items()
                        if group == kind and any(item['job_id'] == key for item in batch))
        generation = completed[kind, batch_id, 'generation']
        review = completed[kind, batch_id, 'review']
        if generation[0] == review[0] or generation[1][key]['text'] != text or review[1][key]['decision'] != 'accept':
            raise AssertionError('result_lacks_separate_semantic_comparison')
    require(True, 'every_accepted_result_has_separate_completed_generation_and_review')
    labels = json.loads((output / 'completed-labels.ko.json').read_text())
    for entry in workset['entries']:
        if entry['korean_origin'] == 'Korean_SNOMED_CT' and labels.get(entry['uri']) != entry['korean_label']:
            raise AssertionError('official_korean_description_was_changed')
    require(all(text.strip() and unicodedata.normalize('NFC', text) == text for text in labels.values()),
            'official_and_completed_model_labels_remain_nfc')
    accepted_counts = Counter(jobs[key]['kind'] for key in results)
    require(dict(accepted_counts) == report['accepted_jobs'], 'accepted_jobs_account_for_the_whole_workset')
    if report['status'] == 'complete':
        require(len(results) == l + q and report['failure'] is None, 'complete_means_every_job_passed_both_requests')
        all_labels = json.loads((output / 'all-labels.ko.json').read_text())
        with (directory / 'catalog/nodes.jsonl').open() as stream:
            node_ids = {json.loads(line)['uri'] for line in stream}
        require(node_ids <= all_labels.keys(), 'all_lexical_and_structural_nodes_have_korean_display_labels')
        questions = json.loads((output / 'all-questions.ko.json').read_text())
        for job in workset['question_jobs']:
            text = questions[job['key']]['text']
            if text != results[job['job_id']] or not 1 <= len(text) <= 30 or unicodedata.normalize('NFC', text) != text:
                raise AssertionError('invalid_prepared_clinical_question')
        require(True, 'every_prepared_clinical_question_is_nfc_1_to_30_without_truncation')
    else:
        require(report['status'] == 'blocked' and bool(report['failure']), 'incomplete_workset_has_exact_failure')
        require(not (output / 'all-labels.ko.json').exists() and not (output / 'questions.ko.json').exists(),
                'blocked_workset_is_never_published_as_complete_assets')
    require(report['automatic_retries'] == 0 and report['next_day_auto_resume'] is False,
            'no_automatic_retry_or_next_day_resume')
    require(report['independent_clinical_validation'] == report['runtime_admission'] == 'not_run',
            'automated_semantics_do_not_claim_clinical_approval_or_admission')
    write(directory / 'workset-identity.json', {'path':str(workset_path.relative_to(ROOT)),
        'sha256':file_hash(workset_path), 'bytes':workset_path.stat().st_size,
        'labels':l, 'questions':q, 'max_calls':ceiling, 'build_id':workset['build_id'],
        'catalog_manifest_sha256':workset['catalog_manifest_sha256'], 'prompt_files':workset['prompt_files'],
        'generator_files':workset['generator_files']})
    result = {'status':'pass', 'check_count':len(checks), 'checks':checks, 'korean_completion':report['status'],
        'accepted_jobs':dict(accepted_counts), 'calls_total':len(calls), 'max_calls':ceiling,
        'official_labels':report['official_source_labels'], 'model_translation_labels':report['model_translation_labels'],
        'unresolved_labels':report['unresolved_lexical_labels'], 'unresolved_questions':report['unresolved_question_jobs'],
        'runtime_admission':'not_run', 'independent_clinical_validation':'not_run'}
    write(directory / 'korean-verification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    result = verify(parser.parse_args().directory)
    print(json.dumps({key:value for key,value in result.items() if key != 'checks'}, indent=2))
