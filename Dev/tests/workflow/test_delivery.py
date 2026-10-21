from rdflib import Literal, RDFS
import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import fixtures as f
from education_fixtures import TEXT, education_response
from workflow.education import generate_plan, _EducationWork, parse_plan, references
from workflow.rules.limits import LIMITS
from workflow.state.models import Question


def invalid_joint_utterances(payload):
    if payload['task'] == 'education':
        raw = education_response(payload)
        for rows in raw['P'].values():
            for row in rows:
                row['utterances'] = ['가' * 31]
        return raw


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

    def test_full_source_context_is_preserved_in_plan_request(self):
        source = 'Source text.\n' * 10000
        c = f.consultation(prepared=f.resources(education=True))
        c.knowledge.guidelines.read = lambda disease: ([{'document_id': 'd', 'text': source,
            'relation': 'exact', 'evidence_use': 'care_navigation', 'scope': 'Synthetic full source'}], [])
        state = f.chief(f.state('DifferentialDiagnosis'))
        c.close_collection(state)
        state.interview.current = 'Education'
        c.sessions['Education'].prepare_plan(state, c.client)
        requests = [row for row in c.client.requests if row['task'] == 'education']
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['documents'][0]['text'], source)
        self.assertEqual(len(state.case.plan), 5)

    def test_invalid_render_is_bounded_without_losing_english_plan(self):
        def response(payload):
            if payload['task'] == 'education':
                return invalid_joint_utterances(payload)
            if payload['task']=='education_doctor':
                return {'items':[{'id':r['id'],'utterances':['x'*31]} for r in payload['sentences']]}
        c = f.consultation(f.FakeSDK(chat_handler=response),f.resources(education=True))
        s = f.chief(f.state('Education',initialized=True))
        f.freeze_for_education(c,s)
        c.sessions["Education"].prepare_plan(s,c.client)
        c.sessions['Education'].prepare_delivery(s,c.client)
        self.assertEqual(len(s.case.plan),5)
        self.assertFalse(s.interview.queue)
        self.assertEqual(len([p for p in c.client.requests if p['task']=='education_doctor']),1)
        self.assertEqual(len([a for a in s.interview.answers if a.outcome=='undelivered']),5)
        c.writer.build_soap(s)
        self.assertTrue(all(s.turn.payload['note']['P'].values()))

    def test_provider_render_failure_recovers_once_before_completed_submission(self):
        client = f.FakeSDK(chat_handler=invalid_joint_utterances)
        original, requests = client.chat, []
        def chat(**request):
            payload = f.decode_context(request['messages'][-1]['content'])
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
        repair = f.decode_context(requests[1]['messages'][-1]['content'])
        self.assertEqual(repair['generation_error'], 'PROVIDER_RESPONSE_INVALID')
        self.assertEqual(repair['validation_errors'], {})
        self.assertTrue(all(client.submissions[0]['note']['P'].values()))
        self.assertEqual(client.actions[0]['content'], c.config.texts.intake_questions['onset'])

    def test_repeated_provider_render_failure_retains_cause_and_english_plan(self):
        requests = []
        def response(payload):
            if payload['task'] == 'education':
                return invalid_joint_utterances(payload)
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
            if payload['task'] == 'education':
                return invalid_joint_utterances(payload)
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
        client = f.FakeSDK(chat_handler=response)
        c, s = f.consultation(client, f.resources(education=True)), f.chief(f.state())
        f.freeze_for_education(c, s)
        c.sessions['Education'].prepare_plan(s, client)
        sentences = [{'id': row.id, 'text': row.text} for row in s.case.plan]
        rendered, errors = c.mouth.render_education(s, client, sentences, {row['id']: 1 for row in sentences}, 5)
        self.assertFalse(errors)
        self.assertEqual(len(rendered), 5)
        self.assertEqual(len(requests), 3)
        self.assertNotIn(accepted, {row['id'] for row in requests[2]['sentences']})
        for error in requests[2]['validation_errors'].values():
            self.assertEqual(error['codepoints'], [31])
            self.assertEqual(error['max_codepoints'], 30)
        self.assertEqual(len(s.case.plan), 5)

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
        self.assertTrue(any(a['content'] == c.config.texts.symptom_cause_unknown for a in c.client.actions))

    def test_diagnosis_notice_is_delivered_before_plan_generation(self):
        client = f.FakeSDK()
        notice = []
        def response(payload):
            if payload['task'] == 'education':
                notice.append(client.actions[-1]['content'])
        client.chat_handler = response
        c,s,_ = f.run(client, prepared=f.resources(education=True))
        ident = c.knowledge.term_id(s.case.primary().name, 'Disease')
        expected = c.config.texts.diagnosis_announcement.format(diagnosis=c.knowledge.label(ident))
        self.assertEqual(notice, [expected])
        self.assertEqual(s.interview.answers[-6].question_id, 'Education:diagnosis:0')

    def test_long_diagnosis_notice_uses_the_short_complete_sentence(self):
        k = f.knowledge()
        for label in list(k._graph.objects(f.OW.Alpha, RDFS.label)):
            if label.language == 'ko':
                k._graph.remove((f.OW.Alpha, RDFS.label, label))
        k._graph.add((f.OW.Alpha, RDFS.label, Literal('조금 긴 가상 질환 이름', lang='ko')))
        k._labels.clear()
        c,s = f.consultation(prepared=f.resources(k, education=True)),f.chief(f.state('Education',initialized=True))
        f.freeze(s,kind='disease',name='Disease alpha')
        self.assertTrue(c.sessions['Education'].prepare_diagnosis(s,c.client))
        self.assertEqual(s.interview.queue[0].text, '조금 긴 가상 질환 이름 의심됩니다.')
        self.assertLessEqual(len(s.interview.queue[0].text), 30)
        self.assertFalse(c.client.requests)

    def test_english_diagnosis_label_gets_a_short_korean_notice_without_changing_diagnosis(self):
        def response(payload):
            if payload.get('announcement'):
                self.assertEqual(payload['fixed_diagnosis']['name'], 'Disease alpha')
                return {'items':[{'id':'diagnosis','utterances':['가상질환A가 의심됩니다.']}]}
        k = f.knowledge()
        for label in list(k._graph.objects(f.OW.Alpha, RDFS.label)):
            if label.language == 'ko':
                k._graph.remove((f.OW.Alpha, RDFS.label, label))
        k._graph.add((f.OW.Alpha, RDFS.label, Literal('Long English display name for disease alpha')))
        k._labels.clear()
        c,s = f.consultation(f.FakeSDK(chat_handler=response),f.resources(k,education=True)),f.chief(f.state('Education',initialized=True))
        f.freeze(s,kind='disease',name='Disease alpha')
        before = s.case.model_dump()
        self.assertTrue(c.sessions['Education'].prepare_diagnosis(s,c.client))
        self.assertEqual(s.interview.queue[0].text, '가상질환A가 의심됩니다.')
        self.assertEqual(s.case.model_dump(), before)

    def test_fatal_announcement_error_does_not_start_plan_generation(self):
        requests = []
        def response(payload):
            requests.append(payload)
            raise f.NovaError('API_UNAVAILABLE')
        k = f.knowledge()
        for label in list(k._graph.objects(f.OW.Alpha, RDFS.label)):
            if label.language == 'ko':
                k._graph.remove((f.OW.Alpha, RDFS.label, label))
        k._graph.add((f.OW.Alpha, RDFS.label, Literal('Long English display name for disease alpha')))
        k._labels.clear()
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
            if payload['task'] == 'education':
                raw = education_response(payload)
                for rows in raw['P'].values():
                    rows[0]['utterances'] = ['전제 조건을 확인해요.', '그 외에는 약을 드세요.']
                return raw
            if payload['task']=='education_doctor':
                return {'items':[{'id':r['id'],'utterances':['전제 조건을 확인해요.','그 외에는 약을 드세요.']}
                                 for r in payload['sentences']]}
        c = f.consultation(f.FakeSDK(chat_handler=response),f.resources(education=True))
        s = f.chief(f.state('Education',initialized=True))
        f.freeze_for_education(c,s)
        c.sessions["Education"].prepare_plan(s,c.client)
        c.sessions['Education'].prepare_delivery(s,c.client)
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
        f.freeze_for_education(c,s)
        c.sessions["Education"].prepare_plan(s,c.client)
        c.sessions["Education"].prepare_plan(s,c.client)
        self.assertEqual(count,2)
        self.assertEqual(len(s.case.plan),4)
        self.assertEqual(s.interview.education_status,'partial')

    def test_education_fixes_one_diagnosis_and_ignores_late_emotion(self):
        c,s = f.consultation(prepared=f.resources(education=True)),f.chief(f.state('Education'))
        f.freeze_for_education(c,s)
        c.sessions["Education"].prepare_plan(s,c.client)
        before = s.case.model_dump()
        q = Question(item_id='education',purpose='education',text='계획을 안내드릴게요.',plan_sentence_id=s.case.plan[0].id)
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        s.turn.stage,s.turn.response='received',{'content':'New disease and fear','turn':1}
        calls = s.session.doctor_calls
        c.ear.process_input(s,c.knowledge,c.client)
        c.refresh_after_input(s)
        self.assertEqual(s.case.model_dump(),before)
        self.assertEqual(s.session.doctor_calls,calls)
        self.assertIsNone(s.turn)

    def test_education_can_deliver_prepared_questions_without_models(self):
        c,s = f.consultation(prepared=f.resources(education=True)),f.chief(f.state('Education',initialized=True))
        f.freeze_for_education(c,s)
        c.sessions["Education"].prepare_plan(s,c.client)
        c.sessions['Education'].prepare_delivery(s,c.client)
        s.session.models_available=False
        q=s.interview.queue[0]
        c.interactions.select_question(s,q)
        c.mouth.validate_action(s)
        c.mouth.execute_action(s,c.client)
        c.ear.process_input(s,c.knowledge,c.client)
        self.assertEqual(s.interview.answers[-1].outcome,'delivered')


if __name__=='__main__':
    unittest.main()
