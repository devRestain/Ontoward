"""Compare observed and unobserved sequential execution and reconstruct each operation."""
from contextlib import nullcontext
import copy
import json
import os
from pathlib import Path
import sys

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
    if name == 'education_repair':
        from education_fixtures import education_response
        def response(payload):
            if payload['task'] == 'education':
                raw = education_response(payload)
                raw['P']['treatment'][0]['utterances'] = ['가' * 31]
                return raw
        client.chat_handler = response
    if name == 'fixed_unknown':
        original_action = client._action
        def unknown(*args):
            return {**original_action(*args), 'content': '모르겠습니다'}
        client._action = unknown
    c=f.consultation(client,prepared=f.resources(education=name in {'education', 'education_repair'}))
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
    with context:
        initial=c.nova_session.initialize_case(client)
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
    assert not [c for c in inspection['checks'] if c['status']=='fail'], (name, inspection['checks'])
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
        assert settings['pipeline']['contract'] == 'D50'
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
    return inspection


def verify():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    scenarios=[]
    for name in ('normal','negative_context','unknown_context','fixed_unknown','education','education_repair','transient_model','model_limit',
                 'malformed_context','expired','closed','soap_repair','unconfirmed','refusal','action_format','recording_failure'):
        baseline,_=capture(name,False)
        observed,path=capture(name,True)
        assert baseline==observed,name
        end=WorkflowState.model_validate(next(iter(observed['updates'][-1].values())))
        if name in {'normal','education','education_repair','fixed_unknown','negative_context','unknown_context','soap_repair','refusal','action_format','transient_model','recording_failure'}:
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
                recording_failure='nonfatal_no_replay',network='none',actual_models='not_run')
    (OUTPUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    verify()
