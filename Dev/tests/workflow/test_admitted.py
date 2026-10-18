"""Admitted RDF acceptance with explicit source-shaped protocol doubles."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import unicodedata


def verify(submission, output):
    sys.path.insert(0,str(submission.resolve()))
    import fixtures as f
    from education_fixtures import education_response
    from workflow.runtime import prepare, assemble_consultation
    from workflow.graph import build_graph
    from workflow.state.models import WorkflowState, Question
    from workflow.rules.assessment import graph_candidates
    from brain_double import clinical_response
    resources=prepare()
    k,config=resources.knowledge,resources.config
    original=frozenset(k._graph)
    checks=[]
    def require(value,name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    target=str(f.OW.SymptomSnomedCT21522001)
    disease=str(f.OW.SnomedCT65275009)
    detailed=next(p for p in k.get_disease_patterns(disease) if p.target==target and p.score==4
                  and len([feature for feature in k.get_pattern_features(p.id) if feature.expected])>=2)
    locations=[k.term(feature.expected.concept) for feature in k.get_pattern_features(detailed.id)
               if feature.attribute==str(f.OW.Location) and feature.expected and feature.expected.kind=='concept']
    fallback=next(c['id'] for c in k.concepts() if c['kind']=='Symptom' and k.questions[c['id']].interviewable
        and not k.get_patterns_by_target(c['id']))
    class SDK(f.FakeSDK):
        def __init__(self,target_id,numeric=False,context='unknown'):
            super().__init__(target=k.term(target_id),context=context)
            self.target_id,self.numeric=target_id,numeric
        def chat(self,messages,**kwargs):
            payload=json.loads(messages[-1]['content'])
            self.requests.append(payload)
            clinical=clinical_response(payload)
            if clinical is not None:
                require(kwargs['reasoning_effort']=='high','Brain_high_effort')
                require(len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode())<=65536,'Brain_whole_message_cap')
                return self.completion(clinical)
            education=education_response(payload)
            if education is not None:
                return self.completion(education)
            require(payload['task']=='input_context','only_exact_binding_needs_context')
            q,text=payload['question'],payload['input']
            rows=[]
            if not q:
                rows=[f.statement(text,target_terms=[self.target],primary_concern=True)]
            elif q['purpose']=='hpi':
                row=f.statement(text,focus='attribute',target_terms=[q['target']],attribute_terms=[q['attribute']],
                    observation_id=q['observation_id'],episode_id=q['episode_id'])
                attr=k.term_id(q['attribute'],'FindingAttribute')
                if attr==str(f.OW.Location) and self.target_id==target:
                    row['value_terms']=locations
                    rows=[row]
                elif self.numeric and attr==str(f.OW.TimeSinceOnset):
                    row['measurement']={'kind':'quantity','value':2,'unit':'month','approximate':True}
                    rows=[row]
                elif self.numeric and attr==str(f.OW.EpisodeDuration):
                    row['measurement']={'kind':'interval','lower':1,'upper':2,'unit':'h','upper_inclusive':False}
                    rows=[row]
            elif q['purpose']=='context' and self.context!='unknown':
                rows=[f.statement(text,target_terms=[q['target']],subject=q.get('subject','patient'),
                    time_context=q.get('time_context','unspecified'),assertion=self.context)]
            elif q['kind']=='EXAM':
                rows=[f.statement(text,target_terms=[q['target']],time_context=q.get('time_context','current'))]
            if not rows:
                rows=[f.statement(text,role='unknown',assertion='unknown',target_terms=[])]
            return self.completion({'statements':rows})
        def _action(self,kind,content,request_id):
            require(unicodedata.normalize('NFC',content)==content and 1<=len(content)<=30,'Korean_NFC_action_bound')
            require(any('가'<=c<='힣' for c in content),'Korean_delivery')
            return super()._action(kind,content,request_id)
        def diagnose(self,**payload):
            require(set(payload)=={'note','diagnosis','request_id'},'wire_fields')
            require(all(set(payload['note'][section])==set(fields) for section,fields in f.RECORD_FIELDS.items()),'fifteen_soap_fields')
            require(payload['note']['O']['tests']=='','no_unobtained_tests')
            return super().diagnose(**payload)
    output.mkdir(parents=True,exist_ok=True)
    cases=[]
    for target_id,numeric in [(target,False),(target,True),(fallback,False)]:
        client=SDK(target_id,numeric)
        c=assemble_consultation(client,resources,now=lambda:f.FIXED,sleep=lambda n:None)
        initial=c.nova_session.initialize_case(client)
        started=time.perf_counter()
        result=build_graph(c,k).invoke(initial.model_dump(mode='json'),{'recursion_limit':c.budget.graph_step_limit(initial)})
        state=WorkflowState.model_validate(result)
        require(state.session.termination=='submitted' and len(client.submissions)==1,'confirmed_submission')
        require(state.turn is None and not state.interview.queue,'closed_turn_and_queue')
        require(all(not any('가'<=ch<='힣' for ch in text) for text in client.submissions[0]['note']['S'].values()),'English_S')
        require(all(client.submissions[0]['note']['P'].values()),'complete_English_P')
        require(len(state.case.plan)==5,'one_final_plan')
        require(state.session.usage['Education'].actions>=5,'Korean_education_delivered')
        if target_id==target:
            require(state.case.assessment.frozen,'frozen_disease_assessment')
            require(state.case.primary().kind=='disease','supported_disease')
        else:
            require(state.case.primary().kind=='symptom','honest_symptom_fallback')
        if numeric:
            require('approximately 2 months' in client.submissions[0]['note']['S']['hpi'],'approximate_registered_number')
        require(frozenset(k._graph)==original,'read_only_RDF')
        (output/f'case-{len(cases)}.json').write_text(state.model_dump_json(indent=2))
        cases.append(dict(target=k.term(target_id),numeric=numeric,actions=len(client.actions),calls=state.session.doctor_calls,
            diagnosis=state.case.primary().name,kind=state.case.primary().kind,seconds=time.perf_counter()-started))
        c.release()
    selected=[]
    for status in ('present','absent','unknown'):
        client=SDK(target,context=status)
        c=assemble_consultation(client,resources,now=lambda:f.FIXED,sleep=lambda n:None)
        state=c.nova_session.initialize_case(client)
        c.ear.process_input(state,k,client)
        state.interview.current,state.interview.status='ContextFactor','collecting'
        candidates=graph_candidates(state.case,k)
        context=next(context for disease in candidates for context in k.get_supporting_context(disease)
                     if k.questions[context['id']].interviewable)
        subject='family' if context['type']=='family_history' else 'patient'
        spec=c.brain._spec(state,context['id'],purpose='context',field='S.fh' if subject=='family' else 'S.pmh',subject=subject,time_context='unspecified')
        c.brain._register(state,spec,0,1)
        c.brain.select_question(state)
        c.mouth.validate_action(state)
        c.mouth.execute_action(state,client)
        c.ear.process_input(state,k,client)
        require(any(fact.target==k.term(context['id']) and fact.status==status for fact in state.case.facts.values()) if status!='unknown'
                else state.interview.answers[-1].outcome=='unknown','selected_context_polarity_'+status)
        candidates=graph_candidates(state.case,k)
        refs=[ref for candidate in candidates.values() for ref in candidate.entry.supports
            if ref.graph_ref.kind=='context' and ref.graph_ref.id==context['id']]
        require(bool(refs) if status=='present' else not refs,'context_support_'+status)
        c.finalize(state)
        c.writer.submit_diagnosis(state)
        c.writer.confirm_submission(state)
        require(state.session.termination=='submitted','selected_context_receipt_'+status)
        selected.append(dict(status=status,target=k.term(context['id'])))
    exam=next(p.target for p in k._profile_cache.values() if k.has_type(p.target,'ExamFinding'))
    client=SDK(target)
    c=assemble_consultation(client,resources,now=lambda:f.FIXED,sleep=lambda n:None)
    state=c.nova_session.initialize_case(client)
    c.ear.process_input(state,k,client)
    state.interview.current,state.interview.status='DifferentialDiagnosis','collecting'
    c.brain._register(state,c.brain._spec(state,exam,episode='one'),0,1)
    c.brain.select_question(state)
    c.mouth.validate_action(state)
    c.mouth.execute_action(state,client)
    c.ear.process_input(state,k,client)
    require(any(fact.kind=='finding' and fact.target==k.term(exam) and fact.acquisition=='EXAM' for fact in state.case.facts.values()),'actual_exam_acquisition')
    c.finalize(state)
    c.writer.submit_diagnosis(state)
    c.writer.confirm_submission(state)
    require(state.session.termination=='submitted' and k.term(exam) in client.submissions[0]['note']['O']['exam'],'exam_soap_and_receipt')
    report=dict(status='pass',cases=cases,selected_context=selected,exam=k.term(exam),checks=len(checks),
        graph_triples=len(original),associations=len(k._profile_cache),network='none',model_responses='scripted',
        actual_luna='not_run',clinical_accuracy='not_run',official_evaluation='not_run',
        manifest_sha256=hashlib.sha256((submission/'knowledge/manifest.json').read_bytes()).hexdigest())
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--submission',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    verify(args.submission,args.output)
