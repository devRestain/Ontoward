"""DD collects from one graph-derived pool and ranks only at exit."""
import copy
import json
import unittest
from unittest.mock import patch

import fixtures as f
from protocol import decode_context
from test_d66 import collection_knowledge
from workflow.rules.assessment import graph_candidates


class DDCollectionCadenceTests(unittest.TestCase):
    def test_selection_includes_current_soap_history_without_state_writes(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        state.case.apply([
            f.CaseFact(id='age', source_ref='initial', category='patient_context', context_key='age', value='6 years'),
            f.CaseFact(id='sex', source_ref='initial', category='patient_context', context_key='sex', value='male'),
            f.CaseFact(id='family', source_ref='reply', category='family_history', subject='family',
                subject_member='father', time_context='past', value='Father grew during high school'),
            f.CaseFact(id='measurement', source_ref='reply', category='measurement',
                value='Reported height velocity', measurement=f.ObservedNumber(kind='quantity', value=5, unit='cm/year'))])
        before = state.model_dump(mode='json')
        work = c.differential.prepare_selection(state)
        payload = decode_context(c.differential.selection_messages(work)[-1]['content'])
        fields, _ = c.writer.build_record_view(state.case, state.interview)
        self.assertEqual(payload['patient_history'], {key: '\n'.join(lines) for key, lines in fields.items()
            if key.startswith(('S.', 'O.')) and lines})
        self.assertIn('Age: 6 years', payload['patient_history']['S.hpi'])
        self.assertIn('Sex: male', payload['patient_history']['S.hpi'])
        self.assertIn('5 cm/year', payload['patient_history']['S.hpi'])
        self.assertIn('Father grew during high school', payload['patient_history']['S.fh'])
        self.assertIn('Family: father; Past', payload['patient_history']['S.fh'])
        self.assertEqual(state.model_dump(mode='json'), before)
        state.case.apply([f.CaseFact(id='new', source_ref='next', category='medical_history',
            value='Medication use', status='absent')])
        self.assertIn('Medication use (-)', c.differential.prepare_selection(state).payload['patient_history']['S.pmh'])

    def test_complete_collection_ranks_once_after_last_answer(self):
        c = f.consultation(prepared=f.resources(collection_knowledge(say=16, exam=10)))
        state = f.chief(f.state('DifferentialDiagnosis'))
        c.run(state)
        requests = [p for p in c.client.requests if p['task'].startswith('clinical_')]
        self.assertGreater(sum(p['task'] == 'clinical_action' for p in requests), 1)
        self.assertEqual([p['task'] for p in requests if p['task'] != 'clinical_action'], ['clinical_rank'])
        self.assertEqual(requests[-1]['task'], 'clinical_rank')
        self.assertTrue(state.case.assessment.frozen)
        self.assertEqual(state.case.assessment.based_on_case_revision, state.case.revision)
        self.assertEqual(state.session.termination, 'submitted')
        self.assertEqual(state.session.usage['DifferentialDiagnosis'].actions, 20)
        self.assertTrue(all(p['resources']['turns'] > 0 for p in requests if p['task'] == 'clinical_action'))
        self.assertNotIn('question_not_executable', str(state.interview.collection))

    def test_selection_omits_full_graph_and_preserves_assessment_and_pool(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        with patch('workflow.sessions.differential_diagnosis.graph_candidates', wraps=graph_candidates) as recall:
            work = c.differential.prepare_selection(state)
            pool = copy.deepcopy(c.differential.question_pool)
            c.differential.prepare_selection(state)
            self.assertEqual(recall.call_count, 1)
        payload = decode_context(c.differential.selection_messages(work)[-1]['content'])
        self.assertFalse({'facts', 'candidates', 'relations', 'patterns', 'evidence', 'conditions'} & payload.keys())
        self.assertTrue(payload['questions'])
        self.assertEqual(set(payload['diseases']), {'Disease alpha', 'Disease beta'})
        before = state.case.assessment
        c.differential.decide(state, c.client)
        self.assertIs(state.case.assessment, before)
        self.assertEqual(c.differential.question_pool, pool)
        full = c.differential.prepare_decision(state)
        from workflow.rules.decision import clinical_messages
        self.assertLess(len(json.dumps(c.differential.selection_messages(work))),
                        len(json.dumps(clinical_messages(c.config, full))))

    def test_latent_attribute_is_enabled_only_after_same_scope_presence(self):
        k = f.knowledge()
        k._graph.add((f.OW.Other, f.OW.hasAttribute, f.OW.Quality))
        f.add_pattern(k, 'otherQuality', f.OW.Other, [
            (f.OW.Quality, dict(kind='concept', concept=str(f.OW.Dull)))])
        k.prepare_terms()
        c, state = f.consultation(prepared=f.resources(k)), f.chief(f.state('DifferentialDiagnosis'))
        first = c.differential.prepare_selection(state)
        ref, spec = next((ref, spec) for ref, spec in c.differential.question_pool.items()
                        if spec['target_id'] == str(f.OW.Other) and spec['attribute_id'] == str(f.OW.Quality))
        self.assertNotIn(ref, first.options)
        state.case.apply([f.fact('other', target='Other symptom', observation_id=spec['observation_id'],
                                episode_id=spec['episode_id'])])
        self.assertIn(ref, c.differential.prepare_selection(state).options)

    def test_exit_rebuilds_current_evidence_and_close_does_not_rank_twice(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(state, c.client)
        state.case.apply([f.fact('new', target='Other symptom')])
        c.differential.close(state, c.client)
        self.assertEqual(state.case.assessment.based_on_case_revision, state.case.revision)
        calls = len(c.client.requests)
        c.differential.close(state, c.client)
        self.assertEqual(len(c.client.requests), calls)
        self.assertEqual(c.client.requests[-1]['task'], 'clinical_rank')
        self.assertTrue(any(row.get('target') == 'Other symptom'
                            for row in c.client.requests[-1]['facts'].values()))

    def test_zero_dd_capacity_skips_selection_and_ranks_once(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis', initialized=True))
        state.session.usage['DifferentialDiagnosis'].actions = 20
        c.run(state)
        self.assertEqual([p['task'] for p in c.client.requests if p['task'].startswith('clinical_')],
                         ['clinical_rank'])
        self.assertNotIn('question_not_executable', str(state.interview.collection))
        self.assertTrue(state.case.assessment.frozen)
        self.assertEqual(state.session.termination, 'submitted')

    def test_selection_input_limit_closes_dd_then_completes_education(self):
        for tokens in (300_000, 300_001):
            with self.subTest(tokens=tokens):
                c = f.consultation(prepared=f.resources(education=True))
                state = f.chief(f.state('DifferentialDiagnosis'))
                state.session.input_tokens = tokens
                c.run(state)
                self.assertEqual([p['task'] for p in c.client.requests if p['task'].startswith('clinical_')],
                                 ['clinical_rank'])
                self.assertEqual(state.interview.collection['DifferentialDiagnosis:completion'],
                                 'dd_selection_input_limit')
                self.assertTrue(all('dd_selection_input_limit' in value
                    for key, value in state.interview.collection.items() if key.endswith('_shortfall')))
                self.assertEqual(state.case.diagnosis, state.case.assessment.differential[0].name)
                self.assertTrue(state.case.assessment.frozen)
                self.assertEqual(state.interview.education_status, 'complete')
                self.assertEqual(state.session.termination, 'submitted')

    def test_input_threshold_during_selection_skips_action_and_repair(self):
        c = f.consultation(prepared=f.resources(education=True))
        state = f.chief(f.state('DifferentialDiagnosis', initialized=True))
        state.session.input_tokens = 299_990
        c.client.chat_handler = lambda payload: {} if payload['task'] == 'clinical_action' else None
        c.run(state)
        self.assertEqual([p['task'] for p in c.client.requests if p['task'].startswith('clinical_')],
                         ['clinical_action', 'clinical_rank'])
        self.assertNotIn('question_not_executable', str(state.interview.collection))
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual(state.session.termination, 'submitted')

    def test_selection_only_input_limit_with_and_without_education(self):
        for enabled, tokens, available in ((True, 299_999, True), (True, 300_000, False),
                                          (False, 300_000, False)):
            with self.subTest(enabled=enabled, tokens=tokens):
                c = f.consultation(prepared=f.resources(education=enabled))
                state = f.chief(f.state('DifferentialDiagnosis'))
                state.session.input_tokens = tokens
                self.assertTrue(c.budget.can_start_action(state))
                self.assertEqual(c.differential.selection_available(state), available)

    def test_final_ranking_is_allowed_above_selection_input_limit(self):
        c = f.consultation(prepared=f.resources(education=True))
        state = f.chief(f.state('DifferentialDiagnosis'))
        state.session.input_tokens = 450_000
        c.differential.decide(state, c.client)
        self.assertEqual(c.client.requests, [])
        c.differential.close(state, c.client)
        self.assertEqual([p['task'] for p in c.client.requests], ['clinical_rank'])
        self.assertTrue(state.case.assessment.frozen)


if __name__ == '__main__':
    unittest.main()
