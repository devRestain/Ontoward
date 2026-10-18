from datetime import timedelta
import copy
import json
import unittest
from unittest.mock import patch

import fixtures as f
from workflow.graph import run_node
from workflow.io.model_client import ModelResult
from workflow.rules.action import content_error
from workflow.rules.submission import validate_payload
from workflow.state.models import Question


class TransportTests(unittest.TestCase):
    def test_transient_replay_keeps_request_identity_and_accounts_once(self):
        c,s = f.consultation(),f.state()
        attempts,calls,delays=[],[],[]
        c.mouth.executor.sleep=delays.append
        def chat(**request):
            calls.append(copy.deepcopy(request))
            if len(calls)==1:
                raise f.NovaError('REQUEST_PENDING')
            return f.FakeSDK.completion('{}')
        c.client.chat=chat
        result=c.ear.model.complete(s,c.client,role='gateway',messages=[{'role':'user','content':'{}'}])
        self.assertEqual(result.content,'{}')
        self.assertEqual(calls[0],calls[1])
        self.assertEqual(delays,[2])
        self.assertEqual((s.session.doctor_calls,s.session.doctor_successes,s.session.input_tokens,s.session.output_tokens),(1,1,20,10))
        self.assertEqual(c.client.timeout,120)

    def test_exhausted_transient_stops_before_actions_or_submission(self):
        client=f.FakeSDK()
        client.chat=lambda **kw:(_ for _ in ()).throw(f.NovaError('REQUEST_PENDING'))
        c,s,_=f.run(client)
        self.assertEqual(s.session.termination,'unknown')
        self.assertFalse(client.actions)
        self.assertFalse(client.submissions)
        self.assertIsNone(s.turn)

    def test_truncation_returns_typed_failure_without_partial_content(self):
        c,s=f.consultation(),f.state()
        c.client.chat=lambda **kw:f.FakeSDK.completion('{"partial":',finish_reason='length')
        result=c.ear.model.complete(s,c.client,role='gateway',messages=[])
        self.assertIsNone(result.content)
        self.assertEqual(result.error,'OUTPUT_TRUNCATED')
        self.assertTrue(result.request_id)
        self.assertEqual(s.session.doctor_calls,1)
        self.assertEqual(s.session.output_tokens,10)

    def test_context_truncation_uses_one_larger_recovery(self):
        requests=[]
        def handler(payload):
            requests.append(payload)
            if len(requests)==1:
                return f.FakeSDK.completion('partial',finish_reason='length')
            return {'statements':[f.statement('Complaint')]}
        s,c,_=f.interpret([],text='Complaint',responses=handler)
        self.assertEqual([p['phase'] for p in requests],['context','context_repair'])
        self.assertTrue(s.case.chief())

    def test_malformed_usage_disables_models_without_false_success(self):
        c,s=f.consultation(),f.state()
        c.client.chat=lambda **kw:{'choices':[{'message':{'content':'{}'}}]}
        result=c.ear.model.complete(s,c.client,role='gateway',messages=[])
        self.assertEqual(result.error,'invalid_model_response')
        self.assertFalse(s.session.models_available)
        self.assertEqual(s.session.doctor_successes,0)

    def test_action_transient_replay_and_format_error_are_not_reissued(self):
        c,s=f.consultation(),f.state()
        q=Question(item_id='q',purpose='greeting',text='안녕하세요.')
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        c.mouth.validate_action(s)
        original,calls=c.client.say,[]
        def say(**body):
            calls.append(body.copy())
            if len(calls)==1:
                raise f.NovaError('REQUEST_PENDING')
            return original(**body)
        c.client.say=say
        c.mouth.execute_action(s,c.client)
        self.assertEqual(calls[0],calls[1])
        self.assertEqual(s.session.usage['Initiation'].actions,1)
        c.ear.process_input(s,c.brain.knowledge,c.client)
        self.assertIsNone(s.turn)
        c.interactions.select_question(s,q)
        c.questions.register(s,q)
        c.mouth.validate_action(s)
        calls.clear()
        def malformed(**body):
            calls.append(body)
            raise f.NovaError('PATIENT_RESPONSE_INVALID')
        c.client.say=malformed
        c.mouth.execute_action(s,c.client)
        c.ear.process_input(s,c.brain.knowledge,c.client)
        self.assertEqual(len(calls),1)
        self.assertIsNone(s.turn)

    def test_late_budget_gate_never_transmits_an_expired_question(self):
        c,s=f.consultation(),f.state()
        q=Question(item_id='q',purpose='chief',text='증상이 있나요?')
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        c.mouth.validate_action(s)
        s.session.deadline=f.FIXED
        c.mouth.execute_action(s,c.client)
        self.assertFalse(c.client.actions)
        self.assertEqual(s.session.termination,'expired')

    def test_observation_failure_does_not_replay_external_action(self):
        def fail(*a,**kw):
            raise OSError('disk full')
        c,s=f.consultation(audit=fail),f.state()
        q=Question(item_id='q',purpose='greeting',text='안녕하세요.')
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        c.mouth.validate_action(s)
        raw=run_node(s,lambda value:c.mouth.execute_action(value,c.client))
        self.assertEqual(len(c.client.actions),1)
        self.assertEqual(raw['turn']['stage'],'received')

    def test_soap_repair_has_one_local_payload_and_new_request_id(self):
        c,s=f.consultation(),f.chief(f.state())
        s.session.doctor_successes=1
        c.close_collection(s)
        c.writer.build_soap(s)
        s.turn.payload['note']['S'].pop('cc')
        c.writer.validate_submission(s)
        self.assertEqual(s.turn.error,'invalid_soap_fields')
        c.repair_submission(s)
        c.writer.validate_submission(s)
        self.assertIsNone(s.turn.error)
        self.assertEqual(s.turn.repairs,1)
        with self.assertRaises(ValueError):
            c.writer.begin_repair(s)
        c.writer.submit_diagnosis(s)
        c.writer.confirm_submission(s)
        self.assertEqual(s.session.termination,'submitted')

    def test_server_soap_repair_and_unconfirmed_submission_boundaries(self):
        c,s=f.consultation(),f.chief(f.state())
        s.session.doctor_successes=1
        c.close_collection(s)
        c.writer.build_soap(s)
        calls=[]
        def diagnose(**payload):
            calls.append(copy.deepcopy(payload))
            if len(calls)==1:
                raise f.NovaError('INVALID_RECORD_FIELDS')
            return {'status':'completed'}
        c.client.diagnose=diagnose
        c.writer.submit_diagnosis(s)
        c.repair_submission(s)
        c.writer.submit_diagnosis(s)
        c.writer.confirm_submission(s)
        self.assertEqual(s.session.termination,'submitted')
        self.assertEqual(calls[0]['note'],calls[1]['note'])
        self.assertNotEqual(calls[0]['request_id'],calls[1]['request_id'])
        c,s=f.consultation(),f.chief(f.state())
        s.session.doctor_successes=1
        c.close_collection(s)
        c.writer.build_soap(s)
        c.client.diagnose=lambda **kw:{'status':'pending'}
        c.writer.submit_diagnosis(s)
        c.writer.confirm_submission(s)
        self.assertEqual(s.session.termination,'unknown')
        self.assertIsNone(s.turn)

    def test_actual_soap_fields_and_no_tests_or_unearned_doctor_success(self):
        c,s=f.consultation(),f.chief(f.state())
        f.freeze(s)
        c.writer.build_soap(s)
        with self.assertRaisesRegex(ValueError,'doctor_call_required'):
            validate_payload(s)
        s.session.doctor_successes=1
        validate_payload(s)
        payload=s.turn.payload
        self.assertEqual(sum(len(fields) for fields in payload['note'].values()),15)
        self.assertEqual(payload['note']['O']['tests'],'')
        payload['note']['O']['tests']='invented'
        with self.assertRaisesRegex(ValueError,'invalid_soap_content'):
            validate_payload(s)

    def test_shared_resources_do_not_share_dialogue_or_decision_attempts(self):
        resources=f.resources()
        a,b=f.consultation(prepared=resources),f.consultation(prepared=resources)
        s=f.chief(f.state())
        a.brain.refresh_assessment(s,a.client)
        a.ear.dialogue.append({'id':'private','patient':'secret'})
        self.assertIsNone(b.brain._attempted)
        self.assertFalse(b.ear.dialogue)
        self.assertIs(a.brain.knowledge,b.brain.knowledge)


if __name__=='__main__':
    unittest.main()
