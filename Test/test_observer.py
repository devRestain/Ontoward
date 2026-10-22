"""Compare observed and unobserved sequential execution and reconstruct each operation."""
from contextlib import nullcontext
import copy
import json
import hashlib
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,os.environ.get('ONTOWARD_WORKFLOW_FIXTURES',str(ROOT/'Dev/tests/workflow')))
import fixtures as f
from observe import observing, plain
from inspection import inspect_run
from execution import observing_operations
from workflow.state.models import WorkflowState

OUTPUT=Path(os.environ.get('ONTOWARD_OBSERVER_OUTPUT',ROOT/'Tmp/d44-observer'))


def capture(name,observed):
    client=f.FakeSDK(context='absent' if name=='negative_context' else 'unknown' if name=='unknown_context' else 'present')
    if name in {'education_repair', 'education_passages', 'education_context', 'education_doctor_context'}:
        from education_fixtures import education_response
        def response(payload):
            if payload['task'] == 'education':
                if name == 'education_context' and payload['phase'] == 'repair':
                    raise f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400)
                raw = education_response(payload)
                if name == 'education_passages' and 'tests' in raw['P']:
                    raw['P']['tests'][0].update(basis='guideline',
                        references=[dict(document_id='observer-source', quote='Seek care promptly.')])
                elif name == 'education_repair' and 'treatment' in raw['P']:
                    raw['P']['treatment'][0]['utterances'] = ['가' * 31]
                else:
                    for field, rows in raw['P'].items():
                        if field != 'tests':
                            rows[0]['utterances'] = ['가' * 31]
                    if name == 'education_context' and 'treatment' in raw['P']:
                        raw['P']['treatment'] = 'invalid rows'
                return raw
            if name in {'education_context', 'education_doctor_context'} and payload['task'] == 'education_doctor':
                raise f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400)
        client.chat_handler = response
    if name == 'fixed_unknown':
        original_action = client._action
        def unknown(*args):
            return {**original_action(*args), 'content': '모르겠습니다'}
        client._action = unknown
    c=f.consultation(client,prepared=f.resources(education=name.startswith('education')))
    corpus = OUTPUT / 'guideline-corpus'
    if name == 'education_passages':
        from knowledge.guidelines import GuidelineLibrary
        corpus.mkdir(exist_ok=True)
        raw = b'# Management\nSimulation introduction.\n## Warning\nSeek care promptly.\n## Treatment\nReview options.\n'
        (corpus / 'source.md').write_bytes(raw)
        source = dict(document_id='observer-source', path='source.md', sha256=hashlib.sha256(raw).hexdigest(),
                      relation='exact', evidence_use='care_navigation', scope='Synthetic protocol source')
        c.knowledge.guidelines = GuidelineLibrary({str(f.OW.Alpha): [source], str(f.OW.Beta): [source]})
    if name=='closed':
        client.status='closed'
    if name=='expired':
        client.deadline=f.FIXED
    if name=='malformed_context':
        client.chat=lambda **kw:client.completion('{')
    if name=='model_limit':
        client.chat=lambda **kw:(_ for _ in ()).throw(f.NovaError('MODEL_CALL_LIMIT'))
    if name=='unconfirmed':
        client.diagnose=lambda **kw:{'status':'pending'}
    injected={'transient_model':('chat','REQUEST_PENDING'), 'soap_repair':('diagnose','INVALID_RECORD_FIELDS'),
              'action_format':('say','PATIENT_RESPONSE_INVALID'), 'refusal':('say','EXAM_NOT_RECOGNIZED')}.get(name)
    wire=[]
    for method in ('session','chat','say','exam','diagnose'):
        original=getattr(client,method)
        def invoke(*args,_method=method,_original=original,**kwargs):
            wire.append({'method':_method,'args':copy.deepcopy(args),'body':copy.deepcopy(kwargs)})
            if injected and _method==injected[0] and sum(r['method']==_method for r in wire)==1:
                raise f.NovaError(injected[1])
            return _original(*args,**kwargs)
        setattr(client,method,invoke)
    path=OUTPUT/(name+'.missing/trace.jsonl' if name=='recording_failure' else name+'.jsonl')
    if path.is_file():
        path.unlink()
    context=observing(path) if observed else nullcontext()
    environment = patch.dict(os.environ, {'NOVA_GUIDELINES_DIR': str(corpus)}) if name == 'education_passages' else nullcontext()
    original_read, reads = Path.read_bytes, []
    def drift(file):
        raw = original_read(file)
        if file.as_posix().endswith('/knowledge/guideline_passages.py'):
            reads.append(file)
            if len(reads) > 1:
                return raw + b'\n# Simulated concurrent source change\n'
        return raw
    source_guard = patch.object(Path, 'read_bytes', drift) if name == 'source_drift' else nullcontext()
    with environment, source_guard, context:
        initial=c.nova_session.initialize_case(client)
        if name in {'education_context', 'education_doctor_context'}:
            initial = f.chief(f.state())
            f.freeze_for_education(c, initial)
        initial_raw=initial.model_dump(mode='json')
        updates=[]
        def capture_update(kind, name, state, error):
            if kind == 'end':
                updates.append({name:state.model_dump(mode='json')})
        with observing_operations(c,capture_update):
            c.run(initial)
    return plain({'initial':initial_raw,'updates':updates,'wire':wire}),path


