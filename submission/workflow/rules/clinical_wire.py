"""Request-local clinical projection; never change logical work or graph objects."""
from copy import deepcopy
import json


def wire_key(value):
    # JSON distinguishes false/0 and preserves numeric types, units and list order.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def check_fields(row, allowed, schema):
    extra = row.keys() - set(allowed.split())
    if extra:
        raise ValueError(f'unknown_clinical_wire_{schema}_fields:{sorted(extra)}')


def fields(row, allowed, schema):
    check_fields(row, allowed, schema)
    return deepcopy(row)


def compact_expected(value):
    # Concept and concept_set have already been projected by prepare_decision.
    if not isinstance(value, dict) or value.get('kind') not in {'quantity', 'interval'}:
        return deepcopy(value)
    check_fields(value, 'kind concept concepts selection match value operator lower upper '
           'lower_inclusive upper_inclusive unit upper_unit approximate', 'expected')
    inactive = dict(concept=None, concepts=[], selection='any_of', match='exact')
    if value['kind'] == 'quantity':
        inactive.update(lower=None, upper=None, upper_unit=None, lower_inclusive=True, upper_inclusive=True)
    else:
        inactive.update(value=None, operator='eq')
    if any(key in value and wire_key(value[key]) != wire_key(default) for key, default in inactive.items()):
        raise ValueError('clinical_wire_nondefault_inactive_expected_field')
    if value['kind'] == 'quantity':
        result = {key: deepcopy(value[key]) for key in ('kind', 'value', 'unit') if key in value}
        if 'operator' in value and value['operator'] != 'eq':
            result['operator'] = value['operator']
    else:
        result = {key: deepcopy(value[key]) for key in ('kind', 'lower', 'upper', 'unit', 'upper_unit')
                  if key in value and value[key] is not None}
        for key in ('lower_inclusive', 'upper_inclusive'):
            if key in value and value[key] is not True:
                result[key] = value[key]
    if 'approximate' in value and value['approximate'] is not False:
        result['approximate'] = value['approximate']
    return result


def compact_feature(feature):
    row = fields(feature, 'attribute expected_status expected', 'feature')
    if (row.get('attribute') is None and row.get('expected_status') in {'present', 'absent'}
            and row.get('expected') == row['expected_status']):
        return {'presence': row['expected_status']}
    if row.get('expected_status') is None:
        row.pop('expected_status', None)  # Default: no additional target status condition.
    if 'expected' in row:
        row['expected'] = compact_expected(row['expected'])
    return row


