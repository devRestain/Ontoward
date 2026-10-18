from contextlib import contextmanager
from collections import Counter
from dataclasses import fields, is_dataclass
from functools import partial, wraps
import inspect
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
        self.calls, self.stack, self.object_state = 0, [], None
        self.restore, self.objects = [], []
        self.scoring_depth, self.suppressed = 0, Counter()

    def value(self, value):
        if hasattr(value, 'model_dump'):
            return {'type': type(value).__name__, 'data': plain(value.model_dump())}
        if is_dataclass(value) and not isinstance(value, type):
            return {'type': type(value).__name__, 'data': {field.name: self.value(getattr(value, field.name)) for field in fields(value)}}
        if isinstance(value, dict):
            return {str(key): self.value(item) for key, item in value.items()}
        if isinstance(value, (tuple, set, frozenset)):
            return {'type': type(value).__name__, 'data': [self.value(item) for item in value]}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        # Service references must not serialize client credentials or arbitrary __dict__ values.
        return {'type': type(value).__name__, 'reference_only': True}

    def object_snapshot(self, state):
        if state is None:
            return {}
        value = plain(state.model_dump(mode='json'))
        result = {'object_state': value} if self.object_state is None else {'object_patch': changes(self.object_state, value)}
        self.object_state = value
        return result

    def wrap(self, operation, owner, name, object_id):
        signature = inspect.signature(operation)
        @wraps(operation)
        def call(*args, **kwargs):
            if self.failed:
                return operation(*args, **kwargs)
            if self.scoring_depth and owner in {'EvidenceIndex', 'ClinicalKnowledge', 'BudgetPolicy'}:
                self.suppressed[f'{owner}.{name}'] += 1
                return operation(*args, **kwargs)
            self.calls += 1
            call_id, parent, started = self.calls, self.stack[-1] if self.stack else None, time.monotonic()
            state, before = None, None
            try:
                arguments = signature.bind(*args, **kwargs).arguments
                state = next((item for item in arguments.values() if type(item).__name__ == 'WorkflowState'), None)
                before = plain(state.model_dump(mode='json')) if state is not None else None
                inputs = {key: {'type': 'WorkflowState', 'state_reference': True} if item is state and state is not None
                          else self.value(item) for key, item in arguments.items()}
                self.emit('call_start', call_id=call_id, parent_call_id=parent, object_id=object_id,
                          owner=owner, method=name, inputs=inputs, **self.object_snapshot(state))
            except Exception as error:
                self.emit('observation_error', error=type(error).__name__)
            self.stack.append(call_id)
            scoring = owner == 'DoctorBrain' and name == 'replan'
            if scoring:
                self.scoring_depth += 1
            try:
                result = operation(*args, **kwargs)
            except BaseException as error:
                try:
                    after = plain(state.model_dump(mode='json')) if state is not None else None
                    self.emit('call_error', call_id=call_id, owner=owner, method=name,
                              error=type(error).__name__, message=str(error),
                              writes=changes(before, after) if before is not None else [], **self.object_snapshot(state))
                except Exception:
                    pass
                raise
            else:
                try:
                    after = plain(state.model_dump(mode='json')) if state is not None else None
                    arguments_after = {key: {'type': 'WorkflowState', 'state_reference': True} if item is state and state is not None
                                       else self.value(item) for key, item in arguments.items()}
                    argument_writes = changes(inputs, arguments_after)
                    self.emit('call_end', call_id=call_id, owner=owner, method=name, output=self.value(result),
                              writes=changes(before, after) if before is not None else [],
                              argument_writes=argument_writes, **({'arguments_after': arguments_after} if argument_writes else {}),
                              elapsed=round(time.monotonic() - started, 6), **self.object_snapshot(state))
                except Exception as error:
                    self.emit('observation_error', error=type(error).__name__)
                return result
            finally:
                if scoring:
                    self.scoring_depth -= 1
                self.stack.pop()
        return call

    def attach(self, consultation, knowledge):
        selected = {
            'DoctorEar': {'process_input', '_context', '_read_context', '_mapping_payload', '_map_batch',
                                 '_parse_text', '_apply_facts', '_fit_request', '_validate_facts'},

            'DoctorBrain': {'prepare_initiation', 'prepare_chief_complaint', 'prepare_open_inquiry',
                                 'prepare_clarification', 'replan', 'prepare_context_questions',
                                 'prepare_differential_questions', 'prepare_education', 'select_question', 'refresh_assessment', 'decide', '_payload', 'close_differential'},
            'BudgetPolicy': {'evaluate', 'can_start_action', 'can_empathize', 'model_allowance'},
            'ClinicalKnowledge': {'search_concepts', 'resolve_concept', 'get_symptom_attributes', 'concepts',
                                  'get_target_values', 'get_exam_methods'},
        }
        seen = set()
        def visit(obj, path):
            if id(obj) in seen:
                return
            seen.add(id(obj))
            owner, methods = type(obj).__name__, []
            for name in vars(type(obj)):
                if name not in selected.get(owner, {name} if not name.startswith('_') else set()):
                    continue
                operation = getattr(obj, name)
                if not callable(operation) or inspect.isclass(operation):
                    continue
                previous = vars(obj).get(name)
                had_value = name in vars(obj)
                setattr(obj, name, self.wrap(operation, owner, name, path))
                self.restore.append((obj, name, previous, had_value))
                methods.append(name)
            self.objects.append({'id': path, 'type': owner, 'methods': methods})
            for name in ('ear', 'brain', 'mouth', 'writer', 'nova_session', 'budget',
                         'questions', 'interactions', 'model', 'executor', 'usage'):
                child = getattr(obj, name, None)
                if child is not None and type(child).__module__.startswith('workflow.'):
                    visit(child, f'{path}.{name}')
        visit(consultation, 'consultation')
        visit(knowledge, 'knowledge')
        from workflow.state.evidence import EvidenceIndex
        for cls, names in ((EvidenceIndex, ('from_case',)),):
            for name in names:
                original = vars(cls)[name]
                operation = original.__func__ if isinstance(original, classmethod) else original
                wrapper = self.wrap(operation, cls.__name__, name, cls.__name__)
                setattr(cls, name, classmethod(wrapper) if isinstance(original, classmethod) else wrapper)
                self.restore.append((cls, name, original, True))
            self.objects.append({'id': cls.__name__, 'type': cls.__name__, 'methods': list(names)})

    def detach(self):
        for obj, name, previous, had_value in reversed(self.restore):
            if had_value:
                setattr(obj, name, previous)
            else:
                delattr(obj, name)
        self.restore.clear()

    def emit(self, kind, **data):
        # Observation failures must never repeat an action or replace its exception.
        if self.failed:
            return
        try:
            self.sequence += 1
            current = self.object_state if kind.startswith(('call_', 'sdk_')) else self.state
            session = (current or {}).get('session', {})
            context = {'session': (current or {}).get('interview', {}).get('current', session.get('current')), 'turn': 50 - session['turns_remaining']} if 'turns_remaining' in session else {}
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'seq': self.sequence, 'seconds': round(time.monotonic() - self.started, 6),
                                         'kind': kind, 'node': self.node, **context, **data}, ensure_ascii=False, default=str) + '\n')
        except Exception as error:
            self.failed = True
            print(f'Test observation stopped: {type(error).__name__}', file=sys.stderr)

    def snapshot(self, kind, state, **metadata):
        try:
            value = plain(state)
            context = {'session': value.get('interview', {}).get('current', value['session'].get('current')), 'turn': 50 - value['session']['turns_remaining']}
            if self.state is None:
                self.emit('initial', state=value, **context, **metadata)
            else:
                patch = changes(self.state, value) if self.state != value else []
                if kind != 'node_input' or patch:
                    self.emit(kind, patch=patch, **context, **metadata)
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
        trace.suppressed.clear()
        try:
            trace.node = get_config().get('metadata', {}).get('langgraph_node')
        except RuntimeError:
            trace.node = None
        trace.snapshot('node_input', state.model_dump(mode='json'))
        target = operation.func if isinstance(operation, partial) else operation
        trace.emit('node_start', operation=getattr(target, '__qualname__', str(type(target).__name__)))
        try:
            result = original_node(state, operation)
        except BaseException as error:
            trace.emit('node_error', error=type(error).__name__, message=str(error))
            raise
        trace.snapshot('node_end', result, suppressed_calls=dict(trace.suppressed))
        return result

    def build_graph(consultation, knowledge):
        trace.knowledge = knowledge
        try:
            trace.attach(consultation, knowledge)
        except Exception as error:
            trace.emit('observation_error', error=type(error).__name__)
        from workflow.state.models import WorkflowState
        trace.emit('settings', education_enabled=consultation.budget.education_enabled, objects=trace.objects,
                   state_schema=WorkflowState.model_json_schema(),
                   observation_scope='Case collaborators, parser stages, dictionary lookups, state writes and SDK bodies; exclude Python heap and inner hypothetical scoring loops')
        return original_build(consultation, knowledge)

    def request(client, method, path, body=None):
        started = time.monotonic()
        trace.emit('sdk_request', method=method, path=path, body=body,
                   request_id=(body or {}).get('request_id'), timeout=client.timeout,
                   parent_call_id=trace.stack[-1] if trace.stack else None)
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
    trace.emit('start', format_version=2)
    try:
        yield trace
    except BaseException as error:
        trace.emit('end', outcome='exited' if isinstance(error, SystemExit) and not error.code else 'error',
                   error=type(error).__name__, message=str(error))
        raise
    else:
        trace.emit('end', outcome='exited')
    finally:
        trace.detach()
        graph.run_node, graph.build_graph, runtime.build_graph = original_node, original_build, runtime_build
        nova_sdk.Client._request = original_request


if __name__ == '__main__':
    sys.path.insert(0, '/submission')
    with observing(Path(os.environ.get('NOVA_OUTPUT_DIR', '/output')) / 'trace.jsonl'):
        runpy.run_path('/submission/run.py', run_name='__main__')
