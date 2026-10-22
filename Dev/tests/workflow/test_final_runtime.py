"""Bounded offline recovery: real input custody, finite progress and honest receipts."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import fixtures as f
from workflow.doctor_brain import ModelResult
from workflow.input_types import ContextInput, ContextStatement, PatientContextFact
from workflow.rules.collection import answered, slot_resolved
from workflow.rules.chief import force_chief
from workflow.rules.decision import close_graph_input
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
            from workflow.rules.limits import FIXED_UTTERANCES
            if request['content'] in {text for lines in FIXED_UTTERANCES.values() for text in lines}:
                return original(**request)
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
        self.assertEqual(sum(row.actions for row in s.session.usage.values()) + s.session.fixed_actions, len(client.actions))
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
        self.assertNotIn('known_patient_context', client.requests[0])
        self.assertTrue(any(row.get('context_key') == 'sex' and row['value'] == 'female'
                            for row in client.requests[0]['records']))
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
    def test_large_graph_packet_keeps_all_complete_records_and_closed_references(self):
        payload = dict(facts={'f1': dict(scope='s1')}, scopes={f's{i}': dict(subject='patient') for i in range(1, 107)},
            conditions={f'c{i}': [dict(status='present')] for i in range(111)},
            relations={f'r{i}': dict(full_pattern=[dict(expected='complete criterion')], applicability=f'c{i}') for i in range(111)},
            evidence={f'e{i}': dict(relation=f'r{i % 111}', facts=['f1'], scope=f's{1 + i % 106}') for i in range(113)},
            candidates=[dict(ref='d1', supports=[f'e{i}' for i in range(113)], against=[], unresolved=[])],
            questions=[dict(ref=f'q{i}', scope=f's{1 + i % 106}', expected_by_disease={'d1': [dict(relation=f'r{i % 111}', feature=0)]}) for i in range(99)],
            input_limits={})
        before = copy.deepcopy(payload)
        close_graph_input(payload)
        for key in ('relations', 'evidence', 'questions', 'scopes', 'conditions', 'candidates'):
            self.assertEqual(payload[key], before[key], key)
        self.assertEqual([len(payload[key]) for key in ('relations', 'evidence', 'questions', 'scopes', 'conditions')],
                         [111, 113, 99, 106, 111])
        self.assertEqual(len(payload['facts']), 1)
        for row in payload['evidence'].values():
            self.assertIn(row['relation'], payload['relations'])
            self.assertIn(row['scope'], payload['scopes'])
        for row in payload['questions']:
            for entries in row['expected_by_disease'].values():
                for entry in entries:
                    self.assertIn(entry['relation'], payload['relations'])
        self.assertTrue(all(row['full_pattern'] == [dict(expected='complete criterion')] for row in payload['relations'].values()))

    def test_all_candidates_rank_and_freeze_with_top_five_soap_alternatives(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        for index in range(60):
            node = f.OW[f'Candidate{index}']
            c.knowledge._graph.add((node, f.RDF.type, f.OW.Disease))
            c.knowledge._graph.add((node, f.RDFS.label, f.Literal(f'Disease {index}', lang='en')))
            f.add_pattern(c.knowledge, f'candidate{index}', f.OW.Complaint, [], disease=node, effect='support')
        c.knowledge.prepare_terms()
        work = c.differential.prepare_decision(s)
        self.assertEqual(len(work.payload['candidates']), 62)
        self.assertEqual(len(work.candidates), 62)
        self.assertEqual(len(work.refs), 62)
        self.assertNotIn('differential', work.payload['input_limits'])
        self.assertNotIn('omitted_candidates', work.payload['input_limits'])
        raw = dict(ranked_disease_refs=[row['ref'] for row in work.payload['candidates']])
        c.differential.accept(s, raw, work, closing=True)
        c.differential.close(s, c.client, allow_model=False)
        self.assertEqual(len(s.case.assessment.differential), 62)
        c.writer.build_soap(s)
        self.assertEqual(s.turn.payload['note']['A']['differential'].count('r/o '), 5)
        self.assertEqual(s.turn.payload['diagnosis'], s.case.assessment.differential[0].name)
        note = s.turn.payload['note']['A']['differential']
        for entry in s.case.assessment.differential[1:6]:
            self.assertIn('r/o ' + entry.name + ':', note)
        for entry in s.case.assessment.differential[6:]:
            self.assertNotIn('r/o ' + entry.name + ':', note)
        validate_wire_payload(s.turn.payload)

    def test_graph_projection_keeps_all_fact_scopes_and_candidate_references(self):
        payload = dict(facts={f'f{i}': dict(scope=f's{i}') for i in range(65)},
            scopes={f's{i}': dict(subject='patient') for i in range(65)},
            conditions={}, relations={}, evidence={}, questions=[], input_limits={},
            candidates=[dict(ref=f'd{i}', supports=[], against=[], unresolved=[]) for i in range(65)])
        close_graph_input(payload)
        self.assertEqual(len(payload['facts']), 65)
        self.assertEqual(len(payload['scopes']), 65)
        self.assertEqual(len(payload['candidates']), 65)

    def test_large_internal_differential_keeps_five_in_normal_and_minimal_writer(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.close_collection(s)
        entry = s.case.assessment.differential[0]
        s.case.assessment = s.case.assessment.model_copy(update={'differential': (
            entry, *(DifferentialEntry(kind='disease', name=f'Accepted alternative {i} ' + 'x' * 300)
                     for i in range(400)))})
        c.client.chat = Mock(side_effect=AssertionError('Writer must not call a model'))
        c.writer.build_soap(s)
        self.assertEqual(s.turn.payload['note']['A']['differential'].count('r/o '), 5)
        c.writer.validate_submission(s)
        self.assertIsNone(s.turn.error)
        c.writer.build_minimal(s, 'forced writer failure')
        self.assertEqual(s.turn.payload['note']['A']['differential'].count('r/o '), 5)
        self.assertIn('r/o Accepted alternative 4 ', s.turn.payload['note']['A']['differential'])
        self.assertNotIn('r/o Accepted alternative 5 ', s.turn.payload['note']['A']['differential'])
        c.finish_submission(s)
        self.assertEqual(s.interview.collection['submission:minimal'], 'forced writer failure')
        validate_wire_payload(s.session.final_payload)
        self.assertEqual(s.session.final_payload['diagnosis'], entry.name)
        self.assertEqual(len(s.case.assessment.differential), 401)
        self.assertEqual(s.session.termination, 'submitted')
        c.client.chat.assert_not_called()


class HistoryCompletionTests(unittest.TestCase):
    def test_child_and_caregiver_demographics_leave_family_history_question_open(self):
        c, s = f.consultation(), f.chief(f.state('ContextFactor'))
        rows = [PatientContextFact(key='age', value='6 years', quote='6세',
                    measurement=dict(kind='quantity', value=6, unit='year')),
                PatientContextFact(key='sex', value='male', quote='남아'),
                PatientContextFact(key='age', value='37 years', quote='37세 모', subject='family', subject_member='mother',
                    measurement=dict(kind='quantity', value=37, unit='year')),
                PatientContextFact(key='sex', value='female', quote='모', subject='family', subject_member='mother')]
        s.case.apply(c.ear._demographic_facts(s, rows, 'initial', 0, {'opening': '6세 남아, 37세 모'}))
        s.case.apply([CaseFact(id='weight', category='measurement', value='Weight 20 kg; height 110 cm', source_ref='initial:opening')])
        self.assertFalse(slot_resolved(s.case, 'family_history'))
        self.assertFalse(answered(s, 'family_history'))
        c.tools._prepare_common(s, ('family_history',), c.config.texts.history_questions, 'history')
        self.assertEqual([q.category for q in s.interview.queue], ['family_history'])
        fields, refs = c.writer.build_record_view(s.case)
        self.assertIn('6 years', ' '.join(fields['S.hpi']))
        self.assertNotIn('37 years', ' '.join(fields['S.hpi']))
        self.assertIn('37 years', ' '.join(fields['S.fh']))
        self.assertEqual(s.case.facts['patient_context:family:mother:age'].source_ref, 'initial:opening')
        s.case.apply([CaseFact(id='father', category='family_history', value='Father had late growth',
            subject='family', subject_member='father', source_ref='family-reply')])
        self.assertTrue(answered(s, 'family_history'))

    def test_family_patient_and_demographic_only_answers_do_not_complete_patient_history(self):
        for slot in ('medical_history', 'medication', 'allergy', 'social_history'):
            with self.subTest(slot=slot):
                s = f.state('ContextFactor')
                family = CaseFact(id='family', category=slot, value='Family report', subject='family',
                    subject_member='mother', source_ref='family')
                s.case.apply([family])
                self.assertFalse(answered(s, slot))
                s.case.apply([CaseFact(id='patient_context:family:mother:age', category=slot, value='37 years',
                    subject='family', subject_member='mother', source_ref='demographic-reply')])
                s.interview.answers = [Answer(question_id='q', source_ref='demographic-reply', scope='ContextFactor',
                    category=slot, purpose='history', key=('SAY', '', '', 'patient', '', 'unspecified', '', ''), outcome='recorded')]
                self.assertFalse(answered(s, slot))
                for purpose, key, facts in [('context', ('SAY', 'Test history', '', 'patient', '', 'past', '', ''), ()),
                        ('history', ('SAY', '', '', 'family', 'mother', 'unspecified', '', ''), ()),
                        ('history', ('SAY', '', '', 'patient', '', 'unspecified', '', ''), ('family',))]:
                    s.interview.answers = [Answer(question_id='q', source_ref='reply', scope='ContextFactor',
                        category=slot, purpose=purpose, key=key, outcome='recorded', fact_ids=facts)]
                    self.assertFalse(answered(s, slot))
                s.case.apply([family.model_copy(update={'id': 'patient', 'subject': 'patient', 'subject_member': None})])
                self.assertTrue(answered(s, slot))

    def test_whole_family_denial_and_delivered_unknown_resolve_family_history(self):
        s = f.state('ContextFactor')
        s.case.apply([CaseFact(id='denial', category='family_history', value='No family history reported',
            status='absent', subject='patient', source_ref='initial')])
        self.assertTrue(answered(s, 'family_history'))
        c, s = f.consultation(), f.state('ContextFactor')
        c.tools._prepare_common(s, ('family_history',), c.config.texts.history_questions, 'history')
        q = s.interview.queue[0]
        c.interactions.select_question(s, q)
        s.turn.response = dict(status='OK', turn=1, turns_remaining=49, content='모르겠어요')
        c.ear.process_input(s, c.knowledge, c.client)
        self.assertTrue(answered(s, 'family_history'))
        self.assertFalse(slot_resolved(s.case, 'family_history'))


class UnknownAssessmentTests(unittest.TestCase):
    def reply_after_ranking(self, content='모르겠어요', *, parse_failure=False):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis', initialized=True))
        work = c.differential.prepare_decision(s, mode='rank', closing=True)
        c.differential.accept(s, dict(ranked_disease_refs=list(work.refs)), work, closing=True)
        s.case.assessment = s.case.assessment.model_copy(update={'limitations': ('Prior limitation',)})
        previous = s.case.assessment
        q = Question(item_id='unknown', purpose='feature', text='가상증상이 있나요?', target='Test complaint',
            observation_id='obs1', episode_id='episode1', time_context='current',
            affirmative_presence=True, answer_type='presence')
        c.questions.register(s, q)
        c.interactions.select_question(s, q)
        original = c.client.say
        def say(**request):
            return dict(original(**request), content=content)
        c.client.say = say
        c.mouth.validate_action(s)
        c.mouth.execute_action(s, c.client)
        if parse_failure:
            with patch.object(c.ear, '_parse_text', side_effect=ValueError('parser failure')), \
                    patch.object(c, 'refresh_after_input'):
                c.accept_input(s)
        else:
            c.ear.process_input(s, c.knowledge, c.client)
        return c, s, previous

    def test_exact_unknown_failed_reassessment_preserves_order_evidence_and_original_basis(self):
        for failure in ('context', 'output_exhausted'):
            with self.subTest(failure=failure):
                c, s, previous = self.reply_after_ranking()
                self.assertEqual((s.case.revision, s.case.chief_fact_id),
                                 (previous.based_on_case_revision, previous.based_on_chief_fact_id))
                c.client.chat = Mock(side_effect=f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400))
                if failure == 'output_exhausted':
                    s.session.output_tokens = 100_000
                c.differential.close(s, c.client)
                assessment = s.case.assessment
                self.assertEqual(assessment.differential, previous.differential)
                self.assertEqual(assessment.based_on_response, previous.based_on_response)
                self.assertIn('Prior limitation', assessment.limitations)
                self.assertTrue(any('not clinically reassessed' in item for item in assessment.limitations))
                self.assertTrue(assessment.frozen)
                self.assertEqual(c.client.chat.call_count, 1 if failure == 'context' else 0)

    def test_model_free_exit_retains_last_accepted_disease_assessment(self):
        c, s, previous = self.reply_after_ranking()
        c.differential.close(s, c.client, allow_model=False)
        self.assertEqual(s.case.assessment.differential, previous.differential)
        self.assertEqual(s.case.assessment.based_on_response, previous.based_on_response)
        self.assertTrue(any('not clinically reassessed' in item for item in s.case.assessment.limitations))

    def test_failed_reassessment_retains_diseases_after_changed_or_unparsed_inputs(self):
        for kind in ('negative', 'acknowledgement', 'parser', 'free_text', 'revision', 'chief',
                     'error', 'turn', 'response', 'status', 'exam', 'earlier_reply'):
            with self.subTest(kind=kind):
                c, s, previous = self.reply_after_ranking(
                    '아니요' if kind == 'negative' else '알겠습니다' if kind == 'acknowledgement' else
                    '잘 모르겠지만 어제 새 통증이 생겼어요' if kind == 'free_text' else '모르겠어요',
                    parse_failure=kind == 'parser')
                if kind == 'revision':
                    s.case.apply([CaseFact(id='new', value='New family history', category='family_history',
                        subject='family', subject_member='father', source_ref='new')])
                elif kind == 'chief':
                    s.case.chief_fact_id = None
                elif kind in {'error', 'turn', 'response', 'status', 'exam'}:
                    answer = s.interview.answers[-1]
                    update = {'response': dict(answer.response, error='API_UNAVAILABLE')} if kind == 'error' else (
                        {'turn': None} if kind == 'turn' else {'response': None} if kind == 'response' else
                        {'response': dict(answer.response, status='failed')} if kind == 'status' else
                        {'key': ('EXAM', *answer.key[1:])})
                    s.interview.answers[-1] = answer.model_copy(update=update)
                elif kind == 'earlier_reply':
                    s.interview.answers.insert(0, s.interview.answers[-1].model_copy(update={'source_ref': 'unreviewed'}))
                c.client.chat = Mock(side_effect=f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400))
                c.differential.close(s, c.client)
                self.assertEqual(s.case.assessment.differential, previous.differential)
                self.assertEqual(s.case.assessment.based_on_case_revision, previous.based_on_case_revision)
                self.assertEqual(s.case.assessment.based_on_chief_fact_id, previous.based_on_chief_fact_id)
                self.assertEqual(s.case.assessment.based_on_response, previous.based_on_response)
                self.assertTrue(any('not clinically reassessed' in item for item in s.case.assessment.limitations))

    def test_successful_reassessment_after_unknown_takes_precedence(self):
        c, s, previous = self.reply_after_ranking()
        c.differential.close(s, c.client)
        self.assertNotEqual(s.case.assessment.based_on_response, previous.based_on_response)
        self.assertEqual(s.case.assessment.based_on_response, s.interview.answers[-1].source_ref)
        self.assertFalse(any('not clinically reassessed' in item for item in s.case.assessment.limitations))


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
