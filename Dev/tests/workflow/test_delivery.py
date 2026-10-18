import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import fixtures as f
from education_fixtures import TEXT, education_response
from workflow.education import generate_plan, _EducationWork, parse_plan, references
from workflow.rules.limits import LIMITS
from workflow.state.models import PendingEmpathy, Question


class DeliveryTests(unittest.TestCase):
    def test_complete_education_and_replies_are_transcript_only(self):
        c,s,updates = f.run(prepared=f.resources(education=True))
        self.assertEqual(s.session.termination,'submitted')
        self.assertEqual(len(s.case.plan),5)
        self.assertEqual(s.interview.education_status,'complete')
        self.assertEqual(s.session.usage['Education'].actions,6)
        self.assertEqual(sum(a.purpose=='education' and a.outcome=='delivered' for a in s.interview.answers),6)
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
        c.close_collection(s)
        c.brain.prepare_education(s,c.client)
        c.mouth.prepare_education(s,c.client)
        self.assertEqual(len(s.case.plan),5)
        self.assertFalse(s.interview.queue)
        self.assertEqual(len([p for p in c.client.requests if p['task']=='education_doctor']),2)
        self.assertEqual(len([a for a in s.interview.answers if a.outcome=='undelivered']),5)
        c.writer.build_soap(s)
        self.assertTrue(all(s.turn.payload['note']['P'].values()))

    def test_provider_render_failure_recovers_once_before_completed_submission(self):
        client = f.FakeSDK()
        original, requests = client.chat, []
        def chat(**request):
            payload = json.loads(request['messages'][-1]['content'])
            if payload['task'] == 'education_doctor':
                requests.append(copy.deepcopy(request))
                if len(requests) == 1:
                    raise f.NovaError('PROVIDER_RESPONSE_INVALID', 503)
            return original(**request)
        client.chat = chat
        c,s,_ = f.run(client, prepared=f.resources(education=True))
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.interview.education_status, 'complete')
        self.assertEqual(s.session.usage['Education'].actions, 6)
        self.assertEqual([r['max_tokens'] for r in requests], [8000, 8000])
        self.assertNotEqual(requests[0]['request_id'], requests[1]['request_id'])
        repair = json.loads(requests[1]['messages'][-1]['content'])
        self.assertEqual(repair['generation_error'], 'PROVIDER_RESPONSE_INVALID')
        self.assertEqual(repair['validation_errors'], {})
        self.assertTrue(all(client.submissions[0]['note']['P'].values()))
        self.assertEqual(client.actions[0]['content'], '병원 오시는 길이 불편하진 않으셨나요?')

    def test_repeated_provider_render_failure_retains_cause_and_english_plan(self):
        requests = []
        def response(payload):
            if payload['task'] == 'education_doctor':
                requests.append(payload)
                raise f.NovaError('PROVIDER_RESPONSE_INVALID', 503)
        client = f.FakeSDK(chat_handler=response)
        c,s,_ = f.run(client, prepared=f.resources(education=True))
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.interview.education_status, 'partial')
        self.assertEqual(s.interview.education_reason, 'PROVIDER_RESPONSE_INVALID')
        self.assertEqual(s.session.usage['Education'].actions, 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(s.case.plan), 5)
        self.assertTrue(all(client.submissions[0]['note']['P'].values()))
        self.assertEqual({a.reason for a in s.interview.answers if a.purpose == 'education' and a.outcome == 'undelivered'},
                         {'PROVIDER_RESPONSE_INVALID'})

    def test_truncated_render_uses_one_larger_recovery_without_partial_delivery(self):
        requests = []
        def response(payload):
            if payload['task'] == 'education_doctor':
                requests.append(payload)
                if len(requests) == 1:
                    return f.FakeSDK.completion(education_response(payload), finish_reason='length')
        c,s,_ = f.run(f.FakeSDK(chat_handler=response), prepared=f.resources(education=True))
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.session.usage['Education'].actions, 6)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]['generation_error'], 'OUTPUT_TRUNCATED')
        self.assertEqual(requests[1]['sentences'], requests[0]['sentences'])

    def test_provider_then_invalid_render_keeps_a_separate_format_repair(self):
        requests = []
        accepted = None
        def response(payload):
            nonlocal accepted
            if payload['task'] == 'education_doctor':
                requests.append(copy.deepcopy(payload))
                if len(requests) == 1:
                    raise f.NovaError('PROVIDER_RESPONSE_INVALID', 503)
                if len(requests) == 2:
                    raw = education_response(payload)
                    accepted = raw['items'][0]['id']
                    for row in raw['items'][1:]:
                        row['utterances'] = ['가'*31]
                    return raw
        c,s,_ = f.run(f.FakeSDK(chat_handler=response), prepared=f.resources(education=True))
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.interview.education_status, 'complete')
        self.assertEqual(s.session.usage['Education'].actions, 6)
        self.assertEqual(len(requests), 3)
        self.assertNotIn(accepted, {row['id'] for row in requests[2]['sentences']})
        for error in requests[2]['validation_errors'].values():
            self.assertEqual(error['codepoints'], [31])
            self.assertEqual(error['max_codepoints'], 30)
        self.assertTrue(all(c.client.submissions[0]['note']['P'].values()))

    def test_symptom_diagnosis_has_general_plan_without_guideline_lookup(self):
        resources = f.resources(education=True)
        resources.knowledge.guidelines.read = lambda _: (_ for _ in ()).throw(AssertionError('symptom lookup'))
        c,s,_ = f.run(f.FakeSDK(target='Other symptom'), prepared=resources)
        self.assertEqual(s.case.primary().kind, 'symptom')
        self.assertIn('no_graph_disease_assessment',s.case.assessment.limitations)
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.session.usage['Education'].actions, 7)
        plan_request = next(p for p in c.client.requests if p['task'] == 'education')
        self.assertEqual(plan_request['documents'], [])
        self.assertTrue(all(sentence.basis == 'model_knowledge' for sentence in s.case.plan))
        self.assertTrue(all(c.client.submissions[0]['note']['P'].values()))
        self.assertTrue(any(a['content'] == c.brain.config.texts.symptom_cause_unknown for a in c.client.actions))

    def test_diagnosis_notice_is_delivered_before_plan_generation(self):
        client = f.FakeSDK()
        notice = []
        def response(payload):
            if payload['task'] == 'education':
                notice.append(client.actions[-1]['content'])
        client.chat_handler = response
        c,s,_ = f.run(client, prepared=f.resources(education=True))
        ident = c.brain.knowledge.term_id(s.case.primary().name, 'Disease')
        expected = c.brain.config.texts.diagnosis_announcement.format(diagnosis=c.brain.knowledge.label(ident))
        self.assertEqual(notice, [expected])
        self.assertEqual(s.interview.answers[-6].question_id, 'Education:diagnosis:0')

    def test_long_diagnosis_notice_uses_the_short_complete_sentence(self):
        k = f.knowledge()
        k.labels[str(f.OW.Alpha)] = '조금 긴 가상 질환 이름'
        c,s = f.consultation(prepared=f.resources(k, education=True)),f.chief(f.state('Education',initialized=True))
        f.freeze(s,kind='disease',name='Disease alpha')
        self.assertTrue(c.mouth.prepare_diagnosis(s,c.client,k))
        self.assertEqual(s.interview.queue[0].text, '조금 긴 가상 질환 이름 의심됩니다.')
        self.assertLessEqual(len(s.interview.queue[0].text), 30)
        self.assertFalse(c.client.requests)

    def test_english_diagnosis_label_gets_a_short_korean_notice_without_changing_diagnosis(self):
        def response(payload):
            if payload.get('announcement'):
                self.assertEqual(payload['fixed_diagnosis']['name'], 'Disease alpha')
                return {'items':[{'id':'diagnosis','utterances':['가상질환A가 의심됩니다.']}]}
        k = f.knowledge()
        k.labels[str(f.OW.Alpha)] = 'Long English display name for disease alpha'
        c,s = f.consultation(f.FakeSDK(chat_handler=response),f.resources(k,education=True)),f.chief(f.state('Education',initialized=True))
        f.freeze(s,kind='disease',name='Disease alpha')
        before = s.case.model_dump()
        self.assertTrue(c.mouth.prepare_diagnosis(s,c.client,k))
        self.assertEqual(s.interview.queue[0].text, '가상질환A가 의심됩니다.')
        self.assertEqual(s.case.model_dump(), before)

    def test_fatal_announcement_error_does_not_start_plan_generation(self):
        requests = []
        def response(payload):
            requests.append(payload)
            raise f.NovaError('API_UNAVAILABLE')
        k = f.knowledge()
        k.labels[str(f.OW.Alpha)] = 'Long English display name for disease alpha'
        c,s = f.consultation(f.FakeSDK(chat_handler=response),f.resources(k,education=True)),f.chief(f.state('Education'))
        f.freeze(s,kind='disease',name='Disease alpha')
        c.enter_session(s)
        self.assertEqual(s.session.termination, 'unknown')
        self.assertEqual(len(requests), 2)
        self.assertEqual({p['task'] for p in requests}, {'education_doctor'})
        self.assertFalse(s.case.plan)

    def test_provider_plan_failure_recovers_without_parsing_absent_response(self):
        requests = []
        def response(payload):
            if payload['task'] == 'education':
                requests.append(payload)
                if len(requests) == 1:
                    raise f.NovaError('PROVIDER_RESPONSE_INVALID', 503)
        c,s,_ = f.run(f.FakeSDK(chat_handler=response), prepared=f.resources(education=True))
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(s.interview.education_status, 'complete')
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]['generation_error'], 'PROVIDER_RESPONSE_INVALID')
        self.assertEqual(requests[1]['validation_errors'], [])

    def test_conditional_group_withholds_whole_invalid_group(self):
        def response(payload):
            if payload['task']=='education_doctor':
                return {'items':[{'id':r['id'],'utterances':['전제 조건을 확인해요.','그 외에는 약을 드세요.']}
                                 for r in payload['sentences']]}
        c = f.consultation(f.FakeSDK(chat_handler=response),f.resources(education=True))
        s = f.chief(f.state('Education',initialized=True))
        c.close_collection(s)
        c.brain.prepare_education(s,c.client)
        c.mouth.prepare_education(s,c.client)
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
        c.close_collection(s)
        c.brain.prepare_education(s,c.client)
        c.brain.prepare_education(s,c.client)
        self.assertEqual(count,2)
        self.assertEqual(len(s.case.plan),4)
        self.assertEqual(s.interview.education_status,'partial')

    def test_education_fixes_one_diagnosis_and_ignores_late_emotion(self):
        c,s = f.consultation(prepared=f.resources(education=True)),f.chief(f.state('Education'))
        c.close_collection(s)
        c.brain.prepare_education(s,c.client)
        before = s.case.model_dump()
        q = Question(item_id='education',purpose='education',text='계획을 안내드릴게요.',plan_sentence_id=s.case.plan[0].id)
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        s.turn.stage,s.turn.response='received',{'content':'New disease and fear','turn':1}
        calls = s.session.doctor_calls
        c.ear.process_input(s,c.brain.knowledge,c.client)
        c.refresh_after_input(s)
        self.assertEqual(s.case.model_dump(),before)
        self.assertEqual(s.session.doctor_calls,calls)
        self.assertIsNone(s.interview.empathy)
        self.assertIsNone(s.turn)

    def test_education_can_deliver_prepared_questions_without_models(self):
        c,s = f.consultation(prepared=f.resources(education=True)),f.chief(f.state('Education',initialized=True))
        c.close_collection(s)
        c.brain.prepare_education(s,c.client)
        c.mouth.prepare_education(s,c.client)
        s.session.models_available=False
        q=s.interview.queue[0]
        c.interactions.select_question(s,q)
        c.mouth.validate_action(s)
        c.mouth.execute_action(s,c.client)
        c.ear.process_input(s,c.brain.knowledge,c.client)
        self.assertEqual(s.interview.answers[-1].outcome,'delivered')

    def test_empathy_keeps_codes_and_canonical_facts_without_patient_raw(self):
        def response(payload):
            return {'statements':[f.statement('Complaint')],
                    'empathy':{'quote':'I am scared','emotion':'fear','intent':'new_distress'}}
        s,c,client=f.interpret([],text='Complaint I am scared',responses=response)
        self.assertEqual(s.interview.empathy.emotion,'fear')
        self.assertNotIn('I am scared',s.model_dump_json())
        client.chat_handler=None
        c.mouth.prepare_empathy(s,client,s.interview.empathy)
        payload=client.requests[-1]
        self.assertEqual(payload['emotion'],'fear')
        self.assertNotIn('I am scared',json.dumps(payload))
        self.assertNotIn('dialogue',payload)

    def test_empathy_reserves_three_calls_and_separate_action_accounting(self):
        c,s=f.consultation(),f.chief(f.state('ChiefComplaint',initialized=True))
        s.session.call_limit=2
        self.assertFalse(c.budget.can_empathize(s))
        s.session.call_limit=c.budget.collection_calls(s)+1
        self.assertTrue(c.budget.can_empathize(s))
        c.mouth.usage.record_actions(s,50,49,purpose='empathy')
        self.assertEqual(c.budget.interview_actions(s),0)
        self.assertEqual(s.session.usage['ChiefComplaint'].actions,1)

    def test_invalid_empathy_uses_prepared_fallback(self):
        client=f.FakeSDK(chat_handler=lambda p:{'text':'x'*31} if p['task']=='empathy' else None)
        c,s=f.consultation(client),f.chief(f.state())
        event=PendingEmpathy(source_ref='s',emotion='fear',intent='new_distress',key='k')
        s.interview.empathy=event
        c.mouth.prepare_empathy(s,client,event)
        self.assertEqual(s.question().text,c.brain.config.texts.empathy_fallback)


if __name__=='__main__':
    unittest.main()
