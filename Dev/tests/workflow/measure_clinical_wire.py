"""Offline final-message byte comparison; never execute a model or estimate tokens."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import fixtures as f
from clinical_wire_fixtures import assert_same_meaning, duplicate_payload
from workflow.doctor_ear import DoctorEar
from workflow.input_types import ContextStatement
from workflow.model_context import message_metrics, messages
from workflow.rules.clinical_wire import compact_clinical_payload
from workflow.rules.decision import bound_graph_input, clinical_messages, prepare_decision


def baseline_config(root):
    manifest = json.loads((root / 'prompts.json').read_text())
    prompts = {route: '\n\n'.join((root.parent / path).read_text().strip() for path in paths)
               for route, paths in manifest.items()}
    return SimpleNamespace(prompt=lambda *routes: '\n\n'.join(prompts[route] for route in routes))


def clinical_baseline(config, payload):
    route = {'clinical_rank': 'clinical.rank', 'clinical_action': 'clinical.action',
             'clinical_decision': 'clinical.decision'}[payload['task']]
    routes = [route, 'session.' + payload['stage']]
    if 'validation_error' in payload:
        routes.append('clinical.repair')
    return messages(config.prompt(*routes), payload)


def compare(test, baseline, current, logical, **labels):
    before = clinical_baseline(baseline, logical)
    work = SimpleNamespace(payload=logical)
    after = clinical_messages(current, work)
    assert_same_meaning(test, logical, json.loads(after[-1]['content']))
    return dict(**labels, role='clinical', task=logical['task'],
        phase='repair' if 'validation_error' in logical else 'initial',
        before=message_metrics('clinical', before), after=message_metrics('clinical', after),
        semantic_equivalence='pass_against_current_bound', actual_after_tokens='not_measured')


def measure(baseline, output, inventory):
    test = unittest.TestCase()
    c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
    report = dict(status='pass', baseline_revision='07420ee44587a323eb2434d95c7656cdec1986b9',
        actual_model_calls=0, token_estimation='not_performed', graph_detail_limit=50,
        byte_metric='ensure_ascii=False,separators=(comma,colon),allow_nan=False; UTF-8',
        block_sizes='Diagnostic values; exclude enclosing key/separator overhead and may overlap',
        comparisons=[], unsupported_saved_requests=[])
    rows = report['comparisons']
    for mode in ('rank', 'decision', 'action'):
        if mode == 'action':
            c.differential.accept(s, dict(ranked_disease_refs=list(work.refs)), work, closing=True)
        work = prepare_decision(s, c.knowledge, c.tools, mode=mode)
        rows.append(compare(test, baseline, c.config, work.payload, kind='synthetic_small'))
        work.payload['validation_error'] = 'unregistered_question_ref' if mode != 'rank' else 'invalid_ranking'
        rows.append(compare(test, baseline, c.config, work.payload, kind='synthetic_small'))
    for task in ('clinical_rank', 'clinical_decision', 'clinical_action'):
        logical = duplicate_payload()
        logical['task'] = task
        if task == 'clinical_rank':
            logical['questions'] = []
        elif task == 'clinical_action':
            logical['prior_order'] = [candidate['ref'] for candidate in logical['candidates']]
            for candidate in logical['candidates']:
                for category in ('supports', 'against', 'unresolved'):
                    candidate.pop(category)
            logical['evidence'] = {}
        bound_graph_input(logical)
        for phase in ('initial', 'repair'):
            if phase == 'repair':
                logical['validation_error'] = 'invalid_reference ' * 80
            rows.append(compare(test, baseline, c.config, logical, kind='synthetic_duplicate_heavy'))
    statement = ContextStatement.model_validate(f.statement(quote='0 kg', focus='attribute',
        attribute_terms=['Body weight'], measurement=dict(kind='quantity', value=0, unit='kg')))
    contracts = {index: [dict(id='Synthetic target', kind='Symptom', attributes=[dict(id='Body weight', units=['kg'],
        values=[dict(id=f'Category {value}') for value in range(32)])])] for index in range(6)}
    for phase in ('mapping', 'mapping_repair'):
        routes = ['mapping.select', *(['mapping.repair'] if phase.endswith('repair') else [])]
        payload = DoctorEar._mapping_payload([statement] * 6, list(contracts), contracts, phase, [])
        original = deepcopy(payload)
        for row in original['statements']:
            row['candidates'] = deepcopy(contracts[0])
        rows.append(dict(kind='synthetic_numeric_mapping', role='gateway', task='input_mapping', phase=phase,
            before=message_metrics('gateway', messages(baseline.prompt(*routes), original)),
            after=message_metrics('gateway', messages(c.config.prompt(*routes), payload)),
            actual_after_tokens='not_measured'))
    selected = set()
    if inventory:
        saved = json.loads(inventory.read_text())
        selected.update(row['file'] for row in saved['context_failures'])
        report['saved_inventory'] = dict(requests_scanned=saved['saved_requests_scanned'], context_failures=len(saved['context_failures']))
    selected.add('Tmp/test-evaluator/C10-20261021T234358Z-50434359aa/simulator/requests.json')
    selected.add('Tmp/test-evaluator/C03-20261021T170847Z-13e2a787c9/simulator/requests.json')
    for source in sorted(selected):
        file = Path(source)
        if not file.is_file():
            continue
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        for ident, record in json.loads(file.read_text()).items():
            request = record.get('request', {})
            original = request.get('messages')
            if not original:
                continue
            payload = json.loads(original[-1]['content'])
            task, outcome = payload.get('task'), record.get('outcome', [])
            failed_context = bool(outcome and outcome[0] != 200 and 'CONTEXT_LIMIT_EXCEEDED' in str(outcome))
            current_saved = 'C10-20261021T234358Z-50434359aa' in source
            if task not in {'clinical_rank', 'clinical_decision', 'clinical_action', 'input_mapping', 'input_context', 'education', 'education_doctor'}:
                continue
            numeric_saved = task == 'input_mapping' and any(row.get('measurement') for row in payload['statements'])
            unchanged_education = task in {'education', 'education_doctor'}
            if not (failed_context or current_saved or numeric_saved or unchanged_education):
                continue
            role = 'clinical' if task.startswith('clinical_') else task if unchanged_education else 'gateway'
            labels = dict(kind='saved_failure_current_bound' if failed_context else
                'saved_numeric_mapping' if numeric_saved else 'saved_unchanged_education' if unchanged_education else 'saved_current_bound',
                file=source, file_sha256=digest, request_id=ident, historical_outcome=outcome[0] if outcome else None,
                actual_saved=message_metrics(role, original),
                actual_saved_prompt_tokens=((outcome[1].get('usage') or {}).get('prompt_tokens')
                    if outcome and outcome[0] == 200 else None))
            try:
                if task.startswith('clinical_'):
                    logical = deepcopy(payload)
                    if 'input_limits' not in logical:
                        logical['input_limits'] = dict(graph_items=50,
                            omitted_question_options=max(0, len(logical['questions']) - 50))
                        bound_graph_input(logical)
                        labels['historical_selection'] = 'Apply current bound to older unbounded payload; do not attribute that loss to compaction'
                    rows.append(compare(test, baseline, c.config, logical, **labels))
                else:
                    wire = deepcopy(payload)
                    if task == 'input_mapping':
                        routes = ['mapping.select', *(['mapping.repair'] if payload['phase'] == 'mapping_repair' else [])]
                        for statement_row in wire['statements']:
                            if statement_row.get('measurement'):
                                statement_row['candidates'] = [dict(id=target['id'], kind=target['kind'], attributes=[
                                    dict(id=attribute['id'], units=attribute['units']) for attribute in target['attributes']])
                                    for target in statement_row['candidates']]
                        before = messages(baseline.prompt(*routes), payload)
                        after = messages(c.config.prompt(*routes), wire)
                    else:
                        # Ear context and its prompts are deliberately unchanged.
                        before, after = original, deepcopy(original)
                    rows.append(dict(**labels, role=role, task=task, phase=message_metrics(role, after)['phase'],
                        before=message_metrics(role, before), after=message_metrics(role, after),
                        actual_after_tokens='not_measured'))
            except (KeyError, TypeError, ValueError, AssertionError) as error:
                report['unsupported_saved_requests'].append(dict(file=source, request_id=ident, task=task, reason=str(error)[:300]))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], comparisons=len(rows),
        unsupported_saved_requests=report['unsupported_saved_requests'], saved_inventory=report.get('saved_inventory')), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--saved-inventory', type=Path)
    args = parser.parse_args()
    measure(baseline_config(args.baseline_config), args.output, args.saved_inventory)
