"""Compare observed and unobserved D44 execution and reconstruct every node."""
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
from workflow.graph import build_graph
from workflow.state.models import WorkflowState

OUTPUT=Path(os.environ.get('ONTOWARD_OBSERVER_OUTPUT',ROOT/'Tmp/d44-observer'))


def capture(name,observed):
    client=f.FakeSDK(context='absent' if name=='negative_context' else 'unknown' if name=='unknown_context' else 'present')
    c=f.consultation(client,prepared=f.resources(education=name=='education'))
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
        from workflow import graph
        updates=list(graph.build_graph(c,c.brain.knowledge).stream(initial.model_dump(mode='json'),
            {'recursion_limit':c.budget.graph_step_limit(initial)},stream_mode='updates'))
    return plain({'initial':initial.model_dump(mode='json'),'updates':updates,'wire':wire}),path


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


def verify():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    scenarios=[]
    for name in ('normal','negative_context','unknown_context','education','transient_model','model_limit',
                 'malformed_context','expired','closed','soap_repair','unconfirmed','refusal','action_format','recording_failure'):
        baseline,_=capture(name,False)
        observed,path=capture(name,True)
        assert baseline==observed,name
        end=WorkflowState.model_validate(next(iter(observed['updates'][-1].values())))
        if name in {'normal','education','negative_context','unknown_context','soap_repair','refusal','action_format','transient_model','recording_failure'}:
            assert end.session.termination=='submitted',(name,end.session.reason)
        if name!='recording_failure':
            current=None
            reconstructed=[]
            rows=[json.loads(line) for line in path.read_text().splitlines()]
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
