from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import sys
import time


def plain(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def changes(before, after, path=()):
    if type(before) is not type(after):
        return [{'op': 'replace', 'path': list(path), 'value': after}]
    result = []
    if isinstance(before, dict):
        result.extend({'op': 'remove', 'path': [*path, key]} for key in sorted(before.keys() - after.keys()))
        for key, value in after.items():
            result.extend(changes(before[key], value, (*path, key)) if key in before else
                          [{'op': 'add', 'path': [*path, key], 'value': value}])
    elif isinstance(before, list):
        for index in range(min(len(before), len(after))):
            result.extend(changes(before[index], after[index], (*path, index)))
        result.extend({'op': 'remove', 'path': [*path, index]} for index in range(len(before) - 1, len(after) - 1, -1))
        result.extend({'op': 'add', 'path': [*path, index], 'value': after[index]} for index in range(len(before), len(after)))
    elif before != after:
        result.append({'op': 'replace', 'path': list(path), 'value': after})
    return result


class Trace:
    def __init__(self, path):
        self.path, self.started = Path(path), time.monotonic()
        self.state, self.node, self.knowledge = None, None, None
        self.sequence, self.labels, self.failed = 0, set(), False

    def emit(self, kind, **data):
        # Observation failures must never repeat an action or replace its exception.
        if self.failed:
            return
        try:
            self.sequence += 1
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'seq': self.sequence, 'seconds': round(time.monotonic() - self.started, 6),
                                         'kind': kind, 'node': self.node, **data}, ensure_ascii=False, default=str) + '\n')
        except Exception as error:
            self.failed = True
            print(f'Test observation stopped: {type(error).__name__}', file=sys.stderr)

    def snapshot(self, kind, state):
        try:
            value = plain(state)
            context = {'session': value['session']['current'], 'turn': 50 - value['session']['turns_remaining']}
            if self.state is None:
                self.emit('initial', state=value, **context)
            else:
                patch = changes(self.state, value) if self.state != value else []
                if kind != 'node_input' or patch:
                    self.emit(kind, patch=patch, **context)
            self.state = value
            if self.knowledge:
                labels = {}
                def visit(item):
                    if isinstance(item, dict):
                        for child in item.values():
                            visit(child)
                    elif isinstance(item, list):
                        for child in item:
                            visit(child)
                    elif isinstance(item, str) and item.startswith(('urn:', 'http://', 'https://')) and item not in self.labels:
                        self.labels.add(item)
                        label = self.knowledge.label(item)
                        if label != item:
                            labels[item] = label
                visit(value)
                if labels:
                    self.emit('labels', labels=labels)
        except Exception as error:
            self.emit('observation_error', error=type(error).__name__)


@contextmanager
def observing(path):
    import nova_sdk
    from langgraph.config import get_config
    from workflow import graph, runtime

    trace = Trace(path)
    original_node, original_request = graph.run_node, nova_sdk.Client._request
    original_build, runtime_build = graph.build_graph, runtime.build_graph

    def run_node(state, operation):
        try:
            trace.node = get_config().get('metadata', {}).get('langgraph_node')
        except RuntimeError:
            trace.node = None
        trace.snapshot('node_input', state.model_dump())
        trace.emit('node_start')
        try:
            result = original_node(state, operation)
        except BaseException as error:
            trace.emit('node_error', error=type(error).__name__, message=str(error))
            raise
        trace.snapshot('node_end', result)
        return result

    def build_graph(consultation, knowledge):
        trace.knowledge = knowledge
        trace.emit('settings', education_enabled=consultation.budget.education_enabled)
        return original_build(consultation, knowledge)

    def request(client, method, path, body=None):
        started = time.monotonic()
        trace.emit('sdk_request', method=method, path=path, body=body,
                   request_id=(body or {}).get('request_id'), timeout=client.timeout)
        try:
            response = original_request(client, method, path, body)
        except BaseException as error:
            trace.emit('sdk_error', path=path, request_id=(body or {}).get('request_id'),
                       error=getattr(error, 'code', type(error).__name__), message=str(error),
                       elapsed=round(time.monotonic() - started, 6))
            raise
        trace.emit('sdk_response', path=path, request_id=(body or {}).get('request_id'), response=response,
                   elapsed=round(time.monotonic() - started, 6))
        return response

    graph.run_node, graph.build_graph, runtime.build_graph = run_node, build_graph, build_graph
    nova_sdk.Client._request = request
    trace.emit('start', format_version=1)
    try:
        yield trace
    except BaseException as error:
        trace.emit('end', outcome='exited' if isinstance(error, SystemExit) and not error.code else 'error',
                   error=type(error).__name__, message=str(error))
        raise
    else:
        trace.emit('end', outcome='exited')
    finally:
        graph.run_node, graph.build_graph, runtime.build_graph = original_node, original_build, runtime_build
        nova_sdk.Client._request = original_request


if __name__ == '__main__':
    sys.path.insert(0, '/submission')
    with observing(Path(os.environ.get('NOVA_OUTPUT_DIR', '/output')) / 'trace.jsonl'):
        runpy.run_path('/submission/run.py', run_name='__main__')
