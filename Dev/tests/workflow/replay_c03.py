"""Replay saved interpretation bytes; this is not a fresh model-quality check."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def verify(submission, trace, output):
    sys.path.insert(0,str(submission.resolve()))
    from workflow.runtime import prepare, assemble_consultation
    from workflow.state.models import ClinicalFact, Question, SessionContext, WorkflowState
    import fixtures as f
    selected={}
    with trace.open() as stream:
        for line in stream:
            prefix=line[:30]
            if any(prefix.startswith('{"seq": '+str(seq)+',') for seq in (28422,28457,28483,28509)):
                event=json.loads(line)
                selected[event['seq']]=event
    context=selected[28422]['response']['choices'][0]['message']['content']
    original=json.loads(selected[28457]['body']['messages'][-1]['content'])
    q=original['question']
    resources=prepare()
    knowledge=resources.knowledge
    calls=[]
    class SDK(f.FakeSDK):
        def chat(self,messages,**kwargs):
            payload=json.loads(messages[-1]['content'])
            calls.append(payload)
            assert payload['task']=='input_context','Saved care statements must not call a mapper'
            return self.completion(context)
    client=SDK()
    c=assemble_consultation(client,resources,now=lambda:f.FIXED)
    s=f.state()
    s.case.apply([ClinicalFact(id='chief',kind='symptom',target=knowledge.term(q['target_id']),status='present',
        subject='patient',reported_by='mother',time_context='current',observation_id=q['observation_id'],
        episode_id=q['episode_id'],category='presentation',acquisition='SAY',source_ref='earlier')])
    question=Question(item_id=q['item_id'],purpose='intake',text=q['text'],target=knowledge.term(q['target_id']),
        observation_id=q['observation_id'],episode_id=q['episode_id'],category='previous_care',coverage=True)
    c.questions.register(s,question)
    c.interactions.select_question(s,question)
    s.turn.stage,s.turn.response='received',{'content':original['input'],'turn':4}
    c.interpreter.record_delivery(question,s.turn.request_id,s.turn.response)
    c.interpreter.process_input(s,knowledge,client)
    assert len(s.case.facts)==1 and s.case.chief(confirmed=True).status=='present'
    notes=list(s.case.notes.values())
    assert len(notes)==2 and {n.status for n in notes}=={'present','absent'}
    assert all(n.category=='previous_care' and n.reported_by=='mother' and n.time_context=='past' for n in notes)
    assert len(calls)==1 and s.turn is None
    c.freeze_diagnosis(s)
    c.writer.build_soap(s)
    hpi=s.turn.payload['note']['S']['hpi']
    assert 'previous treatment (-)' in hpi and 'observation; monitoring (+)' in hpi
    old=[]
    for seq in (28457,28483,28509):
        payload=json.loads(selected[seq]['body']['messages'][-1]['content'])
        old.append(dict(seq=seq,phase=payload['phase'],statements=len(payload['statements']),
                        candidates=sum(len(row['candidates']) for row in payload['statements'])))
    report=dict(status='pass',source_trace=str(trace),trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),
        saved_context_sha256=hashlib.sha256(context.encode()).hexdigest(),saved_mapping_requests=old,
        replay_context_calls=1,replay_mapping_calls=0,preserved_notes=[n.model_dump() for n in notes],soap_hpi=hpi,
        replay='unchanged_saved_context_response',revised_prompt_live_quality='not_run',actual_NOVA='not_run')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--submission',type=Path,required=True)
    p.add_argument('--trace',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    verify(a.submission,a.trace,a.output)
