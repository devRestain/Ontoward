"""Compare fixed accepted facts with a frozen baseline, using protocol replies only."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def probe(submission):
    sys.path.insert(0,str(submission))
    from workflow.runtime import prepare, assemble_consultation
    from workflow.state.models import ClinicalFact, SessionContext, WorkflowState
    from brain_double import clinical_response
    resources=prepare();k=resources.knowledge
    if hasattr(k,'get_feature_contributions'):
        contribution_rows={ident:[value.model_dump(mode='json') for value in k.get_feature_contributions(ident)]
            for ident in sorted(k._profile_cache)}
    else:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from Dev.ontology.contributions import feature_contributions
        contribution_rows={ident:[value.model_dump(mode='json') for value in feature_contributions(k,ident)]
            for ident in sorted(k._profile_cache)}
    contribution_digest=hashlib.sha256(json.dumps(contribution_rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    now=datetime.now(timezone.utc)
    class Models:
        timeout=120
        def __init__(self): self.requests=[]
        def chat(self,messages,**kwargs):
            payload=json.loads(messages[-1]['content']);self.requests.append(payload)
            return dict(choices=[dict(message=dict(content=json.dumps(clinical_response(payload))),finish_reason='stop')],
                usage=dict(prompt_tokens=20,completion_tokens=10))
    target='Abdominal pain';target_id=k.term_id(target,'Symptom')
    disease='urn:ontoward:SnomedCT65275009'
    profile=next(p for p in k.get_disease_patterns(disease) if p.target==target_id and p.score==4
        and any(f.expected and f.expected.kind=='concept' for f in k.get_pattern_features(p.id)))
    feature=next(f for f in k.get_pattern_features(profile.id) if f.expected and f.expected.kind=='concept')
    context=next(iter(k.get_supporting_context(disease)),None)
    rows=[]
    for label in ('chief_only','chief_and_attribute','chief_and_context','unknown_chief'):
        state=WorkflowState(session=SessionContext(session_id='fixed-input',deadline=now+timedelta(minutes=25),turns_remaining=50))
        state.interview.current='DifferentialDiagnosis'
        facts=[ClinicalFact(id='chief',kind='symptom',target=target,status='unknown' if label=='unknown_chief' else 'present',
            category='presentation',acquisition='initial',source_ref='fixed',time_context='current',observation_id='observation',episode_id='episode')]
        if label=='chief_and_attribute':
            facts.append(ClinicalFact(id='attribute',kind='attribute',target=target,attribute=k.term(feature.attribute),
                values=(k.term(feature.expected.concept),),status='present',acquisition='SAY',source_ref='fixed-attribute',
                time_context='current',observation_id='observation',episode_id='episode'))
        if label=='chief_and_context' and context:
            facts.append(ClinicalFact(id='context',kind='context',target=k.term(context['id']),status='present',
                subject='family' if context['type']=='family_history' else 'patient',acquisition='SAY',source_ref='fixed-context'))
        state.case.apply(facts)
        client=Models();c=assemble_consultation(client,resources,now=lambda:now)
        started=time.perf_counter()
        if hasattr(c,'brain'):
            from workflow.rules.assessment import graph_candidates
            candidates=graph_candidates(state.case,k)
            c.brain.refresh_assessment(state,client,closing=True)
            selected=[e.name for e in state.case.assessment.differential]
            retrieved=len(candidates);eligible=None
        else:
            result=c.reasoner.refresh_hypotheses(state)
            retrieved=len(result.hypotheses);supported=c.reasoner.supported_hypotheses(result)
            eligible=len(supported);c.reasoner.select_diagnosis(state)
            selected=[state.case.diagnosis.name] if state.case.diagnosis else []
        rows.append(dict(case=label,facts=[f.model_dump(mode='json') for f in facts],retrieved=retrieved,
            old_gate_eligible=eligible,selected=selected,clinical_calls=len(client.requests),
            candidates_sent=len(client.requests[0]['candidates']) if client.requests else 0,
            graph_state_bytes=len(state.model_dump_json().encode()),cpu_and_fixture_seconds=time.perf_counter()-started))
    return dict(cases=rows,preparation_contributions_sha256=contribution_digest,
        preparation_contributions_count=sum(map(len,contribution_rows.values())),runtime_python_files=len(list(submission.rglob('*.py'))),
        runtime_python_bytes=sum(p.stat().st_size for p in submission.rglob('*.py')))


def compare(baseline, submission, output):
    values={}
    for name,source in [('baseline',baseline),('d46',submission)]:
        result=subprocess.run([sys.executable,'-B',__file__,'--probe',str(source)],capture_output=True,text=True,check=True)
        values[name]=json.loads(result.stdout)
    for old,new in zip(values['baseline']['cases'],values['d46']['cases']):
        assert old['facts']==new['facts'],old['case']
    assert values['baseline']['preparation_contributions_sha256']==values['d46']['preparation_contributions_sha256']
    old=json.loads((baseline/'knowledge/manifest.json').read_text());new=json.loads((submission/'knowledge/manifest.json').read_text())
    keys=('build_id','schema','vocabulary','bundles','questions','guidelines','scoring_policy','source_snapshots')
    assert all(old[key]==new[key] for key in keys)
    assert (baseline/'nova_sdk.py').read_bytes()==(submission/'nova_sdk.py').read_bytes()
    values.update(status='pass',same_fixed_facts=True,preparation_contributions_equal=True,clinical_asset_pins='unchanged',
        model_responses='scripted',ranking_quality='not_measured',clinical_accuracy='not_run',
        baseline_manifest_sha256=hashlib.sha256((baseline/'knowledge/manifest.json').read_bytes()).hexdigest())
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(values,indent=2)+'\n')
    print(json.dumps({key:value for key,value in values.items() if key not in {'baseline','d46'}},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--probe',type=Path);parser.add_argument('--baseline',type=Path)
    parser.add_argument('--submission',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.probe: print(json.dumps(probe(args.probe)))
    else: compare(args.baseline,args.submission,args.output)
