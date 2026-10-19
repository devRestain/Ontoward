"""Compare the frozen D43 and current D44 on identical accepted clinical assertions."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time


def worker(runtime,output):
    sys.path.insert(0,str(runtime.resolve()))
    from workflow.runtime import prepare
    from workflow.clinical_reasoner import ClinicalReasoner
    from workflow.state.evidence import EvidenceIndex
    from workflow.state import models
    from workflow.graph import run_node
    resources=prepare()
    k=resources.knowledge
    modern=hasattr(models,'ClinicalFact')
    target='urn:ontoward:SymptomSnomedCT21522001'
    location='urn:ontoward:Location'
    disease='urn:ontoward:SnomedCT65275009'
    profile=next(p for p in k.get_disease_patterns(disease) if p.target==target and p.score==4
                 and sum(f.attribute==location for f in k.get_pattern_features(p.id))>=2)
    values=[f.expected.concept for f in k.get_pattern_features(profile.id) if f.attribute==location]
    context=k.get_supporting_context(disease)[0]['id']
    scope='family' if k.get_context_type(context)=='family_history' else 'patient'
    exam=next(p.target for p in k._profile_cache.values() if k.has_type(p.target,'ExamFinding'))
    fixed=[dict(id='chief',target=target,kind='symptom',field='S.cc',values=[],attribute=None,subject='patient'),
           dict(id='loc',target=target,kind='attribute',field='S.hpi',values=values,attribute=location,subject='patient'),
           dict(id='ctx',target=context,kind='context',field='S.fh' if scope=='family' else 'S.pmh',values=[],attribute=None,subject=scope),
           dict(id='exam',target=exam,kind='finding',field='O.exam',values=[],attribute=None,subject='patient')]
    s=models.WorkflowState(session=models.SessionContext(session_id='fixed',deadline=datetime(2026,10,18,tzinfo=timezone.utc)+timedelta(days=1),turns_remaining=40))
    for raw in fixed:
        common=dict(id=raw['id'],status='present',observation_id='obs1',episode_id='episode1',time_context='current',subject=raw['subject'])
        if modern:
            fact=models.ClinicalFact(**common,kind=raw['kind'],target=k.term(raw['target']),
                attribute=k.term(raw['attribute']) if raw['attribute'] else None,values=tuple(k.term(v) for v in raw['values']),
                category='presentation' if raw['id']=='chief' else None,acquisition='EXAM' if raw['kind']=='finding' else 'SAY',source_ref='fixed')
            s.case.apply([fact])
        else:
            ident=common.pop('id')
            value=models.ClinicalValue(**common,kind=raw['kind'],text='fixed accepted assertion',concept_ids=[raw['target']],
                attribute_id=raw['attribute'],values=raw['values'])
            s.case.put(raw['field'],models.RecordItem(id=ident,status='done',scope='ChiefComplaint',value=value,
                acquisition='EXAM' if raw['kind']=='finding' else 'SAY',source_refs=['fixed']))
    if not modern:
        s.case.select_primary()
        s.differential.initialized=True
    reasoner=ClinicalReasoner(k)
    if modern:
        snapshot=reasoner.refresh_hypotheses(s)
    else:
        reasoner.refresh_hypotheses(s)
        snapshot=reasoner.evaluate(EvidenceIndex.from_case(s.case),reasoner.anchor(s.case))
    scores=[dict(disease=h.disease_id,score=h.score,evidence=h.evidence_score,chief=h.chief_score,
        bonus=h.context_bonus,penalty=h.contradiction_penalty,coverage=h.chief_coverage,
        evidence_ids=h.evidence_ids,contradiction_ids=h.contradiction_ids) for h in snapshot.hypotheses]
    size=len(json.dumps(s.model_dump(mode='json'),ensure_ascii=False,separators=(',',':')).encode())
    copy_times=[]
    validation_times=[]
    node_times=[]
    for _ in range(31):
        start=time.perf_counter_ns()
        s.model_copy(deep=True)
        copy_times.append(time.perf_counter_ns()-start)
        raw=s.model_dump()
        start=time.perf_counter_ns()
        models.WorkflowState.model_validate(raw)
        validation_times.append(time.perf_counter_ns()-start)
        start=time.perf_counter_ns()
        run_node(s,lambda state:None)
        node_times.append(time.perf_counter_ns()-start)
    from workflow.runtime import assemble_consultation
    class InputSDK:
        session_id='fixed-input'
        timeout=120
        requests=[]
        def session(self):
            return dict(session_id=self.session_id,status='active',deadline='2026-10-19T00:00:00+00:00',turns_remaining=50,
                initial={'opening':'A reported complaint and two locations'},allowed_actions=['SAY','EXAM','DIAGNOSE'])
        def chat(self,**request):
            self.requests.append(request['messages'])
            payload=json.loads(request['messages'][-1]['content'])
            if payload['task']=='input_context':
                wire={'statements':[dict(quote=payload['input'],role='clinical',assertion='present',focus='target',
                    target_terms=[k.label(target,language='en')],primary_concern=True,time_context='current'),
                    dict(quote=payload['input'],role='clinical',assertion='present',focus='attribute',anchor=0,
                         target_terms=[k.label(target,language='en')],attribute_terms=[k.label(location,language='en')],
                         value_terms=[k.label(v,language='en') for v in values],time_context='current')]}
            else:
                wire=[]
                for statement in payload['statements']:
                    contract=next((row for row in statement['candidates'] if row['id']==target),None)
                    if not contract:
                        wire.append({})
                    elif not contract['attributes']:
                        wire.append({target:'(+)'})
                    else:
                        attr=next((a for a in contract['attributes'] if a['id']==location),None)
                        allowed={v['id'] for v in attr['values']} if attr else set()
                        wire.append({target:{location:dict.fromkeys(values,'(+)')}} if set(values)<=allowed else {})
            return {'choices':[{'message':{'content':json.dumps(wire)}}],
                    'usage':{'prompt_tokens':20,'completion_tokens':10}}
    client=InputSDK()
    c=assemble_consultation(client,resources,now=lambda:datetime(2026,10,18,tzinfo=timezone.utc))
    initial=c.nova_session.initialize_case(client)
    c.interpreter.process_input(initial,k,client)
    input_facts=len(initial.case.facts) if modern else sum(item.value is not None for _,item in initial.case.entries())
    if modern:
        input_semantics=sorted((fact.kind,fact.target,fact.attribute or '',sorted(fact.values),fact.status)
                               for fact in initial.case.facts.values())
    else:
        input_semantics=sorted((item.value.kind,k.label(item.value.concept_ids[0],language='en'),
            k.label(item.value.attribute_id,language='en') if item.value.attribute_id else '',
            sorted(k.label(v,language='en') for v in item.value.values),item.value.status)
            for _,item in initial.case.entries() if item.value and item.value.concept_ids)
    report=dict(mode='d44' if modern else 'd43',assertions=fixed,scores=scores,state_bytes=size,
        copy_median_ms=statistics.median(copy_times)/1e6,validate_median_ms=statistics.median(validation_times)/1e6,
        node_median_ms=statistics.median(node_times)/1e6,iterations=31,
        includes_model_history=False,includes_reasoning_in_state=not modern,
        fixed_input_facts=input_facts,fixed_input_calls=len(client.requests),
        fixed_input_semantics=input_semantics,
        clinical_bundle_sha256=hashlib.sha256(next((runtime/'knowledge').glob('*-clinical.ttl')).read_bytes()).hexdigest())
    output.write_text(json.dumps(report,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--baseline',type=Path)
    p.add_argument('--submission',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--worker',type=Path)
    a=p.parse_args()
    if a.worker:
        worker(a.worker,a.output)
        return
    a.output.mkdir(parents=True,exist_ok=True)
    for name,path in [('baseline',a.baseline),('current',a.submission)]:
        subprocess.run([sys.executable,'-B',__file__,'--worker',str(path),'--output',str(a.output/(name+'.json'))],check=True)
    old,new=[json.loads((a.output/(name+'.json')).read_text()) for name in ('baseline','current')]
    assert old['assertions']==new['assertions']
    assert old['scores']==new['scores']
    assert old['fixed_input_semantics']==new['fixed_input_semantics']
    assert old['clinical_bundle_sha256']==new['clinical_bundle_sha256']
    result=dict(status='pass',baseline=old,current=new,score_parity=True,network='none',
        state_reduction_percent=100*(1-new['state_bytes']/old['state_bytes']),
        limitations=['Four fixed accepted assertions, local medians only','Not a live service latency or clinical quality measurement',
                     'Historical C03 peak state is a separate recorded case, not the same fixed workload'])
    (a.output/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:value for key,value in result.items() if key not in {'baseline','current'}},indent=2))


if __name__=='__main__':
    main()
