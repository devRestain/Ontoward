"""Bounded offline recovery: real input custody, finite progress and honest receipts."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import fixtures as f
from workflow.doctor_brain import ModelResult
from workflow.input_types import ContextInput, ContextStatement
from workflow.rules.chief import force_chief
from workflow.rules.decision import bound_graph_input
from workflow.rules.submission import validate_wire_payload
from workflow.state.models import Answer, CaseFact, DifferentialEntry, Assessment, PlanSentence, Question, TurnContext
from inspection import outcome_metrics


class CompletionTests(unittest.TestCase):
    def test_dump_and_cleanup_errors_cannot_replace_actual_receipt(self):
        from workflow.runtime import consult
        from workflow.state.models import WorkflowState
        c = f.consultation()
        with patch('workflow.runtime.assemble_consultation', return_value=c), \
             patch.object(WorkflowState, 'model_dump', side_effect=ValueError('dump fault')), \
             patch.object(c, 'release', side_effect=OSError('cleanup fault')):
            result = consult(c.client, f.resources())
        self.assertEqual(result['session']['termination'], 'submitted')
        self.assertEqual(result['session']['receipt']['status'], 'completed')
        validate_wire_payload(result['session']['final_payload'])

    def test_invalid_first_session_returns_honest_missing_case(self):
        from workflow.runtime import consult
        c = f.consultation()
        c.client.session = Mock(side_effect=f.NovaError('API_UNAVAILABLE'))
        with patch('workflow.runtime.assemble_consultation', return_value=c):
            result = consult(c.client, f.resources())
        self.assertEqual(result['session']['termination'], 'unknown')
        self.assertIsNone(result['session']['final_payload'])
        self.assertIsNone(result['session']['receipt'])
        self.assertFalse(c.client.submissions)

    def test_original_sdk_io_and_nonobject_error_are_narrowly_normalized(self):
        from nova_sdk import Client
        from workflow.io.sdk_boundary import sdk_call
        client = Client(api_base='http://offline.invalid', token='fixture', session_id='offline')
        for raw in (OSError('read fault'), b'{"error":"nonobject"}'):
            response = Mock()
            response.status = 503
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            if isinstance(raw, Exception):
                response.read.side_effect = raw
            else:
                response.read.return_value = raw
            with patch.object(client, '_open', return_value=response), self.assertRaises(f.NovaError) as error:
                sdk_call(client.session)
            self.assertEqual(error.exception.code, 'API_UNAVAILABLE' if isinstance(raw, Exception) else 'INVALID_API_RESPONSE')
        with self.assertRaises(AttributeError):
            sdk_call(lambda: getattr(object(), 'missing'))

    def test_one_failed_action_is_consumed_and_independent_actions_continue(self):
        client = f.FakeSDK()
        original, calls = client.say, []
        failed_id = None
        def say(**request):
            nonlocal failed_id
            calls.append(copy.deepcopy(request))
            if failed_id is None:
                failed_id = request['request_id']
            if request['request_id'] == failed_id:
                raise f.NovaError('API_UNAVAILABLE')
            return original(**request)
        client.say = say
        c, s, _ = f.run(client)
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(sum(row['request_id'] == failed_id for row in calls), 2)
        self.assertTrue(client.actions)
        failed = next(row for row in s.interview.answers if row.source_ref == failed_id)
        self.assertEqual((failed.outcome, failed.turn, failed.response), ('undelivered', None, {'error': 'API_UNAVAILABLE'}))
        self.assertEqual(sum(row.actions for row in s.session.usage.values()), len(client.actions))
        self.assertFalse(any(fact.source_ref == failed_id for fact in s.case.facts.values()))

    def test_received_reply_survives_parser_exception_without_replay(self):
        c, s = f.consultation(), f.chief(f.state('ChiefComplaint', initialized=True))
        q = Question(item_id='bad-input', purpose='hpi', target='Test complaint', attribute='Location', text='어디가 불편한가요?')
        c.questions.register(s, q)
        c.interactions.select_question(s, q)
        c.mouth.validate_action(s)
        c.mouth.execute_action(s, c.client)
        source, raw = s.turn.request_id, copy.deepcopy(s.turn.response)
        with patch.object(c.ear, '_parse_text', side_effect=ValueError('parse fault')):
            c.accept_input(s)
        answer = next(row for row in s.interview.answers if row.question_id == q.item_id)
        self.assertEqual((answer.source_ref, answer.response, answer.turn, answer.outcome), (source, raw, 1, 'unknown'))
        self.assertEqual(len(c.client.actions), 1)
        c.questions.register(s, q)
        self.assertFalse(any(row.item_id == q.item_id for row in s.interview.queue))
        self.assertIn('chief', s.case.facts)

    def test_unsent_question_has_no_answer_and_cannot_revive(self):
        c, s = f.consultation(), f.chief(f.state('ChiefComplaint', initialized=True))
        c.sessions['ChiefComplaint'].prepare(s)
        q = next(row for row in s.interview.queue if row.attribute)
        c.interactions.select_question(s, q)
        c.questions.pass_step(s, 'local_validation')
        self.assertFalse(s.interview.answers)
        self.assertFalse(c.client.actions)
        c.sessions['ChiefComplaint'].prepare(s)
        self.assertFalse(any(row.semantic_key() == q.semantic_key() for row in s.interview.queue))
        self.assertEqual(c.tools.chief_statuses(s)[q.attribute], 'passed_unasked')

    def test_prepare_and_close_faults_advance_to_minimal_submission(self):
        c = f.consultation()
        s = c.nova_session.initialize_case(c.client)
        c.sessions['Initiation'].prepare = Mock(side_effect=ValueError('prepare fault'))
        c.sessions['ChiefComplaint'].close = Mock(side_effect=ValueError('close fault'))
        c.differential.close = Mock(side_effect=ValueError('freeze fault'))
        c.writer.build_record_view = Mock(side_effect=ValueError('projection fault'))
        c.run(s)
        self.assertEqual(s.session.termination, 'submitted')
        validate_wire_payload(s.session.final_payload)
        self.assertEqual(s.session.final_payload['diagnosis'], s.case.diagnosis)
        self.assertTrue(s.session.final_payload['note']['S']['cc'])
        self.assertTrue(s.case.assessment.frozen)

    def test_final_get_failure_does_not_block_post_and_diagnosis_stays_fixed(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.close_collection(s)
        diagnosis = s.case.diagnosis
        c.writer.build_soap(s)
        c.client.session = Mock(side_effect=f.NovaError('API_UNAVAILABLE'))
        c.writer.submit_diagnosis(s)
        c.writer.confirm_submission(s)
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(c.client.submissions[0]['diagnosis'], diagnosis)

    def test_unknown_submission_keeps_same_id_body_and_payload(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.close_collection(s)
        c.writer.build_soap(s)
        requests = []
        def fail(**body):
            requests.append(copy.deepcopy(body))
            raise f.NovaError('API_UNAVAILABLE')
        c.client.diagnose = fail
        c.finish_submission(s)
        self.assertEqual(s.session.termination, 'unknown')
        self.assertIsNone(s.session.receipt)
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(s.turn.request_id, s.session.submission_request_id)
        self.assertEqual(s.turn.payload, s.session.final_payload)
        validate_wire_payload(s.turn.payload)

    def test_malformed_receipt_recovers_identical_request(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.close_collection(s)
        c.writer.build_soap(s)
        requests = []
        def diagnose(**body):
            requests.append(copy.deepcopy(body))
            return [] if len(requests) == 1 else {'status': 'completed'}
        c.client.diagnose = diagnose
        c.finish_submission(s)
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(requests[0], requests[1])

    def test_closed_get_never_becomes_a_receipt_but_preserves_payload(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.close_collection(s)
        c.writer.build_soap(s)
        c.client.status = 'completed'
        c.writer.submit_diagnosis(s)
        self.assertEqual(s.session.termination, 'closed')
        self.assertIsNone(s.session.receipt)
        self.assertFalse(c.client.submissions)
        validate_wire_payload(s.session.final_payload)

    def test_minimal_payload_really_shrinks_oversized_note_without_model(self):
        c, s = f.consultation(), f.chief(f.state())
        c.close_collection(s)
        calls = len(c.client.requests)
        for index in range(600):
            s.case.facts[str(index)] = CaseFact(id=str(index), category='other', value='Preserved observation ' + str(index) + ' x' * 150,
                                              status='unknown', source_ref='received')
        c.writer.build_minimal(s, 'record_too_large')
        payload = s.turn.payload
        validate_wire_payload(payload)
        self.assertLessEqual(len(json.dumps(payload['note'], ensure_ascii=False).encode()), 100000)
        self.assertEqual(payload['note']['O']['tests'], '')
        self.assertEqual(len(c.client.requests), calls)
        self.assertEqual(payload['diagnosis'], s.case.diagnosis)

    def test_education_error_is_undelivered_and_plan_is_retained(self):
        c, s = f.consultation(prepared=f.resources(education=True)), f.chief(f.state('Education'))
        f.freeze(s)
        s.case.plan = [PlanSentence(id='p1', field='education', text='Discuss follow-up.', basis='model_knowledge')]
        q = Question(item_id='Education:p1:0', purpose='education', text='추적 진료를 확인해요.', plan_sentence_id='p1')
        c.questions.register(s, q)
        c.interactions.select_question(s, q)
        s.turn.response, s.turn.stage = {'error': 'API_UNAVAILABLE'}, 'received'
        c.ear.process_input(s, c.knowledge, c.client)
        self.assertEqual(s.interview.answers[0].outcome, 'undelivered')
        self.assertEqual(len(s.case.plan), 1)


class ChiefAndContextTests(unittest.TestCase):
    def test_route_unknown_answer_is_not_prepared_again(self):
        c, s = f.consultation(), f.state('ChiefComplaint', initialized=True)
        force_chief(s, c.knowledge, c.config)
        c.sessions['ChiefComplaint'].prepare(s)
        q = next(row for row in s.interview.queue if row.attribute)
        c.interactions.select_question(s, q)
        s.turn.response, s.turn.stage = {'status': 'OK', 'content': '모르겠어요', 'turn': 1}, 'received'
        c.ear.process_input(s, c.knowledge, c.client)
        c.sessions['ChiefComplaint'].prepare(s)
        self.assertEqual(c.tools.chief_statuses(s)[q.attribute], 'unknown')
        self.assertFalse(any(row.semantic_key() == q.semantic_key() for row in s.interview.queue))

    def test_demographic_changes_corrections_and_different_units_are_not_echoes(self):
        from workflow.input_types import PatientContextFact
        known = [dict(context_key='age', subject='patient', value='1 year', status='present',
                      measurement=dict(kind='quantity', value=1, unit='year'))]
        c = f.consultation()
        for changes in (dict(measurement=dict(kind='quantity', value=1, unit='month')),
                        dict(correction=True), dict(subject='family', subject_member='mother')):
            row = PatientContextFact.model_validate(dict(key='age', value='1 year', quote='earlier',
                measurement=dict(kind='quantity', value=1, unit='year'), **{key: value for key, value in changes.items() if key != 'measurement'})
                | ({'measurement': changes['measurement']} if 'measurement' in changes else {}))
            self.assertFalse(c.ear._demographic_echo(row, known))

    def test_forced_chief_has_eight_candidates_one_call_no_fabricated_fact(self):
        for content in ('{}', '{"symptom_ref":"outside"}', '{"symptom_ref":"s_1"}'):
            c, s = f.consultation(), f.state()
            s.case.presenting_text = 'No lexical match in this fixture'
            brain = Mock()
            brain.complete.return_value = ModelResult(content=content)
            force_chief(s, c.knowledge, c.config, brain, c.client)
            force_chief(s, c.knowledge, c.config, brain, c.client)
            brain.complete.assert_called_once()
            data = json.loads(brain.complete.call_args.kwargs['messages'][-1]['content'])
            self.assertLessEqual(len(data['candidates']), 8)
            self.assertTrue(c.knowledge.has_type(s.case.chief_route.target_id, 'Symptom'))
            self.assertFalse(s.case.facts)
            self.assertIsNone(s.case.chief(confirmed=True))
            self.assertEqual(s.case.chief_route.method, 'stable_order')
            c.differential.close(s, c.client, allow_model=False)
            self.assertEqual(s.case.diagnosis, 'Undifferentiated presenting complaint')
            self.assertFalse(s.case.primary().supports)

    def test_normal_chief_uses_no_force_call(self):
        c, s = f.consultation(), f.chief(f.state())
        brain = Mock()
        force_chief(s, c.knowledge, c.config, brain, c.client)
        brain.complete.assert_not_called()
        self.assertIsNone(s.case.chief_route)

    def test_ungrounded_same_demographic_echo_does_not_repair_valid_sibling(self):
        c, s = f.consultation(), f.state()
        s.case.apply([CaseFact(id='patient_context:patient::sex', category='patient_context', context_key='sex',
            value='female', source_ref='initial:opening', acquisition='initial')])
        def response(payload):
            return dict(statements=[f.statement('Complaint')], patient_context=[dict(key='sex', value='female', quote='earlier female')])
        s, c, client = f.interpret([], s=s, text='Complaint', responses=response)
        self.assertEqual(len(client.requests), 1)
        self.assertIn('known_patient_context', client.requests[0])
        self.assertNotIn('patient_context', client.requests[0])
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertEqual(s.case.facts['patient_context:patient::sex'].source_ref, 'initial:opening')

    def test_partial_null_or_missing_area_keeps_sibling_and_original_anchor_slots(self):
        c = f.consultation()
        previous = ContextInput(statements=[ContextStatement(**f.statement('Complaint')),
            ContextStatement(quote='bad', role='unknown'), ContextStatement(**f.statement('Detail', focus='attribute', anchor=1))])
        payload = dict(records=[], question=None)
        for raw in ({'statements': [None]}, {}, {'statements': []}):
            context, errors = c.ear._read_context(raw, payload, 'Complaint bad Detail', previous, [1], [])
            self.assertEqual(len(context.statements), 3)
            self.assertEqual(context.statements[0], previous.statements[0])
            self.assertEqual(context.statements[1].role, 'unknown')
            self.assertEqual(context.statements[2].role, 'unknown')
            self.assertFalse(errors)
        raw = dict(statements=[None, None], patient_context=[dict(key='sex', value='female', quote='female')])
        context, errors = c.ear._read_context(raw, payload, 'female', previous, [1], [0])
        self.assertEqual(context.patient_context[0].value, 'female')
        self.assertTrue(any(row['area'] == 'statements' for row in errors))


class PacketLimitTests(unittest.TestCase):
    def test_large_graph_packet_has_fifty_complete_records_and_closed_references(self):
        payload = dict(facts={'f1': dict(scope='s1')}, scopes={f's{i}': dict(subject='patient') for i in range(1, 107)},
            conditions={f'c{i}': [dict(status='present')] for i in range(111)},
            relations={f'r{i}': dict(full_pattern=[dict(expected='complete criterion')], applicability=f'c{i}') for i in range(111)},
            evidence={f'e{i}': dict(relation=f'r{i % 111}', facts=['f1'], scope=f's{1 + i % 106}') for i in range(113)},
            candidates=[dict(ref='d1', supports=[f'e{i}' for i in range(113)], against=[], unresolved=[])],
            questions=[dict(ref=f'q{i}', scope=f's{1 + i % 106}', expected_by_disease={'d1': [dict(relation=f'r{i % 111}', feature=0)]}) for i in range(99)],
            input_limits={})
        bound_graph_input(payload)
        for key in ('relations', 'evidence', 'questions', 'scopes', 'conditions'):
            self.assertLessEqual(len(payload[key]), 50, key)
        self.assertEqual(len(payload['facts']), 1)
        for row in payload['evidence'].values():
            self.assertIn(row['relation'], payload['relations'])
            self.assertIn(row['scope'], payload['scopes'])
        for row in payload['questions']:
            for entries in row['expected_by_disease'].values():
                for entry in entries:
                    self.assertIn(entry['relation'], payload['relations'])
        self.assertTrue(all(row['full_pattern'] == [dict(expected='complete criterion')] for row in payload['relations'].values()))

    def test_clinical_workset_ten_and_note_five_differentials(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        for index in range(20):
            node = f.OW[f'Candidate{index}']
            c.knowledge._graph.add((node, f.RDF.type, f.OW.Disease))
            c.knowledge._graph.add((node, f.RDFS.label, f.Literal(f'Disease {index}', lang='en')))
            f.add_pattern(c.knowledge, f'candidate{index}', f.OW.Complaint, [], disease=node, effect='support')
        c.knowledge.prepare_terms()
        work = c.differential.prepare_decision(s)
        self.assertEqual(len(work.payload['candidates']), 10)
        raw = dict(ranked_disease_refs=[row['ref'] for row in work.payload['candidates']])
        c.differential.accept(s, raw, work, closing=True)
        c.differential.close(s, c.client, allow_model=False)
        self.assertEqual(len(s.case.assessment.differential), 10)
        c.writer.build_soap(s)
        self.assertEqual(s.turn.payload['note']['A']['differential'].count('r/o '), 5)
        self.assertEqual(work.payload['input_limits']['omitted_candidates'], 12)


class OutcomeTests(unittest.TestCase):
    def test_completed_protocol_and_failed_education_remain_separate(self):
        payload = dict(note=f.RECORD_FIELDS and {section: {key: '' for key in keys} for section, keys in f.RECORD_FIELDS.items()}, diagnosis='Working problem')
        payload['note']['A']['evidence'] = 'Assessment incomplete'
        state = dict(case=dict(plan=[], facts={'a': dict(graph_binding=None)}),
            interview=dict(education_status='failed', education_reason='provider error', answers=[
                dict(question_id='Education:diagnosis:0', outcome='delivered')]),
            session=dict(final_payload=payload))
        value = outcome_metrics(state, payload, [payload], dict(status='completed', receipt=dict(status='completed')))
        self.assertTrue(value['submission_confirmed'])
        self.assertEqual((value['education_status'], value['plan_count'], value['diagnosis_announcement_delivered']), ('failed', 0, 1))
        self.assertFalse(any(value['p_coverage'].values()))
        self.assertEqual((value['fact_count'], value['unbound_fact_count']), (1, 1))
        self.assertEqual(value['plan_delivery'], [])

    def test_local_payload_without_receipt_and_legacy_absence_are_distinct(self):
        payload = dict(note={section: {key: '' for key in keys} for section, keys in f.RECORD_FIELDS.items()}, diagnosis='Working problem')
        value = outcome_metrics(dict(session=dict(final_payload=payload)), {}, [], {})
        self.assertTrue(value['payload_generated'])
        self.assertFalse(value['received'])
        self.assertFalse(value['submission_confirmed'])
        self.assertIsNone(value['plan_count'])
        self.assertIsNone(value['diagnosis_announcement_delivered'])
        self.assertIsNone(value['fact_count'])

    def test_partial_plan_delivery_uses_expected_utterance_count(self):
        state = dict(case=dict(plan=[dict(id='p1')]), interview=dict(education_utterances={'p1': 2},
            answers=[dict(plan_sentence_id='p1', outcome='delivered')]), session={})
        value = outcome_metrics(state, {}, [], {})
        self.assertEqual(value['plan_delivery'][0]['status'], 'partial')
        del state['interview']['education_utterances']
        value = outcome_metrics(state, {}, [], {})
        self.assertEqual(value['plan_delivery'][0]['status'], 'not_collected')


if __name__ == '__main__':
    unittest.main()
