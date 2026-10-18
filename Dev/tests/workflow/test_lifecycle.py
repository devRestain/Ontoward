import copy
import json
import unittest
from unittest.mock import patch

import fixtures as f
from workflow.graph import run_node, route_budget
from workflow.state.models import Question, TurnContext
from workflow.rules.limits import SESSION_INTERVIEW_LIMITS


class LifecycleTests(unittest.TestCase):
    def test_complete_workflow_owns_only_live_work(self):
        c,s,updates = f.run()
        self.assertEqual(s.session.termination,'submitted')
        self.assertEqual(len(c.client.submissions),1)
        self.assertIsNone(s.turn)
        self.assertFalse(s.interview.queue)
        self.assertTrue(s.case.diagnosis)
        for name,raw in updates:
            self.assertEqual(set(raw),{'case','interview','session','turn'})
            if name in {'process_initial_input','process_input','refresh_after_input','finish'}:
                self.assertIsNone(raw['turn'])
            self.assertNotIn('model_history',json.dumps(raw))
            for q in raw['interview']['queue']:
                self.assertNotIn('assessment',q)
            for answer in raw['interview']['answers']:
                self.assertNotIn('text',answer)
                self.assertNotIn('question',answer)
                self.assertNotIn('response',answer)
        self.assertGreater(len(c.interpreter.dialogue),1)
        self.assertNotIn('확인한 환자 응답',s.model_dump_json())
        c.release()
        self.assertFalse(c.interpreter.dialogue)
        self.assertIsNone(c.reasoner._snapshot)

    def test_question_registration_and_cancellation_never_write_patient_state(self):
        s,c = f.chief(f.state()),f.consultation()
        before = s.case.model_dump()
        q = Question(item_id='q',purpose='hpi',text='위치가 어디인가요?',target='Test complaint',attribute='Location')
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        c.questions.discard_unasked(s,{'q'})
        c.questions.discard_unasked(s,{'q'})
        self.assertEqual(s.case.model_dump(),before)
        self.assertIsNone(s.turn)
        self.assertFalse(s.interview.queue)

    def test_executing_question_cannot_be_discarded(self):
        s,c = f.state(),f.consultation()
        q = Question(item_id='q',purpose='chief',text='증상이 있나요?')
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        s.turn.stage = 'received'
        before = s.model_dump()
        with self.assertRaises(ValueError):
            c.questions.discard_unasked(s,{'q'})
        self.assertEqual(s.model_dump(),before)

    def test_answer_replaces_question_and_deduplicates_same_delivery(self):
        q = Question(item_id='q',purpose='intake',text='치료받으셨나요?',category='previous_care',coverage=True)
        s,c,client = f.interpret([f.statement('No treatment',record_category='previous_care',assertion='absent',
            note_value='No previous treatment')],q=q)
        self.assertFalse(s.interview.queue)
        self.assertIsNone(s.turn)
        a = s.interview.answers[0]
        self.assertEqual(a.outcome,'recorded')
        c.questions.complete(s,q,a.source_ref,outcome='recorded')
        self.assertEqual(len(s.interview.answers),1)

    def test_node_copy_isolation_and_return_validation(self):
        s = f.chief(f.state())
        before = s.model_dump()
        output = run_node(s,lambda value:value.case.apply([f.fact('other',target='Other symptom')]))
        self.assertEqual(s.model_dump(),before)
        self.assertIn('other',output['case']['facts'])
        def bad(value):
            value.session.usage['Initiation'].actions = -1
            value.interview.queue.append({'invalid':True})
        with self.assertRaises(ValueError):
            run_node(s,bad)
        self.assertEqual(s.model_dump(),before)

    def test_one_reasoner_shared_and_only_latest_snapshot_retained(self):
        c,s = f.consultation(),f.chief(f.state())
        self.assertIs(c.reasoner,c.planner.reasoner)
        self.assertIs(c.reasoner,c.writer.reasoner)
        first = c.reasoner.refresh_hypotheses(s)
        self.assertIs(first,c.reasoner.refresh_hypotheses(s))
        s.case.apply([f.fact('attr',kind='attribute',attribute='Location',values=('head',),category=None)])
        second = c.reasoner.refresh_hypotheses(s)
        self.assertIsNot(first,second)
        self.assertIs(c.reasoner._snapshot,second)
        self.assertNotIn('hypotheses',s.model_dump_json())

    def test_cold_cache_and_audit_parity(self):
        a,sa,ua = f.run()
        events = []
        b,sb,ub = f.run(audit=lambda event,**data:events.append(event),cache=False)
        self.assertEqual(sa.model_dump(),sb.model_dump())
        self.assertEqual(a.client.actions,b.client.actions)
        self.assertEqual(a.client.submissions,b.client.submissions)
        self.assertTrue(events)
        def fail(*args,**kwargs):
            raise OSError('recording unavailable')
        c,sc,uc = f.run(audit=fail)
        self.assertEqual(sa.model_dump(),sc.model_dump())
        self.assertEqual(a.client.actions,c.client.actions)
        self.assertEqual(len(c.client.submissions),1)

    def test_session_caps_and_no_future_session_queue(self):
        c,s,updates = f.run()
        for name,raw in updates:
            interview = raw['interview']
            if interview['current'] != 'Education':
                self.assertFalse(any(q['purpose']=='education' for q in interview['queue']))
        for scope,usage in s.session.usage.items():
            self.assertLessEqual(usage.actions-usage.empathy_actions,SESSION_INTERVIEW_LIMITS[scope][1])

    def test_expiry_and_last_response_processing(self):
        client = f.FakeSDK()
        c = f.consultation(client)
        s = c.nova_session.initialize_case(client)
        s.session.deadline = f.FIXED
        c.check_budget(s)
        self.assertEqual(s.session.termination,'expired')
        s = f.chief(f.state(turns=0))
        q = Question(item_id='last',purpose='hpi',text='어떤 느낌인가요?',target='Test complaint',attribute='Quality',
            observation_id='obs1',episode_id='episode1',time_context='current')
        s,c,client = f.interpret([f.statement('dull',focus='attribute',attribute_terms=['Quality'],value_terms=['dull'])],s=s,q=q)
        client.remaining = 0
        self.assertTrue(any(fact.values==('dull',) for fact in s.case.facts.values()))
        c.check_budget(s)
        self.assertTrue(s.session.finalizing)
        self.assertIsNone(s.turn)

    def test_budget_evaluation_is_pure_and_preserves_open_inquiry(self):
        s = f.chief(f.state('ChiefComplaint',turns=18,initialized=True))
        c = f.consultation()
        c.planner.prepare_chief_complaint(s)
        before = s.model_dump()
        decision = c.budget.evaluate(s)
        self.assertEqual(s.model_dump(),before)
        kept = [q for q in s.interview.queue if q.item_id not in decision.discard]
        self.assertTrue(any(q.purpose=='open_inquiry' for q in kept))

    def test_collection_completion_routes_through_normal_education(self):
        from workflow.graph import build_graph
        from workflow.state.models import WorkflowState
        c = f.consultation(prepared=f.resources(education=True))
        s = f.chief(f.state('DifferentialDiagnosis',initialized=True))
        s.session.finalizing = True
        result = build_graph(c,c.planner.knowledge).invoke(s.model_dump(mode='json'),
            {'recursion_limit':c.budget.graph_step_limit(s)})
        done = WorkflowState.model_validate(result)
        self.assertEqual(done.session.termination, 'submitted')
        self.assertGreaterEqual(done.session.usage['Education'].actions, 6)
        self.assertEqual(done.interview.collection['DifferentialDiagnosis:completion'], 'collection_complete')
        self.assertTrue(c.client.actions[0]['content'].endswith('질환이 의심됩니다.'))
        self.assertTrue(all(c.client.submissions[0]['note']['P'].values()))

    def test_model_budget_stop_still_allows_prepared_diagnosis_notice(self):
        from workflow.graph import build_graph
        from workflow.state.models import WorkflowState
        c = f.consultation(prepared=f.resources(education=True))
        s = f.chief(f.state('DifferentialDiagnosis',initialized=True))
        s.session.models_available = False
        s.session.doctor_successes = 1
        result = build_graph(c,c.planner.knowledge).invoke(s.model_dump(mode='json'),
            {'recursion_limit':c.budget.graph_step_limit(s)})
        done = WorkflowState.model_validate(result)
        self.assertEqual(done.session.termination, 'submitted')
        self.assertEqual(done.interview.collection['DifferentialDiagnosis:completion'], 'model_call_budget')
        self.assertEqual(len(c.client.actions), 1)
        self.assertTrue(c.client.actions[0]['content'].endswith('질환이 의심됩니다.'))

    def test_time_or_turn_budget_stop_does_not_start_education_actions(self):
        for turns, seconds in ((0, 500), (20, 200)):
            with self.subTest(turns=turns):
                from datetime import timedelta
                c,s = f.consultation(prepared=f.resources(education=True)),f.chief(f.state('DifferentialDiagnosis',turns=turns,initialized=True))
                s.session.deadline = f.FIXED + timedelta(seconds=seconds)
                c.client.remaining, c.client.deadline = turns, s.session.deadline
                c.check_budget(s)
                self.assertTrue(s.session.finalizing)
                self.assertEqual(route_budget(s), 'build_soap')
                self.assertFalse(c.client.actions)

    def test_chief_change_invalidates_old_question_binding(self):
        s,c = f.chief(f.state('ChiefComplaint',initialized=True)),f.consultation()
        c.planner.prepare_chief_complaint(s)
        old = {q.item_id for q in s.interview.queue if q.purpose=='hpi'}
        new = f.fact('replacement',target='Other symptom',observation_id='obs2',episode_id='episode2')
        s.case.apply([new],preferred=new.id)
        c.planner.prepare_chief_complaint(s)
        self.assertFalse(old & {q.item_id for q in s.interview.queue})
        self.assertEqual(s.case.chief().id,'replacement')
        self.assertIn('chief',s.case.facts)

    def test_submission_payload_is_local_until_confirmed(self):
        s,c = f.chief(f.state()),f.consultation()
        s.session.doctor_successes = 1
        c.freeze_diagnosis(s)
        c.writer.build_soap(s)
        self.assertEqual(s.turn.kind,'submission')
        self.assertEqual(set(s.case.model_dump()),{'facts','notes','chief_fact_id','diagnosis','plan','revision'})
        c.writer.validate_submission(s)
        c.writer.submit_diagnosis(s)
        c.writer.confirm_submission(s)
        self.assertEqual(s.session.termination,'submitted')
        self.assertIsNone(s.turn)
        self.assertEqual(s.session.receipt['status'],'completed')


if __name__=='__main__':
    unittest.main()
