"""Lossless inputs, evidence-only coverage and verified no-information DD reuse."""
import copy
import json
import unittest
from unittest.mock import Mock

import fixtures as f
from clinical_wire_fixtures import assert_same_meaning, canonical, duplicate_payload
from protocol import decode_context, expand_tables
from test_d66 import collection_knowledge, receipt
from workflow.input_wire import InputProjection
from workflow.model_context import message_metrics
from workflow.rules.collection import answered
from workflow.rules.coverage import CoverageWork, accept, covered, key, question_record, unknown_answers
from workflow.rules.decision import clinical_messages
from workflow.state.models import CaseFact, Question, TurnContext
from workflow.wire import json_bytes, row_table, table_payload


class LosslessInputTests(unittest.TestCase):
    def test_tables_preserve_missing_null_types_and_interleaved_array_order(self):
        rows = []
        for index in range(120):
            row = dict(ref=f'q_{index}', kind='SAY', target='Repeated long clinical target name',
                       measurement=dict(value=0.0 if index % 2 else 0, unit='kg', approximate=False))
            if index % 3:
                row['attribute'] = None if index % 2 else 'Repeated attribute name'
            rows.append(row)
        table = row_table(rows)
        self.assertLess(json_bytes(table), json_bytes(rows))
        self.assertEqual(canonical(expand_tables(table)), canonical(rows))
        dictionary = {f'e_{i}': row for i, row in enumerate(rows)}
        self.assertEqual(canonical(expand_tables(row_table(dictionary))), canonical(dictionary))
        tiny = [{'value': 0}]
        self.assertEqual(row_table(tiny), tiny)

    def test_complete_clinical_work_above_one_hundred_is_unchanged(self):
        c, state = f.consultation(prepared=f.resources(collection_knowledge(say=110, exam=6))), f.chief(f.state('DifferentialDiagnosis'))
        work = c.differential.prepare_decision(state)
        before = copy.deepcopy(work)
        wire = json.loads(clinical_messages(c.config, work)[-1]['content'])
        expanded = expand_tables(wire)
        assert_same_meaning(self, work.payload, wire)
        self.assertEqual(work, before)
        self.assertGreater(len(expanded['questions']), 100)
        self.assertEqual({q['ref'] for q in expanded['questions']}, set(work.options))
        metrics = message_metrics('clinical', clinical_messages(c.config, work))
        self.assertEqual(metrics['counts']['questions'], len(work.options))

    def test_table_metrics_count_logical_rows_and_nested_expectations(self):
        logical = duplicate_payload(count=120)
        from workflow.rules.clinical_wire import compact_clinical_payload
        compact = compact_clinical_payload(logical)
        tables = table_payload(compact, ('facts', 'scopes', 'relations', 'evidence', 'questions', 'candidates'))
        from workflow.model_context import messages
        before, after = (message_metrics('clinical', messages('Same', p)) for p in (compact, tables))
        self.assertEqual(before['counts'], after['counts'])
        self.assertLess(after['messages_json_bytes'], before['messages_json_bytes'])

    def test_ear_keeps_every_fact_and_restores_opaque_references(self):
        c, state = f.consultation(), f.chief(f.state('ChiefComplaint'))
        state.case.apply([CaseFact(id=f'long-fact-identity-{i}', category='other', value=f'Explicit report {i}',
            source_ref=f'actual-source-{i}', observation_id=f'actual-observation-{i}', episode_id=f'actual-episode-{i}')
            for i in range(90)])
        state.turn = TurnContext(kind='initial', response={'opening': 'New report'})
        logical = dict(task='input_context', question=None, **c.ear._project_context(state, None))
        projection = InputProjection(logical)
        wire = projection.payload(logical)
        expanded = decode_context(json.dumps(wire))
        self.assertEqual(len(expanded['records']), 91)
        restored = projection.restore(expanded)
        self.assertEqual(canonical(restored['records']), canonical(logical['records']))
        original = logical['records'][30]
        refs = projection.refs
        output = projection.restore({'statements': [dict(correction_id=refs['id'][original['id']],
            observation_id=refs['observation_id'][original['observation_id']],
            episode_id=refs['episode_id'][original['episode_id']])]})
        self.assertEqual(output['statements'][0], {key: original[value] for key, value in
            (('correction_id', 'id'), ('observation_id', 'observation_id'), ('episode_id', 'episode_id'))})
        self.assertEqual(projection.payload(logical), wire)

    def test_context_repairs_reuse_refs_and_reject_unknown_reference(self):
        state = f.chief(f.state('ChiefComplaint'))
        calls = []
        def handler(payload):
            if payload['task'] != 'input_context':
                return None
            calls.append(payload)
            row = payload['records'][0]
            return {'statements': [f.statement('Reported complaint', correction_id='f_missing' if len(calls) == 1 else row['id'],
                observation_id=row['observation_id'], episode_id=row['episode_id'])]}
        state, c, _ = f.interpret([], s=state, text='Reported complaint', responses=handler)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['records'], calls[1]['records'])
        self.assertIn('chief', state.case.facts)
        self.assertFalse(any(fact.id.startswith('f_') for fact in state.case.facts.values()))


