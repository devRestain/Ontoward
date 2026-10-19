import copy
import unittest

import fixtures as f
from workflow.rules.decision import clinical_messages
from workflow.state.evidence import EvidenceIndex, patient_payload
from workflow.state.models import Answer, Assessment, CaseFact, DifferentialEntry


class SessionTaskTests(unittest.TestCase):
    def test_initiation_clarifies_a_missing_chief_before_chief_bound_intake(self):
        c, state = f.consultation(), f.state()
        owner = c.sessions['Initiation']
        owner.prepare(state)
        self.assertEqual([q.purpose for q in state.interview.queue], ['greeting'])
        greeting = state.interview.queue.pop()
        state.interview.answers.append(Answer(question_id=greeting.item_id, source_ref='greeting',
            scope='Initiation', purpose='greeting', outcome='nonclinical'))
        owner.prepare(state)
        self.assertEqual([q.purpose for q in state.interview.queue], ['clarification'])
        self.assertFalse(c.client.requests)
        state.interview.queue.clear()
        f.chief(state)
        owner.prepare(state)
        self.assertTrue(state.interview.queue)
        self.assertTrue(all(q.purpose == 'intake' and q.target == 'Test complaint' for q in state.interview.queue))

    def test_exit_rankings_and_per_response_dd_calls_follow_real_workflow(self):
        c, state, updates = f.run(prepared=f.resources(education=True))
        clinical = [row for row in c.client.requests if row['task'].startswith('clinical_')]
        self.assertEqual([(row['task'], row['stage']) for row in clinical[:3]],
            [('clinical_rank', stage) for stage in ('Initiation', 'ChiefComplaint', 'ContextFactor')])
        self.assertIsNone(next(raw['case']['assessment'] for name, raw in updates if name == 'process_initial_input'))
        for stage in ('Initiation', 'ChiefComplaint', 'ContextFactor'):
            self.assertEqual(sum(row['stage'] == stage for row in clinical), 1)
        dd_answers = [a for a in state.interview.answers if a.scope == 'DifferentialDiagnosis' and a.purpose != 'empathy']
        self.assertEqual(sum(row['task'] == 'clinical_decision' for row in clinical), len(dd_answers))
        self.assertEqual(sum(row['task'] == 'clinical_action' for row in clinical), 1)
        self.assertIs(c.ear.model, c.brain)
        self.assertIs(c.mouth.model, c.brain)
        self.assertIs(c.sessions['Education'].brain, c.brain)
        self.assertEqual(state.session.termination, 'submitted')
        self.assertTrue(all(a.scope == 'DifferentialDiagnosis' for a in state.interview.answers if a.purpose == 'ros'))

    def test_empty_candidate_session_exits_still_call_once(self):
        c, state = f.consultation(), f.state()
        state.case.apply([f.fact(target='Other symptom')])
        for stage in ('Initiation', 'ChiefComplaint', 'ContextFactor'):
            state.interview.current = stage
            owner = c.sessions[stage]
            owner.close(state, c.client)
            owner.close(state, c.client)
        self.assertEqual(len(c.client.requests), 3)
        self.assertTrue(all(row['candidates'] == [] for row in c.client.requests))
        self.assertEqual(state.case.assessment.differential, ())

    def test_changed_unbound_context_revises_the_same_fact_store(self):
        c, state = f.consultation(), f.chief(f.state())
        record = CaseFact(id='medication', category='medication', value='Reported medication 10 mg at night',
            source_ref='reply', acquisition='SAY')
        before = state.case.revision
        state.case.apply([record])
        self.assertEqual(state.case.revision, before + 1)
        self.assertEqual(len(EvidenceIndex.from_case(state.case, c.knowledge).entries), 1)
        self.assertIn(record.value, str(patient_payload(state.case)))
        work = c.sessions['Initiation'].prepare_decision(state)
        self.assertIn(record.value, str(work.payload['facts']))
        state.case.apply([record])
        self.assertEqual(state.case.revision, before + 1)
        state.case.apply([record.model_copy(update={'value': 'Reported medication 20 mg at night'})])
        self.assertEqual(state.case.revision, before + 2)

    def test_mapped_qualified_statement_keeps_its_description_once(self):
        state, c, client = f.interpret([f.statement('Only with exercise', polarity_scope='qualified',
            note_value='Only with exercise; absent at rest')])
        self.assertEqual(len(state.case.facts), 1)
        fact = next(iter(state.case.facts.values()))
        self.assertIsNotNone(fact.graph_binding)
        self.assertIn('absent at rest', fact.value)
        self.assertFalse(EvidenceIndex.from_case(state.case, c.knowledge).entries)
        self.assertIn('absent at rest', str(patient_payload(state.case)))
        fields, _ = c.writer.build_record_view(state.case)
        self.assertEqual(str(fields).count(fact.value), 1)

    def test_unbound_conditions_survive_and_invalid_normalized_text_stays_out_of_consumers(self):
        row = f.statement('Only after exercise', target_terms=[], record_category='previous_care',
            note_value='Observation only after exercise', polarity_scope='qualified')
        state, c, _ = f.interpret([row])
        fact = next(iter(state.case.facts.values()))
        self.assertIsNone(fact.graph_binding)
        self.assertEqual(fact.polarity_scope, 'qualified')
        work = c.sessions['Initiation'].prepare_decision(state)
        self.assertIn('qualified', str(work.payload['facts']))
        valid = f.statement('Accepted observation')
        invalid = f.statement('Invalid description', note_value='환자 원문')
        state, c, _ = f.interpret([valid, invalid])
        self.assertEqual(len(state.case.facts), 1)
        self.assertNotIn('환자 원문', str(patient_payload(state.case)))
        self.assertNotIn('환자 원문', str(c.writer.build_record_view(state.case)))

    def test_context_question_pool_stays_with_the_cc_assessment(self):
        k = f.knowledge()
        for predicate, value in ((f.RDF.type, f.OW.ContextFactor),
            (f.RDFS.label, f.Literal('Other context', lang='en')), (f.OW.contextType, f.Literal('past_medical_history'))):
            k._graph.add((f.OW.BetaContext, predicate, value))
        k.questions[str(f.OW.BetaContext)] = f.QuestionTemplate(text='다른 병력이 있나요?', answer_type='presence', affirmative=True)
        f.add_pattern(k,'betaContext',f.OW.BetaContext,[],disease=f.OW.Beta)
        k.prepare_terms()
        c, state = f.consultation(prepared=f.resources(k)), f.chief(f.state('ContextFactor'))
        state.case.assessment = Assessment(differential=(DifferentialEntry(kind='disease', name='Disease alpha'),),
            based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id)
        context = c.sessions['ContextFactor']
        context.enter(state, state.case.assessment)
        state.case.apply([f.fact('new', kind='context', target='Other context', category='medical_history')])
        context.prepare_context(state)
        self.assertEqual(context.candidate_ids, (str(f.OW.Alpha),))
        self.assertTrue(state.interview.queue)
        self.assertTrue(all(q.target == 'Test history' for q in state.interview.queue))
        self.assertFalse(c.client.requests)

    def test_focused_ros_moves_to_dd_and_keeps_its_limit(self):
        k = f.knowledge()
        k._graph.add((f.OW.SyntheticSystem, f.RDF.type, f.OW.BodySystem))
        for target in (f.OW.Complaint, f.OW.Other):
            k._graph.add((target, f.OW.inSystem, f.OW.SyntheticSystem))
        c, state = f.consultation(prepared=f.resources(k)), f.chief(f.state('ChiefComplaint'))
        spec = c.tools._spec(state, str(f.OW.Other))
        self.assertFalse(c.tools._allowed_now(state, spec))
        state.interview.current = 'DifferentialDiagnosis'
        self.assertTrue(c.tools._allowed_now(state, spec))
        self.assertEqual(spec['purpose'], 'ros')
        for index in range(6):
            state.interview.answers.append(Answer(question_id=str(index), source_ref=str(index),
                scope='DifferentialDiagnosis', purpose='ros', outcome='unknown'))
        self.assertFalse(c.tools._allowed_now(state, spec))

    def test_action_request_omits_full_graph_and_schema(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(state, c.client)
        rank = c.differential.prepare_decision(state)
        action = c.differential.prepare_decision(state, mode='action')
        self.assertFalse(action.payload['evidence'])
        self.assertNotIn('schema', action.payload)
        wire = clinical_messages(c.config, rank)[-1]['content']
        self.assertTrue(wire.startswith('task = '))
        self.assertNotIn('urn:ontoward:', wire)
        self.assertNotIn('graph_binding', wire)

    def test_unknown_dd_response_calls_once_and_freeze_reuses_it(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(state, c.client)
        state.interview.queue.clear()
        before = state.case.revision
        state.interview.answers.append(Answer(question_id='answer', source_ref='accepted-reply',
            scope='DifferentialDiagnosis', purpose='feature', outcome='unknown'))
        calls = len(c.client.requests)
        c.differential.decide(state, c.client)
        c.differential.decide(state, c.client)
        self.assertEqual(state.case.revision, before)
        self.assertEqual(len(c.client.requests), calls + 1)
        state.interview.queue.clear()
        c.close_collection(state)
        self.assertEqual(len(c.client.requests), calls + 1)
        frozen = copy.deepcopy(state.case.model_dump())
        c.writer.build_soap(state)
        c.repair_submission(state)
        self.assertEqual(state.case.model_dump(), frozen)

    def test_closing_after_an_unknown_reply_processes_that_reply_before_freezing(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(state, c.client)
        state.interview.queue.clear()
        state.interview.answers.append(Answer(question_id='last', source_ref='last-unknown-reply',
            scope='DifferentialDiagnosis', purpose='feature', outcome='unknown'))
        calls = len(c.client.requests)
        c.close_collection(state)
        self.assertEqual(len(c.client.requests), calls + 1)
        self.assertEqual(c.differential.last_input[-1], 'last-unknown-reply')
        self.assertTrue(state.case.assessment.frozen)
        c.close_collection(state)
        self.assertEqual(len(c.client.requests), calls + 1)

    def test_final_dd_reply_ranks_once_without_offering_an_unaffordable_action(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(state, c.client)
        state.interview.queue.clear()
        state.session.usage['DifferentialDiagnosis'].actions = 10
        state.interview.answers.append(Answer(question_id='cap', source_ref='last-at-cap',
            scope='DifferentialDiagnosis', purpose='feature', outcome='unknown'))
        calls = len(c.client.requests)
        c.differential.decide(state, c.client)
        self.assertEqual(len(c.client.requests), calls + 1)
        self.assertEqual(c.client.requests[-1]['task'], 'clinical_decision')
        self.assertEqual(c.client.requests[-1]['questions'], [])
        self.assertIsNone(c.differential.error)
        c.close_collection(state)
        self.assertTrue(state.case.assessment.frozen)
        self.assertEqual(len(c.client.requests), calls + 1)
