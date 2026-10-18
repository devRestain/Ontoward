import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import fixtures as f
from education_fixtures import TEXT, education_response
from workflow.education import generate_plan, _EducationWork, parse_plan, references
from workflow.rules.limits import LIMITS
from workflow.state.models import Diagnosis, PendingEmpathy, Question


class DeliveryTests(unittest.TestCase):
    def test_complete_education_and_replies_are_transcript_only(self):
        c,s,updates = f.run(prepared=f.resources(education=True))
        self.assertEqual(s.session.termination,'submitted')
        self.assertEqual(len(s.case.plan),5)
        self.assertEqual(s.interview.education_status,'complete')
        self.assertEqual(s.session.usage['Education'].actions,5)
        self.assertEqual(sum(a.purpose=='education' and a.outcome=='delivered' for a in s.interview.answers),5)
        self.assertTrue(all(c.client.submissions[0]['note']['P'].values()))
        self.assertFalse(any(p['task']=='input_context' and p['question'] and p['question']['purpose']=='education'
                             for p in c.client.requests))
        revision = next(raw['case']['revision'] for name,raw in updates if raw['interview']['current']=='Education')
        self.assertEqual(s.case.revision,revision)

    def test_plan_source_quotes_verified_and_only_offsets_retained(self):
        work = _EducationWork()
        raw = education_response({'task':'education','phase':'direct'})
        raw['P']['tests'][0].update(basis='guideline',references=[{'document_id':'doc','quote':'exact source'}])
        accepted,errors = parse_plan(raw,{'doc':[(10,'a exact source z')]},work)
        self.assertFalse(errors)
        ref = work.sentences[0].references[0]
        self.assertEqual(ref.start_byte,12)
        self.assertEqual(ref.end_byte,24)
        self.assertNotIn('quote',ref.model_dump())
        with self.assertRaises(ValueError):
            references([{'document_id':'doc','quote':'invented'}],{'doc':[(0,'actual')]})

    def test_source_fragments_cover_all_bytes_and_work_is_not_in_state(self):
        from workflow.education import _fragments, messages, message_bytes
        text = ('Clinical source.\n\n'*5000)+'끝'
        doc = {'document_id':'d','text':text}
        chunks = list(_fragments(doc,{},'prompt'))
        self.assertEqual(''.join(c['text'] for c in chunks),text)
        self.assertEqual(chunks[-1]['end_byte'],len(text.encode()))
        self.assertTrue(all(a['end_byte']==b['start_byte'] for a,b in zip(chunks,chunks[1:])))
        self.assertTrue(all(message_bytes(messages('prompt',{'documents':[c]}))<=LIMITS.education_request_bytes for c in chunks))

    def test_invalid_render_is_bounded_without_losing_english_plan(self):
        def response(payload):
            if payload['task']=='education_doctor':
                return {'items':[{'id':r['id'],'utterances':['x'*31]} for r in payload['sentences']]}
        c = f.consultation(f.FakeSDK(chat_handler=response),f.resources(education=True))
        s = f.chief(f.state('Education',initialized=True))
        c.freeze_diagnosis(s)
        c.planner.prepare_education(s,c.client)
        c.doctor.prepare_education(s,c.client)
        self.assertEqual(len(s.case.plan),5)
        self.assertFalse(s.interview.queue)
        self.assertEqual(len([p for p in c.client.requests if p['task']=='education_doctor']),2)
        self.assertEqual(len([a for a in s.interview.answers if a.outcome=='undelivered']),5)
        c.writer.build_soap(s)
        self.assertTrue(all(s.turn.payload['note']['P'].values()))

    def test_conditional_group_withholds_whole_invalid_group(self):
        def response(payload):
            if payload['task']=='education_doctor':
                return {'items':[{'id':r['id'],'utterances':['전제 조건을 확인해요.','그 외에는 약을 드세요.']}
                                 for r in payload['sentences']]}
        c = f.consultation(f.FakeSDK(chat_handler=response),f.resources(education=True))
        s = f.chief(f.state('Education',initialized=True))
        c.freeze_diagnosis(s)
        c.planner.prepare_education(s,c.client)
        c.doctor.prepare_education(s,c.client)
        self.assertFalse(s.interview.queue)
        self.assertTrue(all(a.outcome=='undelivered' for a in s.interview.answers))

    def test_plan_repair_preserves_successful_sentences_and_runs_once(self):
        count = 0
        def response(payload):
            nonlocal count
            if payload['task']=='education':
                count += 1
                raw = education_response(payload)
                raw['P']['treatment'] = []
                return raw
        c = f.consultation(f.FakeSDK(chat_handler=response),f.resources(education=True))
        s = f.chief(f.state('Education'))
        c.freeze_diagnosis(s)
        c.planner.prepare_education(s,c.client)
        c.planner.prepare_education(s,c.client)
        self.assertEqual(count,2)
        self.assertEqual(len(s.case.plan),4)
        self.assertEqual(s.interview.education_status,'partial')

    def test_education_fixes_one_diagnosis_and_ignores_late_emotion(self):
        c,s = f.consultation(prepared=f.resources(education=True)),f.chief(f.state('Education'))
        c.freeze_diagnosis(s)
        c.planner.prepare_education(s,c.client)
        before = s.case.model_dump()
        q = Question(item_id='education',purpose='education',text='계획을 안내드릴게요.',plan_sentence_id=s.case.plan[0].id)
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        s.turn.stage,s.turn.response='received',{'content':'New disease and fear','turn':1}
        calls = s.session.doctor_calls
        c.interpreter.process_input(s,c.planner.knowledge,c.client)
        c.refresh_after_input(s)
        self.assertEqual(s.case.model_dump(),before)
        self.assertEqual(s.session.doctor_calls,calls)
        self.assertIsNone(s.interview.empathy)
        self.assertIsNone(s.turn)

    def test_education_can_deliver_prepared_questions_without_models(self):
        c,s = f.consultation(prepared=f.resources(education=True)),f.chief(f.state('Education',initialized=True))
        c.freeze_diagnosis(s)
        c.planner.prepare_education(s,c.client)
        c.doctor.prepare_education(s,c.client)
        s.session.models_available=False
        q=s.interview.queue[0]
        c.interactions.select_question(s,q)
        c.doctor.validate_action(s)
        c.doctor.execute_action(s,c.client)
        c.interpreter.process_input(s,c.planner.knowledge,c.client)
        self.assertEqual(s.interview.answers[-1].outcome,'delivered')

    def test_empathy_keeps_codes_and_canonical_facts_without_patient_raw(self):
        def response(payload):
            return {'statements':[f.statement('Complaint')],
                    'empathy':{'quote':'I am scared','emotion':'fear','intent':'new_distress'}}
        s,c,client=f.interpret([],text='Complaint I am scared',responses=response)
        self.assertEqual(s.interview.empathy.emotion,'fear')
        self.assertNotIn('I am scared',s.model_dump_json())
        client.chat_handler=None
        c.doctor.prepare_empathy(s,client,s.interview.empathy)
        payload=client.requests[-1]
        self.assertEqual(payload['emotion'],'fear')
        self.assertNotIn('I am scared',json.dumps(payload))
        self.assertNotIn('dialogue',payload)

    def test_empathy_reserves_three_calls_and_separate_action_accounting(self):
        c,s=f.consultation(),f.chief(f.state('ChiefComplaint',initialized=True))
        s.session.call_limit=2
        self.assertFalse(c.budget.can_empathize(s))
        s.session.call_limit=3
        self.assertTrue(c.budget.can_empathize(s))
        c.doctor.usage.record_actions(s,50,49,purpose='empathy')
        self.assertEqual(c.budget.interview_actions(s),0)
        self.assertEqual(s.session.usage['ChiefComplaint'].actions,1)

    def test_invalid_empathy_uses_prepared_fallback(self):
        client=f.FakeSDK(chat_handler=lambda p:{'text':'x'*31} if p['task']=='empathy' else None)
        c,s=f.consultation(client),f.chief(f.state())
        event=PendingEmpathy(source_ref='s',emotion='fear',intent='new_distress',key='k')
        s.interview.empathy=event
        c.doctor.prepare_empathy(s,client,event)
        self.assertEqual(s.question().text,c.planner.config.texts.empathy_fallback)


if __name__=='__main__':
    unittest.main()
