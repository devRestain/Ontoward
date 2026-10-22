"""Dev-only semantic expansion and synthetic packets, never a runtime decoder."""
from copy import deepcopy
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def expand_wire(wire):
    payload = deepcopy(wire)
    patterns = payload.pop('patterns')
    for relation in payload['relations'].values():
        features = deepcopy(patterns[relation.pop('pattern')])
        for feature in features:
            if 'presence' in feature:
                status = feature.pop('presence')
                feature.update(attribute=None, expected_status=status, expected=status)
        relation['full_pattern'] = features
    for question in payload.get('questions', []):
        question['expected_by_disease'] = {disease: deepcopy(group['entries'])
            for group in question.pop('expected_groups') for disease in group['diseases']}
        scope = payload['scopes'][question['scope']]
        question.update(subject=scope['subject'], member=scope.get('member'), time=scope['time'])
    return payload


def clinical_meaning(logical):
    """Normalize only documented bookkeeping and typed defaults for comparison."""
    payload = deepcopy(logical)
    payload.pop('revision', None)
    limits = payload.pop('input_limits', {})
    payload['incomplete'] = payload.get('incomplete', False) or any(
        value > 0 for key, value in limits.items() if key.startswith('omitted_'))
    payload.setdefault('required', [])
    payload.setdefault('questions', [])
    if payload['task'] == 'clinical_rank':
        payload.pop('resources', None)
    for candidate in payload['candidates']:
        for category in ('supports', 'against', 'unresolved'):
            candidate.setdefault(category, [])
    def expected(value):
        if not isinstance(value, dict) or value.get('kind') not in {'quantity', 'interval'}:
            return value
        if value['kind'] == 'quantity':
            return dict(kind='quantity', value=value['value'], unit=value['unit'],
                operator=value.get('operator', 'eq'), approximate=value.get('approximate', False))
        return dict(kind='interval', lower=value.get('lower'), upper=value.get('upper'), unit=value['unit'],
            upper_unit=value.get('upper_unit'), lower_inclusive=value.get('lower_inclusive', True),
            upper_inclusive=value.get('upper_inclusive', True), approximate=value.get('approximate', False))
    for relation in payload['relations'].values():
        relation.setdefault('applicability', None)
        relation['rule_scope'].setdefault('subject_member', None)
        for feature in relation['full_pattern']:
            feature.setdefault('expected_status', None)
            feature['expected'] = expected(feature['expected'])
    for rows in payload['conditions'].values():
        for row in rows:
            row.setdefault('member', None)
    for question in payload['questions']:
        question.setdefault('member', None)
        for entries in question['expected_by_disease'].values():
            for entry in entries:
                if 'expected' in entry:
                    entry['expected'] = expected(entry['expected'])
    return payload


def assert_same_meaning(test, logical, wire):
    # String comparison detects false/0 and 0/0.0 differences missed by Python ==.
    test.assertEqual(canonical(clinical_meaning(logical)), canonical(clinical_meaning(expand_wire(wire))))


def duplicate_payload(count=50, features=16, diseases=62):
    feature_rows = [dict(attribute=None, expected_status='present', expected='present')]
    for index in range(features - 1):
        feature_rows.append(dict(attribute=f'Attribute {index}', expected_status='absent' if index == 0 else None,
            expected=dict(kind='interval', lower=0.0, unit='month', upper=12, upper_unit='month',
                operator='eq', approximate=False, lower_inclusive=False)))
    payload = dict(task='clinical_decision', stage='DifferentialDiagnosis', revision=5,
        chief='f_1', facts={
            'f_1': dict(status='present', kind='symptom', target='Synthetic target', scope='s_1',
                category='presentation', reported_by='patient', acquisition='SAY'),
            'f_2': dict(status='absent', kind='symptom', target='Synthetic target', scope='s_2',
                category='family_history', reported_by='caregiver', acquisition='SAY', polarity_scope='qualified'),
            'f_3': dict(status='present', value='Unbound normalized note', scope='s_3',
                category='medication', reported_by='patient', acquisition='SAY')},
        scopes={'s_1': dict(subject='patient', time='current', observation='o_1', episode='episode_1'),
            's_2': dict(subject='family', member='mother', time='past', observation='o_2', episode='episode_2'),
            's_3': dict(subject='patient', time='past'),
            's_4': dict(subject='patient', time='unspecified', observation='o_3', episode='episode_3')},
        conditions={'condition_1': [dict(target='Context', status='absent', subject='family', member='father', time='past')]},
        relations={}, candidates=[], evidence={}, questions=[], prior_order=['d_1'], required=[],
        resources=dict(turns=12, calls=80), input_limits={})
    for index in range(1, count + 1):
        payload['relations'][f'r_{index}'] = dict(target='Synthetic target',
            effect='support' if index % 2 else 'against', full_pattern=deepcopy(feature_rows),
            rule_scope=dict(subject='patient', subject_member=None, time_context='current' if index % 3 else 'past'),
            applicability='condition_1' if index % 4 else None)
        payload['evidence'][f'e_{index}'] = dict(level='feature', relation=f'r_{index}', feature=0,
            facts=['f_1'] if index % 2 else ['f_2'], scope='s_1' if index % 2 else 's_2', reason='missing_feature')
    evidence = list(payload['evidence'])
    for index in range(1, diseases + 1):
        payload['candidates'].append(dict(ref=f'd_{index}', name=f'Synthetic disease {index}',
            supports=evidence[:1], against=evidence[1:2], unresolved=evidence[2:]))
    for index in range(1, min(count, 8) + 1):
        entries = [dict(relation=f'r_{index}', feature=0, collection_only=True),
                   dict(relation=f'r_{index}', feature=None, expected='absent')]
        payload['questions'].append(dict(ref=f'q_{index}', kind='SAY', target='Synthetic target',
            subject='patient', time='unspecified', scope='s_4',
            expected_by_disease={f'd_{disease}': deepcopy(entries) for disease in range(1, diseases + 1)}))
    return payload