def apply(state,change):
    if not change['path']:
        return copy.deepcopy(change['value'])
    parent=state
    for key in change['path'][:-1]:
        parent=parent[key]
    key=change['path'][-1]
    if change['op']=='remove':
        if isinstance(parent,list):
            parent.pop(key)
        else:
            del parent[key]
    elif change['op']=='add' and isinstance(parent,list):
        parent.insert(key,copy.deepcopy(change['value']))
    else:
        parent[key]=copy.deepcopy(change['value'])
    return state


def verify_trace(rows, name):
    inspection = inspect_run(dict(trace={'events': rows}, warnings=[], summary={}, record={}))
    failed = [c['id'] for c in inspection['checks'] if c['status']=='fail']
    assert failed == (['runtime_stability'] if name == 'source_drift' else []), (name, inspection['checks'])
    current = objects = None
    for row in rows:
        if row['kind']=='initial':
            current=copy.deepcopy(row['state'])
        for change in row.get('patch', []):
            current=apply(current, change)
        if 'object_state' in row:
            objects=copy.deepcopy(row['object_state'])
        for change in row.get('object_patch', []):
            objects=apply(objects, change)
        if row['kind']=='node_end' and objects is not None:
            assert objects==current,(name,row['seq'],'object/node snapshots disagree')
    if name=='normal':
        runtime = next(r['runtime'] for r in rows if r['kind'] == 'settings')
        assert 'config/prompts.json' in runtime['source_sha256']
        assert 'config/prompts/input_initial.txt' in runtime['source_sha256']
        assert 'config/prompts/input_initial.txt' in runtime['prompt_routes']['input.initial']
        assert 'config/prompts/input_initial.txt' not in runtime['prompt_routes']['input.reply']
        settings = next(r for r in rows if r['kind'] == 'settings')
        assert settings['pipeline']['contract'] == 'D68'
        assert settings['pipeline']['input_metrics'] == 'D68'
        outcomes = inspection['model_outcomes']
        assert outcomes and all(row.get('input_metrics') for row in outcomes)
        assert all(row['reported_prompt_tokens'] == 20 and row['error_origin'] is None for row in outcomes)
        assert rows[0]['format_version'] == 7
        assert not any(row['missing'] for row in settings['coverage'])
        assert all(name in runtime['source_sha256'] for name in
                   ('run.py', 'nova_sdk.py', 'knowledge/guidelines.py', 'knowledge/guideline_passages.py'))
        assert set(runtime['test_source_sha256']) == {'observe.py', 'execution.py', 'pipeline.py'}
        for owner, field in [('BudgetPolicy', 'required_counts'), ('ContextFactorSession', 'candidate_ids'),
                             ('DifferentialDiagnosisSession', 'last_input')]:
            assert any(r['kind'] == 'call_start' and r['owner'] == owner and field in r['owner_state'] for r in rows), (owner, field)
        for owner, method in [('InputBinding','exact_mapping'),('InputBinding','make_fact'),
                              ('GraphEvidence','graph_candidates'),('InitiationSession','prepare_decision'),
                              ('DoctorBrain','complete'), ('EvidenceIndex', 'from_case')]:
            calls={r['call_id'] for r in rows if r['kind']=='call_start' and (r['owner'],r['method'])==(owner,method)}
            assert any(r['kind']=='call_end' and r['call_id'] in calls and r.get('output') is not None for r in rows),(owner,method)
    if name == 'education_repair':
        assert any(r['kind'] == 'call_start' and r['owner'] == 'EnglishPlan' and r['method'] == 'parse_plan' for r in rows)
        assert any(r['kind'] == 'call_start' and r['owner'] == 'DoctorMouth' and r['method'] == '_render' for r in rows)
        assert any(r['kind'] == 'call_end' and r['owner'] == 'EducationSession' and r['owner_state'].get('generated_utterances') for r in rows)
        assert any(r['kind'] == 'call_start' and r['owner'] == 'DoctorBrain' and r['inputs'].get('role') == 'education_doctor' for r in rows)
    if name == 'fixed_unknown':
        assert any(r['kind'] == 'call_end' and r['owner'] == 'DoctorEar' and r['method'] == '_fixed_reply' and r['output'] is not None for r in rows)
    if name == 'education_passages':
        for owner, method in [('GuidelineLibrary', 'read'), ('GuidelineEvidence', 'pack_passages'),
                              ('GuidelineEvidence', 'project_documents'), ('GuidelineEvidence', 'source_contexts'),
                              ('ModelProjection', 'fixed_case_payload'), ('EnglishPlan', 'references')]:
            assert any(r['kind'] == 'call_end' and (r['owner'], r['method']) == (owner, method) for r in rows), (owner, method)
        assert any(r['kind'] == 'call_start' and (r.get('definition') or {}).get('path') == 'knowledge/guidelines.py' for r in rows)
    if name in {'education_context', 'education_doctor_context'}:
        errors = [row for row in inspection['model_outcomes'] if row['error'] == 'CONTEXT_LIMIT_EXCEEDED']
        assert len(errors) == 1 and errors[0]['request_id'], (name, errors)
        assert errors[0]['error_origin'] == 'client_or_server'
        assert errors[0]['after']['budget_sync_required']
        if name == 'education_context':
            guards = [row for row in inspection['model_outcomes'] if row['local_education_guard']]
            assert guards and all(row['request_id'] is None and row['before'] == row['after'] for row in guards)
            assert all(row['error_origin'] == 'local_preflight' and row['input_metrics'] for row in guards)
        assert any(r['kind'] == 'call_end' and r.get('owner') == 'NovaSessionClient' and r.get('method') == 'refresh_snapshot' for r in rows)
        assert inspection['checkpoints'][-1]['education_undelivered'] > 0
    return inspection


