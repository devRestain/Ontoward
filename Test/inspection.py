"""Describe recorded execution without importing or rerunning the submission."""
from collections import Counter
from copy import deepcopy
import hashlib
import json


def apply(state, patch):
    for change in patch:
        path = change['path']
        if not path:
            state = deepcopy(change['value'])
            continue
        parent = state
        for key in path[:-1]:
            parent = parent[key]
        key = path[-1]
        if change['op'] == 'remove':
            del parent[key]
        elif change['op'] == 'add' and isinstance(parent, list):
            parent.insert(key, deepcopy(change['value']))
        else:
            parent[key] = deepcopy(change['value'])
    return state


def inspect_run(data):
    events = data['trace']['events']
    settings = next((e for e in events if e['kind'] == 'settings'), {})
    checks, checkpoints, transitions = [], [], Counter()
    counts, methods = Counter(e['kind'] for e in events), Counter()
    def check(ident, value, detail, collected=True):
        checks.append(dict(id=ident, status=('pass' if value else 'fail') if collected else 'not_collected', detail=detail))

    check('event_sequence', [e.get('seq') for e in events] == list(range(1, len(events) + 1)),
          'Require consecutive recorded sequence numbers', bool(events))
    check('trace_boundaries', counts['initial'] == 1 and counts['end'] == 1 and not counts['observation_error']
          and events[-1]['kind'] == 'end' and not data['warnings'],
          'Require initial state, final collector event and no observation or JSON errors', bool(events))
    defined, missing = set(), []
    def references(value, seq):
        if isinstance(value, dict):
            if set(value) == {'trace_value_ref'} and value['trace_value_ref'] not in defined:
                missing.append(seq)
            for item in value.values():
                references(item, seq)
        elif isinstance(value, list):
            for item in value:
                references(item, seq)
    for event in events:
        if event['kind'] == 'value':
            if event['value_id'] in defined:
                missing.append(event['seq'])
            references(event['data'], event['seq'])
            defined.add(event['value_id'])
        else:
            references(event, event.get('seq'))
    check('recorded_values', not missing, dict(values=len(defined), invalid_sequences=missing),
          bool(defined) or any(e.get('format_version', 0) >= 4 for e in events))
    active_calls, call_errors, active_node, node_errors, active_sdk, sdk_errors = [], [], None, [], None, []
    seen_calls, previous = set(), None
    state, state_error, frozen, frozen_changes = None, None, None, []
    modern, unified, freeze_seq, sent = False, False, None, []
    for event in events:
        kind, seq = event['kind'], event.get('seq')
        if kind == 'call_start':
            ident = event.get('call_id')
            if ident in seen_calls or event.get('parent_call_id') != (active_calls[-1] if active_calls else None):
                call_errors.append(seq)
            seen_calls.add(ident)
            active_calls.append(ident)
            methods[f"{event.get('owner')}.{event.get('method')}"] += 1
        elif kind in {'call_end', 'call_error'}:
            if not active_calls or active_calls[-1] != event.get('call_id'):
                call_errors.append(seq)
            else:
                active_calls.pop()
        elif kind == 'node_start':
            if active_node:
                node_errors.append(seq)
            active_node = event.get('node')
            if previous:
                transitions[(previous, active_node)] += 1
            previous = active_node
        elif kind in {'node_end', 'node_error'}:
            if active_node != event.get('node'):
                node_errors.append(seq)
            active_node = None
        elif kind == 'sdk_request':
            if active_sdk:
                sdk_errors.append(seq)
            active_sdk = event
            if (event.get('body') or {}).get('action') == 'DIAGNOSE':
                sent.append(event['body'])
        elif kind in {'sdk_response', 'sdk_error'}:
            if not active_sdk or (active_sdk.get('request_id'), active_sdk.get('path')) != (event.get('request_id'), event.get('path')):
                sdk_errors.append(seq)
            active_sdk = None
        if state_error:
            continue
        try:
            if kind == 'initial':
                state = deepcopy(event['state'])
            elif state is not None and 'patch' in event:
                state = apply(state, event['patch'])
            if state is not None and kind in {'initial', 'node_end'}:
                case = state.get('case', {})
                assessment = case.get('assessment') or {}
                modern = modern or 'assessment' in case
                unified = unified or 'assessment' in case and 'notes' not in case
                primary = (assessment.get('differential') or [{}])[0].get('name')
                patient = {key: case.get(key) for key in ('facts', 'notes', 'chief_fact_id', 'revision', 'assessment')}
                if frozen is not None and patient != frozen:
                    frozen_changes.append(seq)
                if assessment.get('frozen') and frozen is None:
                    frozen, freeze_seq = deepcopy(patient), seq
                checkpoints.append(dict(seq=seq, node=event.get('node'), session=state.get('interview', {}).get('current'),
                    revision=case.get('revision'), assessment_revision=assessment.get('based_on_case_revision'),
                    primary=primary, frozen=assessment.get('frozen'), turn_present=state.get('turn') is not None,
                    fact_count=len(case.get('facts', {})), note_count=len(case.get('notes', {})),
                    unbound_fact_count=sum(not f.get('graph_binding') for f in case.get('facts', {}).values()) if unified else None))
        except (KeyError, IndexError, TypeError, ValueError) as error:
            state_error = dict(seq=seq, error=type(error).__name__)

    check('call_boundaries', not active_calls and not call_errors,
          dict(open=active_calls, invalid_sequences=call_errors), bool(counts['call_start']))
    check('node_boundaries', active_node is None and not node_errors,
          dict(open=active_node, invalid_sequences=node_errors), bool(counts['node_start']))
    check('sdk_boundaries', active_sdk is None and not sdk_errors,
          dict(open=active_sdk.get('seq') if active_sdk else None, invalid_sequences=sdk_errors), bool(counts['sdk_request']))
    check('state_reconstruction', state_error is None, state_error or 'Apply every node patch to the recorded initial state', state is not None)
    edges = {(e['source'], e['target']) for e in settings.get('graph', {}).get('edges', [])}
    invalid_edges = [list(pair) for pair in transitions if pair not in edges]
    check('graph_transitions', not invalid_edges, dict(invalid_edges=invalid_edges), bool(edges))
    execution = settings.get('execution', {})
    operations = set(execution.get('operations', []))
    invalid_operations = [event.get('node') for event in events
                          if event['kind'] == 'node_start' and event.get('node') not in operations]
    check('execution_operations', not invalid_operations, dict(invalid_operations=invalid_operations),
          execution.get('kind') == 'sequential')
    assessment = (frozen or {}).get('assessment') or {}
    primary = (assessment.get('differential') or [{}])[0].get('name')
    check('frozen_patient_state', not frozen_changes, dict(freeze_seq=freeze_seq, changed_at=frozen_changes), frozen is not None)
    check('assessment_revision', assessment.get('based_on_case_revision') == (frozen or {}).get('revision')
          and assessment.get('based_on_chief_fact_id') == (frozen or {}).get('chief_fact_id'),
          'Compare the frozen assessment revision and chief with its recorded facts', frozen is not None)
    check('submission_primary', all(body.get('diagnosis') == primary for body in sent),
          dict(frozen_primary=primary, sent=[body.get('diagnosis') for body in sent]), bool(sent) and frozen is not None)
    record = data['record']
    check('received_soap', bool(sent) and all(sent[-1].get(key) == record.get(key) for key in ('note', 'diagnosis')),
          'Compare final SDK DIAGNOSE fields with the simulator received record', bool(record) and bool(sent))
    check('confirmed_completion', data['summary'].get('status') == 'completed'
          and (data['summary'].get('receipt') or {}).get('status') == 'completed'
          and ((state or {}).get('session', {}).get('termination')
               or (state or {}).get('interaction', {}).get('termination')) == 'submitted',
          'Require both a local completed receipt and submitted workflow state', state is not None and bool(data['summary']))
    return dict(version=1, status='fail' if any(c['status'] == 'fail' for c in checks) else
                'pass' if events and not state_error else 'not_collected',
                runtime=settings.get('runtime'), graph=settings.get('graph'), execution=settings.get('execution'),
                state_layout='D47' if unified else 'D46' if modern else 'legacy_or_unknown', checks=checks,
                event_counts=dict(counts), observed_methods=dict(methods),
                declared_objects=settings.get('objects', []), checkpoints=checkpoints,
                transitions=[dict(source=a, target=b, count=n) for (a, b), n in transitions.items()],
                frozen=dict(seq=freeze_seq, primary=primary,
                    patient_sha256=hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()) if frozen else None,
                limits=dict(scope=settings.get('observation_scope', 'Legacy trace; collector scope was not recorded'),
                    clinical_accuracy='not_evaluated', official_scoring='not_run', inferred_field_reads=False))
