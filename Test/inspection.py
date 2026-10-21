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


def outcome_metrics(state, record, sent, summary):
    """Describe preserved output and actual receipts without synthesizing a record."""
    case, interview, session = ((state or {}).get(key, {}) for key in ('case', 'interview', 'session'))
    payload = session.get('final_payload') or ((state or {}).get('turn') or {}).get('payload')
    if not isinstance(payload, dict) or not isinstance(payload.get('note'), dict):
        payload = {key: record[key] for key in ('note', 'diagnosis') if key in record} if record.get('note') else None
    plans = case.get('plan')
    answers = interview.get('answers')
    delivery = None
    if isinstance(plans, list) and isinstance(answers, list):
        delivery = []
        for sentence in plans:
            rows = [row for row in answers if row.get('plan_sentence_id') == sentence['id']]
            queued = [row for row in interview.get('queue', []) if row.get('plan_sentence_id') == sentence['id']]
            good = sum(row.get('outcome') == 'delivered' for row in rows)
            bad = sum(row.get('outcome') == 'undelivered' for row in rows)
            expected = interview.get('education_utterances', {}).get(sentence['id'])
            delivery.append(dict(id=sentence['id'], delivered_utterances=good, undelivered_utterances=bad,
                pending_utterances=len(queued), expected_utterances=expected,
                status='partial' if good and (bad or queued or expected and good < expected) else
                'delivered' if expected and good == expected and not bad and not queued else
                'undelivered' if bad and not good else 'not_collected'))
    return dict(education_status=interview.get('education_status'), education_reason=interview.get('education_reason'),
        plan_count=len(plans) if isinstance(plans, list) else None,
        diagnosis_announcement_delivered=sum(row.get('outcome') == 'delivered' and row.get('question_id', '').startswith('Education:diagnosis:')
                                            for row in answers) if isinstance(answers, list) else None,
        plan_delivery=delivery, fact_count=len(case['facts']) if isinstance(case.get('facts'), dict) else None,
        unbound_fact_count=sum(not row.get('graph_binding') for row in case['facts'].values())
                          if isinstance(case.get('facts'), dict) and 'notes' not in case else None,
        payload_generated=payload is not None, payload=payload,
        transmitted=bool(sent), received=bool(record.get('note')),
        submission_confirmed=summary.get('status') == 'completed' and (summary.get('receipt') or {}).get('status') == 'completed',
        p_coverage={key: bool(value.strip()) for key, value in payload['note'].get('P', {}).items()} if payload else None,
        clinical_accuracy='not_evaluated')


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
    defined, missing, values = set(), [], {}
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
            values[event['value_id']] = event['data']
        else:
            references(event, event.get('seq'))
    check('recorded_values', not missing, dict(values=len(defined), invalid_sequences=missing),
          bool(defined) or any(e.get('format_version', 0) >= 4 for e in events))
    active_calls, call_errors, active_node, node_errors, active_sdk, sdk_errors = [], [], None, [], None, []
    seen_calls, previous = set(), None
    collaborator_errors, definition_errors = [], []
    pipeline = settings.get('pipeline', {})
    coverage = settings.get('coverage', [])
    current_contract = pipeline.get('version', 0) >= 2
    check('observation_coverage', bool(coverage) and not any(row.get('missing') for row in coverage),
          dict(attachments=coverage), current_contract)
    hashes = (settings.get('runtime') or {}).get('source_sha256', {})
    required_sources = pipeline.get('required_sources', [])
    check('runtime_sources', bool(required_sources) and all(
        isinstance(hashes.get(name), str) and len(hashes[name]) == 64 for name in required_sources),
        dict(required=required_sources, missing=[name for name in required_sources if name not in hashes]), current_contract)
    source_checks = [event for event in events if event['kind'] == 'runtime_check']
    check('runtime_stability', bool(source_checks) and not any(event.get('changed_sources') for event in source_checks),
          dict(checks=source_checks), current_contract)
    def resolve(value, seen=frozenset()):
        if isinstance(value, dict):
            if set(value) == {'trace_value_ref'}:
                key = value['trace_value_ref']
                return resolve(values[key], seen | {key}) if key in values and key not in seen else value
            return {key: resolve(item, seen) for key, item in value.items()}
        return [resolve(item, seen) for item in value] if isinstance(value, list) else value
    object_state, model_calls, model_outcomes = None, {}, []
    budget_fields = ('doctor_calls', 'input_tokens', 'output_tokens', 'models_available', 'budget_sync_required', 'finalizing')
    state, state_error, frozen, frozen_changes = None, None, None, []
    modern, unified, freeze_seq, sent = False, False, None, []
    for event in events:
        kind, seq = event['kind'], event.get('seq')
        if kind == 'call_start':
            ident = event.get('call_id')
            if ident in seen_calls or event.get('parent_call_id') != (active_calls[-1] if active_calls else None):
                call_errors.append(seq)
            seen_calls.add(ident)
            if pipeline:
                location = event.get('definition') or {}
                if not location.get('path') or not isinstance(location.get('line'), int) or location['line'] < 1:
                    definition_errors.append(seq)
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
        if 'owner_state' in event:
            owner = event.get('owner')
            if set(event['owner_state']) - set(pipeline.get('owner_fields', {}).get(owner, ())):
                collaborator_errors.append(seq)
        if state_error:
            continue
        try:
            if 'object_state' in event:
                object_state = deepcopy(event['object_state'])
            elif object_state is not None and 'object_patch' in event:
                object_state = apply(object_state, event['object_patch'])
            if event.get('owner') == 'DoctorBrain' and event.get('method') == 'complete':
                budget = {key: (object_state or {}).get('session', {}).get(key) for key in budget_fields}
                if kind == 'call_start':
                    model_calls[event['call_id']] = dict(seq=seq, role=event.get('inputs', {}).get('role'), before=budget)
                elif kind == 'call_end':
                    result = resolve(event.get('output')) or {}
                    result = result.get('data', {}) if isinstance(result, dict) and result.get('type') == 'ModelResult' else {}
                    error = result.get('error')
                    model_outcomes.append(dict(**model_calls.pop(event['call_id'], dict(seq=seq)),
                        end_seq=seq, error=error, request_id=result.get('request_id'), after=budget,
                        local_education_guard=isinstance(error, str) and error.startswith('LOCAL_EDUCATION_')))
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
                    assessment_response=assessment.get('based_on_response'),
                    assessment_chief=assessment.get('based_on_chief_fact_id'),
                    education_status=state.get('interview', {}).get('education_status'),
                    education_reason=state.get('interview', {}).get('education_reason'),
                    budget={key: state.get('session', {}).get(key) for key in budget_fields},
                    education_delivered=sum(a.get('purpose') == 'education' and a.get('outcome') == 'delivered'
                                            for a in state.get('interview', {}).get('answers', [])),
                    education_undelivered=sum(a.get('purpose') == 'education' and a.get('outcome') == 'undelivered'
                                              for a in state.get('interview', {}).get('answers', [])),
                    plan_count=len(case['plan']) if 'plan' in case else None,
                    primary=primary, frozen=assessment.get('frozen'), turn_present=state.get('turn') is not None,
                    fact_count=len(case['facts']) if 'facts' in case else None,
                    measured_fact_count=sum(bool(f.get('measurement')) for f in case.get('facts', {}).values()),
                    unbound_fact_count=sum(not f.get('graph_binding') for f in case.get('facts', {}).values()) if unified else None))
        except (KeyError, IndexError, TypeError, ValueError) as error:
            state_error = dict(seq=seq, error=type(error).__name__)

    check('call_boundaries', not active_calls and not call_errors,
          dict(open=active_calls, invalid_sequences=call_errors), bool(counts['call_start']))
    check('collaborator_fields', not collaborator_errors,
          dict(invalid_sequences=collaborator_errors, declared=pipeline.get('owner_fields', {})), bool(pipeline))
    check('definition_locations', not definition_errors,
          dict(invalid_sequences=definition_errors), bool(pipeline) and bool(counts['call_start']))
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
                pipeline=pipeline,
                coverage=coverage, model_outcomes=model_outcomes,
                outcome=outcome_metrics(state, record, sent, data['summary']),
                state_layout='D50' if execution.get('kind') == 'sequential' else 'D47' if unified else 'D46' if modern else 'legacy_or_unknown', checks=checks,
                event_counts=dict(counts), observed_methods=dict(methods),
                declared_objects=settings.get('objects', []), checkpoints=checkpoints,
                transitions=[dict(source=a, target=b, count=n) for (a, b), n in transitions.items()],
                frozen=dict(seq=freeze_seq, primary=primary,
                    patient_sha256=hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()) if frozen else None,
                limits=dict(scope=settings.get('observation_scope', 'Legacy trace; collector scope was not recorded'),
                    clinical_accuracy='not_evaluated', official_scoring='not_run', inferred_field_reads=False))
