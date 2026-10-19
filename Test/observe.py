from contextlib import contextmanager
from collections import Counter
from dataclasses import fields, is_dataclass
from functools import partial, wraps
import inspect
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time

from pipeline import OWNER_FIELDS, metadata as pipeline_metadata


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
        self.decision_depth, self.suppressed = 0, Counter()
        self.evidence_seen = set()
        self.values = {}

    def value(self, value):
        result = self._value(value)
        if isinstance(result, (dict, list)):
            packed = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if len(packed) > 2048:
                ident = hashlib.sha256(packed.encode()).hexdigest()
                if ident not in self.values:
                    self.values[ident] = result
                    self.emit('value', value_id=ident, data=result)
                return {'trace_value_ref': ident}
        return result

    def _value(self, value):
        if hasattr(value, 'model_dump'):
            return {'type': type(value).__name__, 'data': self.value(plain(value.model_dump()))}
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

    def expanded(self, value):
        if isinstance(value, dict):
            if set(value) == {'trace_value_ref'}:
                return self.expanded(self.values[value['trace_value_ref']])
            return {key: self.expanded(item) for key, item in value.items()}
        return [self.expanded(item) for item in value] if isinstance(value, list) else value

    def object_snapshot(self, state):
        if state is None:
            return {}
        value = plain(state.model_dump(mode='json'))
        result = {'object_state': value} if self.object_state is None else {'object_patch': changes(self.object_state, value)}
        self.object_state = value
        return result

    def wrap(self, operation, owner, name, object_id, *, call_kind='method'):
        signature = inspect.signature(operation)
        instance = getattr(operation, '__self__', None)
        def owner_state():
            return {field: self.value(getattr(instance, field)) for field in OWNER_FIELDS.get(owner, ())
                    if instance is not None and hasattr(instance, field)}
        try:
            defined = inspect.unwrap(operation)
            source = inspect.getsourcefile(defined)
            definition = dict(path=source[source.rfind('/workflow/') + 1:] if source and '/workflow/' in source else source,
                              line=inspect.getsourcelines(defined)[1]) if source else None
        except (OSError, TypeError):
            definition = None
        @wraps(operation)
        def call(*args, **kwargs):
            if self.failed:
                return operation(*args, **kwargs)
            evidence_key = None
            if owner == 'EvidenceIndex' and name == 'from_case':
                case = kwargs.get('case') or next((arg for arg in args if type(arg).__name__ == 'CaseState'), None)
                evidence_key = (getattr(case, 'revision', None), getattr(case, 'chief_fact_id', None))
            repeated = owner == 'EvidenceIndex' and evidence_key in self.evidence_seen
            if self.decision_depth and (owner in {'ClinicalKnowledge', 'BudgetPolicy'} or repeated):
                self.suppressed[f'{owner}.{name}'] += 1
                return operation(*args, **kwargs)
            if evidence_key is not None:
                self.evidence_seen.add(evidence_key)
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
                          owner=owner, method=name, call_kind=call_kind,
                          callable=f'{operation.__module__}.{operation.__qualname__}',
                          definition=definition, owner_state=owner_state(),
                          inputs=inputs, **self.object_snapshot(state))
            except Exception as error:
                self.emit('observation_error', error=type(error).__name__)
            self.stack.append(call_id)
            deciding = (owner.endswith('Session') and name in {'prepare', 'prepare_decision', 'decide', 'close'}) or owner == 'QuestionTools'
            if deciding:
                self.decision_depth += 1
            try:
                result = operation(*args, **kwargs)
            except BaseException as error:
                try:
                    after = plain(state.model_dump(mode='json')) if state is not None else None
                    self.emit('call_error', call_id=call_id, owner=owner, method=name,
                              error=type(error).__name__, message=str(error),
                              owner_state=owner_state(),
                              writes=changes(before, after) if before is not None else [], **self.object_snapshot(state))
                except Exception:
                    pass
                raise
            else:
                try:
                    after = plain(state.model_dump(mode='json')) if state is not None else None
                    arguments_after = {key: {'type': 'WorkflowState', 'state_reference': True} if item is state and state is not None
                                       else self.value(item) for key, item in arguments.items()}
                    argument_writes = changes(self.expanded(inputs), self.expanded(arguments_after))
                    self.emit('call_end', call_id=call_id, owner=owner, method=name, output=self.value(result),
                              owner_state=owner_state(),
                              writes=changes(before, after) if before is not None else [],
                              argument_writes=argument_writes, **({'arguments_after': arguments_after} if argument_writes else {}),
                              elapsed=round(time.monotonic() - started, 6), **self.object_snapshot(state))
                except Exception as error:
                    self.emit('observation_error', error=type(error).__name__)
                return result
            finally:
                if deciding:
                    self.decision_depth -= 1
                self.stack.pop()
        return call

    def attach(self, consultation, knowledge):
        selected = {
            'Consultation': {'enter_session', 'prepare_session', 'refresh_requirements', 'refresh_after_input',
                             'close_collection', 'check_budget', 'select_action', 'advance_session',
                             'finalize', 'repair_submission', 'release'},
            'DoctorEar': {'process_input', 'record_delivery', '_context', '_read_context', '_project_context',
                          '_mapping_payload', '_map_batch', '_parse_text', '_demographic_facts', '_fixed_reply'},
            'DoctorBrain': {'complete'},
            'DoctorMouth': {'_render', 'render_diagnosis', 'render_education', 'prepare_empathy',
                            'validate_action', 'execute_action'},
            'QuestionTools': {'_spec', '_question', '_register', '_options', 'chief_statuses',
                              'prepare_clarification', 'select_question'},
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
                         'questions', 'interactions', 'model', 'executor', 'usage', 'tools'):
                child = getattr(obj, name, None)
                if child is not None and type(child).__module__.startswith('workflow.'):
                    visit(child, f'{path}.{name}')
            for name, child in getattr(obj, 'sessions', {}).items():
                visit(child, f'{path}.sessions.{name}')
        visit(consultation, 'consultation')
        visit(knowledge, 'knowledge')
        # Wrap the symbols actually called by Ear/Brain, rather than altering the rules globally.
        from workflow import doctor_ear, education as plan
        from workflow.rules import decision
        from workflow.sessions import initiation, chief_complaint, context_factor, differential_diagnosis, education
        boundaries = ((doctor_ear, 'InputBinding', ('candidate_contracts', 'exact_mapping', 'validate_mapping',
                      'force_mapping', 'make_fact', 'note_fact')),
                      (decision, 'GraphEvidence', ('graph_candidates',)),
                      (education, 'EnglishPlan', ('generate_plan',)),
                      (plan, 'EnglishPlan', ('parse_plan', 'references')),
                      *((module, 'ClinicalInput', ('prepare_decision',)) for module in
                        (initiation, chief_complaint, context_factor, differential_diagnosis)))
        for module, owner, names in boundaries:
            for name in names:
                original = getattr(module, name, None)
                if original is None:
                    continue
                setattr(module, name, self.wrap(original, owner, name, f'{module.__name__}.{name}', call_kind='function'))
                self.restore.append((module, name, original, True))
                self.objects.append({'id': f'{module.__name__}.{name}', 'type': 'function', 'owner': owner,
                                     'callable': f'{original.__module__}.{original.__qualname__}', 'methods': [name]})
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
    from workflow.consultation import Consultation
    from execution import BOUNDARIES, observing_operations

    trace = Trace(path)
    original_run, original_request = Consultation.run, nova_sdk.Client._request

    def run(consultation, state):
        trace.knowledge = consultation.knowledge
        try:
            trace.attach(consultation, consultation.knowledge)
            from settings import configured_path, prompt_paths
            from workflow.state.models import WorkflowState
            root = Path(inspect.getfile(WorkflowState)).resolve().parents[2]
            manifest = configured_path('ONTOWARD_PROMPTS', 'config')
            modules = prompt_paths(manifest)
            sources = {file.relative_to(root).as_posix() for file in (root / 'workflow').rglob('*.py')}
            sources.update({'.env', 'settings.py', 'requirements.txt', manifest.relative_to(root).as_posix()})
            if (root / 'knowledge/manifest.json').is_file():
                sources.add('knowledge/manifest.json')
            sources.update(file.relative_to(root).as_posix() for parts in modules.values() for file in parts)
            trace.emit('settings', education_enabled=consultation.budget.education_enabled, objects=trace.objects,
                pipeline=pipeline_metadata(),
                state_schema=WorkflowState.model_json_schema(),
                runtime={'algorithm': __import__('settings').ALGORITHM_VERSION,
                    'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'test_source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                          for name in ('observe.py', 'execution.py', 'pipeline.py')},
                    'source_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(sources)},
                    'prompt_routes': {route: [file.relative_to(root).as_posix() for file in parts]
                                      for route, parts in modules.items()}},
                execution={'kind': 'sequential', 'callable': 'workflow.consultation.Consultation.run',
                    'operations': ['process_initial_input', *[name for _, name in BOUNDARIES]]},
                observation_scope='Actual consultation and collaborator operation boundaries, model exchanges, state writes and SDK bodies; exclude Python heap and repeated inner dictionary and affordability lookups')
        except Exception as error:
            trace.emit('observation_error', error=type(error).__name__)

        def boundary(kind, name, current, error):
            trace.node = name
            if kind == 'start':
                trace.suppressed.clear()
                trace.evidence_seen.clear()
                trace.snapshot('node_input', current.model_dump(mode='json'))
                trace.emit('node_start', operation=name)
            elif kind == 'error':
                trace.snapshot('node_error', current.model_dump(mode='json'),
                               error=type(error).__name__, message=str(error))
            else:
                trace.snapshot('node_end', current.model_dump(mode='json'), suppressed_calls=dict(trace.suppressed))
        with observing_operations(consultation, boundary):
            return original_run(consultation, state)

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

    Consultation.run, nova_sdk.Client._request = run, request
    trace.emit('start', format_version=6)
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
        Consultation.run, nova_sdk.Client._request = original_run, original_request


if __name__ == '__main__':
    sys.path.insert(0, '/submission')
    with observing(Path(os.environ.get('NOVA_OUTPUT_DIR', '/output')) / 'trace.jsonl'):
        runpy.run_path('/submission/run.py', run_name='__main__')