class CoverageTests(unittest.TestCase):
    def setup_question(self, *, stage='DifferentialDiagnosis', attribute=False):
        c, state = f.consultation(), f.chief(f.state(stage))
        if attribute:
            spec = c.tools._spec(state, str(f.OW.Complaint), str(f.OW.Quality), 'obs1', 'episode1', purpose='hpi')
        else:
            spec = c.tools._spec(state, str(f.OW.Other), observation='other-observation', episode='episode1')
        question = c.tools._question(spec, 'pending', 0, 0)
        return c, state, spec, question

    def cover(self, c, state, question, *, fact='chief', outcome='known', answers=None):
        work = CoverageWork(questions={'p_1': question}, fact_refs={'f_1': fact}, answer_refs=answers or {})
        work.proposals = [dict(question_ref='p_1', outcome=outcome,
            **({'fact_refs': ['f_1']} if outcome == 'known' else {'answer_refs': list(work.answer_refs)}))]
        return accept(state, work, c.knowledge, c.config)

    def test_cross_node_coverage_filters_question_without_copying_facts_or_receipts(self):
        c, state, spec, question = self.setup_question()
        before = state.case.model_dump(mode='json')
        self.assertTrue(c.tools._eligible(state, spec))
        self.assertEqual(self.cover(c, state, question), {'p_1'})
        self.assertFalse(c.tools._eligible(state, spec))
        self.assertEqual(state.case.model_dump(mode='json'), before)
        self.assertEqual(state.interview.answers, [])
        self.assertEqual(state.session.usage['DifferentialDiagnosis'].actions, 0)
        record = state.interview.question_coverage['|'.join(key(question))]
        self.assertEqual(set(record.fact_signatures), {'chief'})

    def test_negative_is_known_and_uncertain_is_not(self):
        for value, expected in (('absent', True), ('unknown', False), ('uncertain', False)):
            c, state, _, question = self.setup_question()
            state.case.apply([state.case.facts['chief'].model_copy(update={'status': value})])
            self.assertEqual(bool(self.cover(c, state, question)), expected)

    def test_scopes_and_acquisition_cannot_be_combined(self):
        for changes in (dict(subject='family', subject_member='mother'), dict(time_context='past'),
                        dict(episode_id='different-episode'), dict(kind='EXAM')):
            c, state, _, question = self.setup_question()
            self.assertFalse(self.cover(c, state, question.model_copy(update=changes)))
        c, state, _, question = self.setup_question()
        self.assertTrue(self.cover(c, state, question))  # Distinct observation, same explicit episode.

    def test_correction_conflict_and_removed_fact_invalidate_only_dependent_entry(self):
        for change in ('correction', 'conflict', 'removed'):
            c, state, _, question = self.setup_question()
            self.cover(c, state, question)
            if change == 'correction':
                state.case.apply([state.case.facts['chief'].model_copy(update={'status': 'absent'})])
            elif change == 'conflict':
                state.case.apply([f.fact('conflicting', status='absent')])
            else:
                state.case.facts.pop('chief')
            self.assertFalse(covered(state, question))
            self.assertFalse(state.interview.question_coverage)

    def test_unknown_requires_actual_exact_receipt_and_stays_unknown(self):
        c, state, spec, question = self.setup_question()
        answer = receipt('SAY', 1)
        state.interview.answers.append(answer)
        prior = len(state.interview.answers)
        self.assertTrue(self.cover(c, state, question, outcome='asked_unknown', answers={'a_1': answer}))
        self.assertFalse(c.tools._eligible(state, spec))
        self.assertEqual(state.interview.answers[-1].outcome, 'unknown')
        self.assertEqual(len(state.interview.answers), prior)
        state.case.apply([CaseFact(id='new', category='other', value='New information', source_ref='new')])
        self.assertFalse(covered(state, question))
        bad = answer.model_copy(update={'response': dict(answer.response, error='API_UNAVAILABLE')})
        self.assertFalse(self.cover(c, state, question, outcome='asked_unknown', answers={'a_1': bad}))

    def test_partial_presence_cannot_cover_attribute_or_numeric_detail(self):
        c, state, _, question = self.setup_question(attribute=True)
        self.assertFalse(self.cover(c, state, question))
        note = CaseFact(id='note', category='quality', value='A reported quality', source_ref='old',
            time_context='current', observation_id='obs1', episode_id='episode1', acquisition='SAY')
        state.case.apply([note])
        numeric = question.model_copy(update={'answer_type': 'quantity'})
        self.assertFalse(self.cover(c, state, numeric, fact='note'))

    def test_protected_questions_and_demographics_do_not_complete_history(self):
        c, state, _, question = self.setup_question()
        for purpose in ('chief', 'clarification', 'open_inquiry', 'history', 'education'):
            self.assertFalse(self.cover(c, state, question.model_copy(update={'purpose': purpose})))
        demographic = CaseFact(id='sex', category='patient_context', context_key='sex', value='female',
            source_ref='initial', time_context='current', observation_id='obs1', episode_id='episode1')
        state.case.apply([demographic])
        self.assertFalse(self.cover(c, state, question, fact='sex'))
        self.assertFalse(answered(state, 'family_history'))

    def test_ear_accepts_statement_coverage_only_after_real_fact_storage(self):
        rows = [f.statement('Complaint', primary_concern=True),
            f.statement('one week ago', target_terms=[], focus='attribute', anchor=0,
                record_category='onset', note_value='Started one week ago')]
        def handler(payload):
            if payload['task'] == 'input_context':
                pending = next(q for q in payload['pending_questions'] if q['category'] == 'onset')
                return dict(statements=rows, covered_questions=[dict(question_ref=pending['ref'], outcome='known',
                    statement_indices=[1]), dict(question_ref='missing', outcome='known', statement_indices=[999])])
        state, c, client = f.interpret(rows, text='Complaint one week ago', responses=handler)
        self.assertTrue(state.interview.question_coverage)
        self.assertEqual(len(client.requests), 1)
        self.assertFalse(state.interview.answers)
        self.assertTrue(answered(state, 'onset'))
        c.sessions['Initiation'].prepare(state)
        self.assertFalse(any(q.category == 'onset' for q in state.interview.queue))

    def test_cc_and_context_read_the_shared_coverage_state(self):
        c, state, _, question = self.setup_question(stage='ChiefComplaint', attribute=True)
        state.case.apply([CaseFact(id='quality-note', category='quality', value='Explicit quality detail',
            source_ref='old', observation_id='obs1', episode_id='episode1', time_context='current', acquisition='SAY')])
        self.assertTrue(self.cover(c, state, question, fact='quality-note'))
        c.sessions['ChiefComplaint'].prepare_collection(state)
        self.assertFalse(any(q.attribute == 'Quality' for q in state.interview.queue))
        state.interview.current = 'ContextFactor'
        state.interview.queue.clear()
        work = c.sessions['ChiefComplaint'].prepare_decision(state)
        # Use the same registered context candidate builder as actual Context preparation.
        from workflow.rules.assessment import context_questions
        specs = c.tools.context_specs(state, context_questions(c.knowledge, work.candidates))
        spec = next(iter(specs.values()))
        q = c.tools._question(spec, '', 0, 0)
        note = CaseFact(id='context-note', category='medical_history', value='Explicit registered context information',
            source_ref='old-context', time_context=q.time_context, acquisition='SAY')
        state.case.apply([note])
        self.assertTrue(self.cover(c, state, q, fact=note.id))
        self.assertFalse(c.tools.context_specs(state, context_questions(c.knowledge, work.candidates)))

    def test_exit_ranking_supplies_next_stage_questions_without_extra_call(self):
        for scope, target in (('Initiation', 'Quality'), ('ChiefComplaint', 'Test history')):
            c, state = f.consultation(), f.chief(f.state(scope))
            work = c.sessions[scope].prepare_decision(state)
            wire = decode_context(clinical_messages(c.config, work)[-1]['content'])
            self.assertTrue(any(q.get('attribute') == target or q.get('target') == target
                                for q in wire['pending_questions']))
            self.assertFalse(c.client.requests)

    def test_malformed_optional_coverage_preserves_ranking_and_valid_action(self):
        for proposals in ('bad', [None, {}, {'question_ref': []},
                                dict(question_ref='q_1', outcome='known', fact_refs=['f_missing'])]):
            def handler(payload):
                if payload['task'] == 'clinical_decision':
                    needed = payload['resources']
                    question = next(q for q in payload['questions'] if needed.get('required_' + q['kind'].lower(), 0))
                    return dict(ranked_disease_refs=[d['ref'] for d in payload['candidates']],
                        next_action=dict(kind='ask', question_ref=question['ref']), covered_questions=proposals)
            c, state = f.consultation(f.FakeSDK(chat_handler=handler)), f.chief(f.state('DifferentialDiagnosis'))
            c.differential.decide(state, c.client)
            self.assertIsNotNone(state.case.assessment)
            self.assertEqual(len(c.client.requests), 1)
            self.assertTrue(state.interview.queue)

    def test_selecting_just_covered_option_uses_remaining_question_without_repair(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        state.case.apply([CaseFact(id='note', category='other', value='Explicit known examination information',
            source_ref='exam', acquisition='EXAM', time_context='current', episode_id='episode1')])
        work = c.differential.prepare_decision(state)
        ref = next(ref for ref, q in work.coverage.questions.items() if q.kind == 'EXAM')
        fact = next(ref for ref, ident in work.coverage.fact_refs.items() if ident == 'note')
        c.differential.accept(state, dict(ranked_disease_refs=list(work.refs),
            next_action=dict(kind='ask', question_ref=ref),
            covered_questions=[dict(question_ref=ref, outcome='known', fact_refs=[fact])]), work)
        self.assertTrue(state.interview.queue)
        self.assertEqual(state.interview.queue[0].kind, 'SAY')
        self.assertFalse(c.client.requests)
        self.assertFalse(state.interview.answers)


class UnknownReuseTests(unittest.TestCase):
    def ranked(self):
        c, state = f.consultation(prepared=f.resources(collection_knowledge(say=5, exam=2))), f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(state, c.client)
        state.interview.queue.clear()
        return c, state

    def test_consecutive_exact_unknowns_use_actions_and_close_without_ranking(self):
        c, state = self.ranked()
        before = state.case.assessment
        for number in (1, 2):
            state.interview.answers.append(receipt('SAY', number))
            c.differential.decide(state, c.client)
            self.assertEqual(c.client.requests[-1]['task'], 'clinical_action')
            state.interview.queue.clear()
        calls = len(c.client.requests)
        c.differential.close(state, c.client)
        self.assertEqual(len(c.client.requests), calls)
        self.assertEqual(state.case.assessment.differential, before.differential)
        self.assertEqual(state.case.assessment.based_on_response, before.based_on_response)
        self.assertTrue(state.case.assessment.frozen)
        self.assertEqual(c.differential.handled_response, 'request2')
        self.assertTrue(any('ranking reused' in value for value in state.case.assessment.limitations))

    def test_new_information_nonexact_unknown_and_exam_force_full_decision(self):
        for kind in ('negative', 'free_text', 'EXAM', 'revision', 'chief', 'error'):
            c, state = self.ranked()
            answer = receipt('EXAM' if kind == 'EXAM' else 'SAY', 1)
            if kind in {'negative', 'free_text'}:
                answer = answer.model_copy(update={'response': dict(answer.response,
                    content='없어요' if kind == 'negative' else '모르겠지만 새 통증이 있어요')})
            elif kind == 'error':
                answer = answer.model_copy(update={'reason': 'input failed'})
            state.interview.answers.append(answer)
            if kind == 'revision':
                state.case.apply([CaseFact(id='new', category='other', value='New clinical report', source_ref='new')])
            elif kind == 'chief':
                state.case.chief_fact_id = None
            c.differential.decide(state, c.client)
            self.assertEqual(c.client.requests[-1]['task'], 'clinical_decision', kind)

    def test_cc_assessment_does_not_skip_joint_dd_entry(self):
        c, state = f.consultation(), f.chief(f.state('ChiefComplaint'))
        work = c.sessions['ChiefComplaint'].prepare_decision(state)
        c.sessions['ChiefComplaint'].accept(state, dict(ranked_disease_refs=list(work.refs)), work)
        state.interview.current = 'DifferentialDiagnosis'
        state.interview.answers.append(receipt('SAY', 1))
        c.differential.decide(state, c.client)
        self.assertEqual(c.client.requests[0]['task'], 'clinical_decision')


if __name__ == '__main__':
    unittest.main()