def compact_clinical_payload(payload):
    """Project the already bounded logical payload, with exact ordered sharing."""
    check_fields(payload, 'task stage revision chief chief_route facts scopes conditions relations prior_order '
           'required resources candidates evidence questions input_limits validation_error', 'payload')
    task = payload['task']
    if task not in {'clinical_rank', 'clinical_decision', 'clinical_action'}:
        raise ValueError('unsupported_clinical_wire_task')
    wire = {key: deepcopy(payload[key]) for key in ('task', 'stage', 'chief', 'prior_order')}
    for key in ('chief_route', 'validation_error'):
        if key in payload:
            wire[key] = deepcopy(payload[key])
    if payload.get('required'):
        wire['required'] = deepcopy(payload['required'])
    if task != 'clinical_rank':
        wire['resources'] = fields(payload['resources'], 'turns calls', 'resources')
    # Detailed omission counts are bookkeeping. Preserve their clinical meaning.
    check_fields(payload['input_limits'], 'graph_items omitted_question_options omitted_evidence omitted_questions', 'limits')
    if any(value > 0 for key, value in payload['input_limits'].items() if key.startswith('omitted_')):
        wire['incomplete'] = True
    wire['facts'] = {ref: fields(row, 'status kind target attribute values value measurement category '
        'context_key acquisition reported_by polarity_scope scope', 'fact') for ref, row in payload['facts'].items()}
    wire['candidates'] = []
    used_evidence = set()
    for candidate in payload['candidates']:
        row = fields(candidate, 'ref name supports against unresolved', 'candidate')
        for category in ('supports', 'against', 'unresolved'):
            if row.get(category) == []:
                row.pop(category)
            used_evidence.update(row.get(category, []))
        wire['candidates'].append(row)
    if not used_evidence <= payload['evidence'].keys():
        raise ValueError('clinical_wire_missing_evidence')
    wire['evidence'] = {ref: fields(row, 'level facts relation feature expects context target attribute scope reason', 'evidence')
                        for ref, row in payload['evidence'].items() if ref in used_evidence}
    used_relations = {row['relation'] for row in wire['evidence'].values() if row.get('relation')}
    used_scopes = {row['scope'] for row in wire['facts'].values()}
    used_scopes.update(row['scope'] for row in wire['evidence'].values() if 'scope' in row)
    questions = []
    for question in payload['questions']:
        row = fields(question, 'ref kind target attribute subject member time scope expected_by_disease', 'question')
        scope = payload['scopes'][row['scope']]
        for key in ('subject', 'member', 'time'):
            if row.get(key) != scope.get(key):
                raise ValueError('clinical_wire_question_scope_mismatch')
            row.pop(key, None)
        used_scopes.add(row['scope'])
        groups, group_keys = [], {}
        for disease, entries in row.pop('expected_by_disease').items():
            # Group only identical ENTIRE original entries arrays, including order.
            signature = wire_key(entries)
            if signature not in group_keys:
                group_keys[signature] = len(groups)
                compact_entries = []
                for entry in entries:
                    value = fields(entry, 'relation feature expected collection_only', 'expectation')
                    if 'expected' in value:
                        value['expected'] = compact_expected(value['expected'])
                    if value.get('relation'):
                        used_relations.add(value['relation'])
                    compact_entries.append(value)
                groups.append(dict(diseases=[], entries=compact_entries))
            groups[group_keys[signature]]['diseases'].append(disease)
        row['expected_groups'] = groups
        questions.append(row)
    if task != 'clinical_rank' or questions:
        wire['questions'] = questions
    if not used_scopes <= payload['scopes'].keys() or not used_relations <= payload['relations'].keys():
        raise ValueError('clinical_wire_missing_definition')
    wire['scopes'] = {ref: fields(row, 'subject member time observation episode', 'scope')
                      for ref, row in payload['scopes'].items() if ref in used_scopes}
    wire['patterns'], wire['relations'] = {}, {}
    pattern_keys, used_conditions = {}, set()
    for ref, relation in payload['relations'].items():
        if ref not in used_relations:
            continue
        row = fields(relation, 'target effect rule_scope full_pattern applicability', 'relation')
        pattern = row.pop('full_pattern')
        signature = wire_key(pattern)
        if signature not in pattern_keys:
            pattern_ref = f'p_{len(pattern_keys) + 1}'
            pattern_keys[signature] = pattern_ref
            wire['patterns'][pattern_ref] = [compact_feature(feature) for feature in pattern]
        row['pattern'] = pattern_keys[signature]
        rule_scope = fields(row['rule_scope'], 'subject subject_member time_context', 'rule_scope')
        if rule_scope.get('subject_member') is None:
            rule_scope.pop('subject_member', None)
        row['rule_scope'] = rule_scope
        if row.get('applicability') is None:
            row.pop('applicability', None)  # No prerequisite, distinct from unknown applicability.
        else:
            used_conditions.add(row['applicability'])
        wire['relations'][ref] = row
    if not used_conditions <= payload['conditions'].keys():
        raise ValueError('clinical_wire_missing_condition')
    wire['conditions'] = {}
    for ref, conditions in payload['conditions'].items():
        if ref not in used_conditions:
            continue
        rows = []
        for condition in conditions:
            row = fields(condition, 'target status subject member time', 'condition')
            if row.get('member') is None:
                row.pop('member', None)
            rows.append(row)
        wire['conditions'][ref] = rows
    validate_clinical_references(wire)
    return wire


def validate_clinical_references(wire):
    """Check executable references and feature indices without reinterpreting rules."""
    diseases = {row['ref'] for row in wire['candidates']}
    if not set(wire['prior_order']) <= diseases or wire['chief'] is not None and wire['chief'] not in wire['facts']:
        raise ValueError('clinical_wire_invalid_patient_or_prior_ref')
    def check(row):
        if not set(row.get('facts', [])) <= wire['facts'].keys():
            raise ValueError('clinical_wire_invalid_fact_ref')
        if 'scope' in row and row['scope'] not in wire['scopes']:
            raise ValueError('clinical_wire_invalid_scope_ref')
        if row.get('relation') is not None and row['relation'] not in wire['relations']:
            raise ValueError('clinical_wire_invalid_relation_ref')
        if row.get('feature') is not None:
            relation = wire['relations'].get(row.get('relation'), {})
            pattern = wire['patterns'].get(relation.get('pattern'), [])
            if type(row['feature']) is not int or not 0 <= row['feature'] < len(pattern):
                raise ValueError('clinical_wire_invalid_feature_index')
    for row in [*wire['facts'].values(), *wire['evidence'].values()]:
        check(row)
    question_refs = set()
    for question in wire.get('questions', []):
        check(question)
        if question['ref'] in question_refs:
            raise ValueError('clinical_wire_duplicate_question_ref')
        question_refs.add(question['ref'])
        grouped = set()
        for group in question['expected_groups']:
            if not set(group['diseases']) <= diseases or grouped.intersection(group['diseases']):
                raise ValueError('clinical_wire_invalid_expected_disease_ref')
            grouped.update(group['diseases'])
            for entry in group['entries']:
                check(entry)
