"""Retain accepted disease rankings through resource and finalization failures."""
import unittest
from unittest.mock import Mock, patch

import fixtures as f
from workflow.rules.submission import validate_wire_payload
from workflow.state.models import Assessment, CaseFact


class RankedFinalizationTests(unittest.TestCase):
    def ranked(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis', initialized=True))
        work = c.differential.prepare_decision(state, mode='rank', closing=True)
        c.differential.accept(state, dict(ranked_disease_refs=list(reversed(work.refs))), work, closing=True)
        before = state.case.assessment
        state.case.apply([CaseFact(id='last-negative', value='No regular energy drink consumption',
            status='absent', category='social_history', source_ref='last-reply', turn=27)])
        return c, state, before

    def assert_retained(self, state, before):
        assessment = state.case.assessment
        self.assertTrue(assessment.frozen)
        self.assertEqual(assessment.differential, before.differential)
        self.assertEqual(assessment.based_on_case_revision, before.based_on_case_revision)
        self.assertEqual(assessment.based_on_chief_fact_id, before.based_on_chief_fact_id)
        self.assertEqual(assessment.based_on_response, before.based_on_response)
        self.assertEqual(assessment.frozen_case_revision, state.case.revision)
        self.assertEqual(assessment.frozen_chief_fact_id, state.case.chief_fact_id)
        self.assertEqual(state.case.diagnosis, before.differential[0].name)
        self.assertEqual(state.case.primary().kind, 'disease')

    def test_budget_and_context_errors_keep_first_rank_and_all_alternatives_through_submission(self):
        for failure in ('MODEL_TOKEN_BUDGET', 'CONTEXT_LIMIT_EXCEEDED', 'output_exhausted'):
            with self.subTest(failure=failure):
                c, state, before = self.ranked()
                c.client.chat = Mock(side_effect=f.NovaError(failure, 429))
                if failure == 'output_exhausted':
                    state.session.output_tokens = state.session.output_token_limit
                c.finalize(state)
                self.assert_retained(state, before)
                payload = state.session.final_payload
                validate_wire_payload(payload)
                self.assertEqual(payload['diagnosis'], before.differential[0].name)
                self.assertNotIn('submission:minimal', state.interview.collection)
                self.assertIn('not clinically reassessed', payload['note']['A']['evidence'])
                for entry in before.differential[1:]:
                    self.assertIn('r/o ' + entry.name, payload['note']['A']['differential'])
                self.assertIn('No regular energy drink consumption', payload['note']['S']['sh'])
                self.assertEqual(c.client.chat.call_count, 0 if failure == 'output_exhausted' else 1)
                c.finish_submission(state)
                self.assertEqual(state.session.termination, 'submitted')
                self.assertEqual(state.session.receipt['status'], 'completed')

    def test_graph_dependent_close_failure_and_minimal_writer_keep_the_same_ranked_list(self):
        c, state, before = self.ranked()
        with patch.object(c.differential, 'decide', side_effect=ValueError('rank preparation failed')), \
                patch.object(c.tools, 'chief_statuses', side_effect=ValueError('graph lookup failed')), \
                patch.object(c.writer, 'build_soap', side_effect=ValueError('normal Writer failed')):
            c.finalize(state)
        self.assert_retained(state, before)
        self.assertIn('submission:minimal', state.interview.collection)
        payload = state.session.final_payload
        validate_wire_payload(payload)
        self.assertIn('without final reassessment', payload['note']['A']['evidence'])
        for entry in before.differential[1:]:
            self.assertIn('r/o ' + entry.name, payload['note']['A']['differential'])
        c.finish_submission(state)
        self.assertEqual(state.session.termination, 'submitted')

    def test_missing_evidence_is_removed_without_changing_any_disease_rank(self):
        c, state, before = self.ranked()
        state.case.facts.pop('chief')
        c.differential.freeze_problem(state, 'graph failure')
        self.assertEqual([e.name for e in state.case.assessment.differential], [e.name for e in before.differential])
        self.assertEqual(state.case.primary().kind, 'disease')
        self.assertTrue(any('Invalid evidence references excluded' in v for v in state.case.assessment.limitations))
        for entry in state.case.assessment.differential:
            for ref in (*entry.supports, *entry.against, *entry.unresolved):
                self.assertTrue(set(ref.fact_ids) <= state.case.facts.keys())

    def test_frozen_case_boundary_still_rejects_changes_after_freeze(self):
        for change in ('facts', 'chief'):
            with self.subTest(change=change):
                c, state, before = self.ranked()
                c.differential.close(state, c.client, allow_model=False)
                self.assert_retained(state, before)
                if change == 'facts':
                    with self.assertRaisesRegex(ValueError, 'Clinical information is frozen'):
                        state.case.apply([CaseFact(id='after', category='other', value='New report after freeze', source_ref='after')])
                    state.case.revision += 1
                else:
                    state.case.chief_fact_id = None
                with self.assertRaisesRegex(ValueError, 'stale_frozen_assessment'):
                    c.writer.build_soap(state)

    def test_no_accepted_diseases_still_use_the_confirmed_symptom(self):
        for empty in (None, Assessment(based_on_case_revision=0, based_on_chief_fact_id=None)):
            with self.subTest(empty=empty):
                c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis', initialized=True))
                state.case.assessment = empty
                c.differential.close(state, c.client, allow_model=False)
                self.assertEqual(state.case.primary().kind, 'symptom')
                self.assertEqual(state.case.diagnosis, 'Test complaint')

    def test_display_error_does_not_relabel_a_disease_as_a_symptom(self):
        c, state, before = self.ranked()
        entry = before.differential[0].model_copy(update={'name': 'Long disease name ' * 40})
        state.case.assessment = before.model_copy(update={'differential': (entry, *before.differential[1:])})
        c.differential.freeze_fallback(state, 'display boundary')
        self.assertEqual(state.case.primary().kind, 'disease')
        self.assertEqual(state.case.diagnosis, entry.name)


if __name__ == '__main__':
    unittest.main()
