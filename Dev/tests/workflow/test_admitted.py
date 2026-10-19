"""Verify an explicitly installed v5-enum-1 bundle with protocol doubles."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def fixture_reply(knowledge, payload):
    if payload.get('task')!='input_context' or not payload.get('question',{}): return None
    question=payload['question']
    if not question.get('attribute'): return None
    import fixtures as f
    attribute=knowledge.term_id(question['attribute'],'FindingAttribute')
    values=knowledge.get_attribute_values(attribute)
    row=f.statement(payload['input'],focus='attribute',target_terms=[question['target']],
        attribute_terms=[question['attribute']],observation_id=question['observation_id'],episode_id=question['episode_id'])
    if values: row['value_terms']=[knowledge.term(values[0])]
    else:
        units=knowledge.numeric_units(knowledge.term_id(question['target'],'Symptom'),attribute)
        if not units: return None
        row['measurement']=dict(kind='quantity',value=2.0,unit=units[0])
    return {'statements':[row]}


def verify(submission, output):
    sys.path.insert(0,str(submission.resolve()))
    import fixtures as f
    from workflow.runtime import prepare, PreparedResources
    resources=prepare();knowledge=resources.knowledge
    target=next(profile.target for profiles in knowledge._disease_profiles.values() for profile in profiles
        if profile.effect in {'support','strong_support'} and knowledge.has_type(profile.target,'Symptom')
        and knowledge.question_contract(profile.target).interviewable)
    reports=[]
    for education,context in [(False,'unknown'),(True,'present'),(True,'absent')]:
        client=f.FakeSDK(target=knowledge.term(target),context=context,
            chat_handler=lambda payload:fixture_reply(knowledge,payload))
        prepared=PreparedResources(knowledge,resources.config.model_copy(update={'education_enabled':education}))
        consultation,state,updates=f.run(client,prepared)
        assert state.session.termination=='submitted',(state.session.reason,context)
        assert state.case.assessment.frozen
        assert client.submissions[-1]['diagnosis']==state.case.primary().name
        assert sum(len(section) for section in client.submissions[-1]['note'].values())==15
        assert not client.submissions[-1]['note']['O']['tests']
        assert all(1<=len(action['content'])<=30 for action in client.actions)
        reports.append(dict(education=education,context=context,termination='submitted',nodes=len(updates)))
    report=dict(status='pass',cases=reports,knowledge_contract='v5-enum-1',actual_models='not_run',
        clinical_accuracy='not_run',manifest_sha256=hashlib.sha256((submission/'knowledge/manifest.json').read_bytes()).hexdigest())
    output.mkdir(parents=True,exist_ok=True);(output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--submission',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();verify(args.submission,args.output)