def verify():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    scenarios=[]
    for name in ('normal','negative_context','unknown_context','fixed_unknown','education','education_repair',
                 'education_passages','education_context','education_doctor_context','source_drift','transient_model','model_limit',
                 'malformed_context','expired','closed','soap_repair','unconfirmed','refusal','action_format','recording_failure'):
        baseline,_=capture(name,False)
        observed,path=capture(name,True)
        assert baseline==observed,name
        end=WorkflowState.model_validate(next(iter(observed['updates'][-1].values())))
        if name in {'normal','education','education_repair','education_passages','education_context','education_doctor_context',
                    'fixed_unknown','negative_context','unknown_context','soap_repair','refusal','action_format','source_drift','transient_model','recording_failure'}:
            assert end.session.termination=='submitted',(name,end.session.reason)
        if name!='recording_failure':
            current=None
            reconstructed=[]
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            verify_trace(rows, name)
            assert not any(row['kind']=='observation_error' for row in rows),name
            for row in rows:
                if row['kind']=='initial':
                    current=copy.deepcopy(row['state'])
                for change in row.get('patch',[]):
                    current=apply(current,change)
                if row['kind']=='node_end':
                    reconstructed.append(copy.deepcopy(current))
            expected=[next(iter(update.values())) for update in observed['updates']]
            assert reconstructed==expected,name
            assert any(row['kind']=='call_end' for row in rows) or name in {'closed','expired'},name
        scenarios.append(dict(name=name,termination=end.session.termination,nodes=len(observed['updates'])))
    report=dict(status='pass',scenarios=scenarios,node_updates=sum(row['nodes'] for row in scenarios),
                recording_failure='nonfatal_no_replay',source_drift='detected_without_behavior_change',network='none',actual_models='not_run')
    (OUTPUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    verify()
