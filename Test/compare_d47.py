"""Compare preserved C03 accepted states and requests without external model calls."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

from inspection import apply


def compare(run, output, submission):
    os.environ['ONTOWARD_TEST_SUBMISSION'] = str(submission.resolve())
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'Dev/tests/workflow'))
    import fixtures as f
    from workflow.model_context import messages
    from workflow.rules.decision import clinical_messages
    from workflow.state.models import Assessment, CaseFact, CaseState, WorkflowState
    resources = f.prepare()
    state, selected = None, []
    for line in (run / 'agent/trace.jsonl').open():
        event = json.loads(line)
        if event['kind'] == 'initial':
            state = deepcopy(event['state'])
        elif state is not None and 'patch' in event:
            state = apply(state, event['patch'])
        if event['kind'] != 'sdk_request':
            continue
        body = event.get('body') or {}
        if 'messages' not in body:
            continue
        payload = f.decode_context(body['messages'][-1]['content'])
        if payload.get('task') == 'clinical_decision':
            selected.append((deepcopy(state), body))
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for index, (raw, request) in enumerate(selected):
        old_payload = f.decode_context(request['messages'][-1]['content'])
        old_counts = dict(graph_facts=len(raw['case']['facts']), separate_notes=len(raw['case']['notes']),
            transmitted_facts=len(old_payload['facts']))
        facts = []
        for row in raw['case']['facts'].values():
            facts.append(f.graph_fact(**row))
        for row in raw['case']['notes'].values():
            matches = [fact for fact in facts if fact.polarity_scope == 'qualified' and fact.observation_id
                and (fact.subject, fact.subject_member, fact.observation_id, fact.episode_id, fact.time_context) ==
                    (row['subject'], row['subject_member'], row['observation_id'], row['episode_id'], row['time_context'])]
            if len(matches) == 1:
                facts[facts.index(matches[0])] = matches[0].model_copy(update={'value': row['value']})
            else:
                facts.append(CaseFact.model_validate(row))
        case = CaseState(facts={fact.id: fact for fact in facts},
            chief_fact_id=raw['case']['chief_fact_id'], revision=raw['case']['revision'],
            assessment=Assessment.model_validate(raw['case']['assessment']) if raw['case']['assessment'] else None)
        raw['case'] = case.model_dump(mode='json')
        state = WorkflowState.model_validate(raw)
        state.session.deadline = f.FIXED + f.timedelta(minutes=25)
        c = f.consultation(prepared=resources)
        work = c.sessions['Initiation'].prepare_decision(state)
        current = clinical_messages(resources.config, work)
        prior = {entry.name for entry in case.assessment.differential} if case.assessment else set()
        supplied = {row['name'] for row in work.payload['candidates']}
        assert prior <= supplied, prior - supplied
        assert len(work.payload['facts']) == len(case.current_facts())
        for fact in case.current_facts():
            if fact.value:
                assert fact.value in str(work.payload['facts']), fact.value
        rows = {fact.context_key: fact for fact in case.current_facts() if fact.context_key}
        assert rows['age'].measurement.value == 6 and rows['sex'].value == 'male'
        assert rows['reporter'].value == 'mother' if 'reporter' in rows else any(fact.reported_by == 'mother' for fact in facts)
        from workflow.state.evidence import patient_payload
        plan_context = patient_payload(case)
        assert any(row.get('context_key') == 'age' for row in plan_context['facts'])
        assert any(row.get('measurement', {}).get('unit') in {'cm', 'kg'} for row in plan_context['facts'])
        (output / f'context-{index}.txt').write_text(current[-1]['content'] + '\n')
        cases.append(dict(revision=case.revision, stored_facts=len(case.facts), transmitted_facts=len(work.payload['facts']),
            prior_candidates=len(prior), supplied_candidates=len(supplied), all_prior_retained=True, before=old_counts))
        age = rows['age']
        before = case.revision
        case.apply([age.model_copy(update={'value': '7 years', 'measurement': f.ObservedNumber(kind='quantity', value=7, unit='year')})])
        assert case.revision == before + 1
    assert len(cases) == 4
    fixture, completed, _ = f.run(prepared=f.resources(education=True))
    clinical = [row for row in fixture.client.requests if row['task'].startswith('clinical_')]
    schedule = [dict(stage=row['stage'], task=row['task']) for row in clinical]
    assert schedule[:3] == [dict(stage=stage, task='clinical_rank')
        for stage in ('Initiation', 'ChiefComplaint', 'ContextFactor')]
    assert all(sum(row['stage'] == stage for row in schedule) == 1
        for stage in ('Initiation', 'ChiefComplaint', 'ContextFactor'))
    dd_answers = sum(a.scope == 'DifferentialDiagnosis' and a.purpose != 'empathy' for a in completed.interview.answers)
    assert sum(row['task'] == 'clinical_decision' for row in clinical) == dd_answers
    c, state = f.consultation(), f.state()
    calls, delays = [], []
    def unavailable(**request):
        calls.append(deepcopy(request))
        raise f.NovaError('PROVIDER_UNAVAILABLE')
    c.client.chat = unavailable
    c.brain.executor.sleep = delays.append
    result = c.brain.complete(state, c.client, role='education_doctor', messages=messages('render', {'task': 'education_doctor'}))
    assert result.error == 'PROVIDER_UNAVAILABLE' and state.session.termination == 'unknown'
    assert len(calls) == 2 and calls[0] == calls[1] and delays == [2]
    assert state.session.doctor_calls == 1
    report = dict(status='pass', cases=cases, provider_failure_replayed=True, external_calls=0,
        saved_clinical_stages=[raw['interview']['current'] for raw, _ in selected],
        new_schedule=dict(fixture='synthetic_workflow_not_a_fresh_C03_model_run', requests=schedule,
            dd_replies=dd_answers, termination=completed.session.termination),
        source_run=str(run), source_result_sha256=hashlib.sha256((run / 'result.json').read_bytes()).hexdigest(),
        actual_model_quality='not_run', latency_improvement='not_run', official_scoring='not_run')
    (output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--submission', type=Path, default=Path('/workspace/submission'))
    args = parser.parse_args()
    compare(args.run, args.output, args.submission)
