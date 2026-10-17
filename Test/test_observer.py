from contextlib import ExitStack, nullcontext
import copy
from datetime import datetime, timezone
import importlib.util
import itertools
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import UUID

from observe import observing, plain


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = Path(os.environ.get('ONTOWARD_OBSERVER_OUTPUT', ROOT / 'Tmp/test-web31/parity'))
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ['ONTOWARD_TEST_OUTPUT'] = str(OUTPUT / 'fixtures')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


fixture = module('observer_fixtures', ROOT / 'Dev/tests/workflow/test_workflow.py')
comparison = module('observer_scenarios', ROOT / 'Dev/tests/workflow/compare_traces.py')
fixed = datetime(2026, 10, 14, tzinfo=timezone.utc)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return fixed if tz else fixed.replace(tzinfo=None)


def capture(name, options, observed, bad_path=False):
    ids, wire, delays = itertools.count(1), [], []
    with ExitStack() as stack:
        stack.enter_context(patch.object(fixture, 'datetime', FixedDatetime))
        client = fixture.FakeSDK(**options)
        if name == 'closed':
            client.status = 'closed'
        if name == 'expired':
            client.deadline = fixed
        injected = {'transient_model': ('chat', 'REQUEST_PENDING'), 'response_format': ('say', 'PATIENT_RESPONSE_INVALID'),
                    'soap_repair': ('diagnose', 'INVALID_RECORD_FIELDS')}.get(name)
        for method in ('session', 'chat', 'say', 'exam', 'diagnose'):
            original = getattr(client, method)
            def invoke(*args, _method=method, _original=original, **kwargs):
                row = {'method': _method, 'args': copy.deepcopy(args), 'body': copy.deepcopy(kwargs), 'timeout': client.timeout}
                wire.append(row)
                try:
                    if injected and _method == injected[0] and sum(item['method'] == _method for item in wire) == 1:
                        raise fixture.NovaError(injected[1])
                    response = _original(*args, **kwargs)
                    row['response'] = copy.deepcopy(response)
                    return response
                except fixture.NovaError as error:
                    row['error'] = error.code
                    raise
            setattr(client, method, invoke)
        resources = fixture.resources()
        consultation = fixture.assemble_consultation(client, resources, now=lambda: fixed,
            sleep=delays.append, new_request_id=lambda: str(UUID(int=next(ids))))
        trace_path = OUTPUT / (name + ('.missing/trace.jsonl' if bad_path else '.jsonl'))
        if trace_path.exists():
            trace_path.unlink()
        context = observing(trace_path) if observed else nullcontext(None)
        with context as trace:
            if trace:
                trace.knowledge = resources.knowledge
            initial = consultation.nova_session.initialize_case(client)
            graph = fixture.build_graph(consultation, resources.knowledge)
            updates = list(graph.stream(initial.model_dump(), {'recursion_limit': 1400}, stream_mode='updates'))
        result = plain({'initial': initial.model_dump(), 'updates': updates, 'wire': wire, 'delays': delays})
        return result, trace_path


def reconstructed(path):
    state, updates = None, []
    for event in map(json.loads, path.read_text().splitlines()):
        if event['kind'] == 'initial':
            state = event['state']
        for change in event.get('patch', []):
            if not change['path']:
                state = copy.deepcopy(change['value'])
                continue
            parent = state
            for key in change['path'][:-1]:
                parent = parent[key]
            key = change['path'][-1]
            if change['op'] == 'remove':
                del parent[key]
            elif change['op'] == 'add' and isinstance(parent, list):
                parent.insert(key, copy.deepcopy(change['value']))
            else:
                parent[key] = copy.deepcopy(change['value'])
        if event['kind'] == 'node_end':
            updates.append({event['node']: copy.deepcopy(state)})
    return updates


def main():
    results = {}
    normal = None
    for name, options in comparison.SCENARIOS.items():
        baseline, _ = capture(name, options, False)
        observed, path = capture(name, options, True)
        difference = comparison.first_difference(baseline, observed)
        restored = reconstructed(path)
        reconstruction = comparison.first_difference(observed['updates'], restored)
        if difference or reconstruction:
            raise AssertionError((name, difference, reconstruction))
        if name == 'normal':
            normal = baseline
        final = next(iter(observed['updates'][-1].values()))
        results[name] = {'nodes': len(observed['updates']), 'parity': True, 'reconstruction': True,
                         'termination': final['interaction']['termination'], 'diagnosis': final['case']['diagnosis']}
    unavailable, _ = capture('normal', {}, True, bad_path=True)
    assert comparison.first_difference(normal, unavailable) is None

    import nova_sdk
    client = nova_sdk.Client(api_base='http://unused', token='secret-not-for-trace', session_id='local')
    body = {'request_id': 'fixed-request', 'messages': [{'role': 'user', 'content': 'same request'}]}
    path = OUTPUT / 'sdk.jsonl'
    failure = nova_sdk.NovaError('REQUEST_PENDING', 409)
    with patch.object(nova_sdk.Client, '_request', side_effect=[{'ok': True}, failure]) as original:
        with observing(path):
            assert client._request('POST', '/v1/chat/completions', body) == {'ok': True}
            try:
                client._request('POST', '/v1/chat/completions', body)
            except nova_sdk.NovaError as error:
                assert error is failure
            else:
                raise AssertionError('Observer swallowed the original SDK error')
        assert original.call_count == 2
        assert all(call.args[1:] == ('POST', '/v1/chat/completions', body) for call in original.call_args_list)
    assert 'secret-not-for-trace' not in path.read_text()
    report = {'status': 'pass', 'scenarios': results, 'node_updates': sum(row['nodes'] for row in results.values()),
              'logging_failure_preserves_workflow': True, 'sdk_identity_errors_and_single_delegation': True,
              'actual_nova': 'not_run', 'official_api': 'not_run'}
    (OUTPUT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
