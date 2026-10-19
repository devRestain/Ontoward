import copy
import unittest

import fixtures as f
from workflow.state.models import CaseFact


class SessionOwnershipTests(unittest.TestCase):
    def test_context_entry_accepts_only_a_current_successful_cc_exit(self):
        for unavailable in (None, 'not_closed', 'failed', 'stale_revision', 'changed_chief', 'frozen'):
            with self.subTest(unavailable=unavailable):
                c, state = f.consultation(), f.chief(f.state('ChiefComplaint'))
                cc = c.sessions['ChiefComplaint']
                cc.close(state, c.client)
                expected = tuple(c.knowledge.term_id(e.name, 'Disease') for e in state.case.assessment.differential)
                if unavailable == 'not_closed':
                    cc.closed = False
                elif unavailable == 'failed':
                    cc.error = 'invalid_or_incomplete_ranking'
                elif unavailable == 'stale_revision':
                    state.case.apply([CaseFact(id='medicine', category='medication', value='Reported medication',
                        source_ref='late-reply', acquisition='SAY')])
                elif unavailable == 'changed_chief':
                    state.case.chief_fact_id = 'another-chief'
                elif unavailable == 'frozen':
                    state.case.assessment = state.case.assessment.model_copy(update={'frozen': True})
                state.interview.current = 'ContextFactor'
                calls = len(c.client.requests)
                c.enter_session(state)
                context = c.sessions['ContextFactor']
                self.assertEqual(context.candidate_ids, expected if unavailable is None else ())
                if unavailable:
                    self.assertEqual(state.interview.collection['ContextFactor:candidates'], 'cc_assessment_unavailable')
                self.assertEqual(len(c.client.requests), calls)

    def test_budget_exit_ranks_the_latest_facts_in_each_early_session_once(self):
        for stage in ('Initiation', 'ChiefComplaint', 'ContextFactor'):
            for prior in (False, True):
                with self.subTest(stage=stage, prior=prior):
                    c, state = f.consultation(), f.chief(f.state(stage))
                    if prior:
                        c.sessions[stage].close(state, c.client)
                    state.case.apply([CaseFact(id='medicine', category='medication',
                        value='Reported medication 10 mg at night', source_ref='last-reply', acquisition='SAY')])
                    c.client.remaining = 0
                    state.session.turns_remaining = 0
                    calls = len(c.client.requests)
                    c.check_budget(state)
                    self.assertEqual(len(c.client.requests), calls + 1)
                    self.assertEqual(c.client.requests[-1]['task'], 'clinical_rank')
                    self.assertIn('10 mg at night', str(c.client.requests[-1]['facts']))
                    self.assertTrue(state.case.assessment.frozen)
                    self.assertEqual(state.case.assessment.based_on_case_revision, state.case.revision)
                    self.assertEqual(state.case.primary().kind, 'disease')
                    self.assertEqual(state.interview.collection[stage + ':completion'], 'turn_budget')
                    frozen = copy.deepcopy(state.case.model_dump())
                    c.close_collection(state)
                    c.finalize(state)
                    self.assertEqual(len(c.client.requests), calls + 1)
                    self.assertEqual(state.case.model_dump(), frozen)
                    self.assertFalse(c.client.actions)

    def test_early_exit_without_model_resources_keeps_confirmed_chief_fallback(self):
        for stage in ('Initiation', 'ChiefComplaint', 'ContextFactor'):
            with self.subTest(stage=stage):
                c, state = f.consultation(), f.chief(f.state(stage))
                state.session.models_available = False
                c.check_budget(state)
                self.assertTrue(state.case.assessment.frozen)
                self.assertEqual(state.case.primary().kind, 'symptom')
                self.assertIn('MODEL_UNAVAILABLE', state.case.assessment.limitations)
                self.assertFalse(c.client.requests)
                c.close_collection(state)
                self.assertFalse(c.client.requests)

    def test_rendering_does_not_schedule_or_record_education(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                def response(payload):
                    if invalid and payload['task'] == 'education_doctor':
                        return {'items': []}
                c = f.consultation(f.FakeSDK(chat_handler=response), f.resources(education=True))
                state = f.chief(f.state())
                f.freeze_for_education(c, state)
                owner = c.sessions['Education']
                owner.prepare_plan(state, c.client)
                before = copy.deepcopy((state.case.model_dump(), state.interview.model_dump()))
                text, _ = c.mouth.render_diagnosis(state, c.client, c.knowledge)
                self.assertTrue(text)
                sentence = state.case.plan[0]
                rendered, errors = c.mouth.render_education(state, c.client,
                    [{'id': sentence.id, 'text': sentence.text}], {sentence.id: 1}, 1)
                self.assertEqual(bool(rendered), not invalid)
                self.assertEqual(bool(errors), invalid)
                self.assertEqual((state.case.model_dump(), state.interview.model_dump()), before)

    def test_education_reentry_never_renders_queued_delivered_or_failed_groups_again(self):
        for result in ('queued', 'delivered', 'undelivered'):
            with self.subTest(result=result):
                def response(payload):
                    if result == 'undelivered' and payload['task'] == 'education':
                        from education_fixtures import education_response
                        raw = education_response(payload)
                        for rows in raw['P'].values():
                            rows[0]['utterances'] = []
                        return raw
                    if result == 'undelivered' and payload['task'] == 'education_doctor':
                        return {'items': []}
                c = f.consultation(f.FakeSDK(chat_handler=response), f.resources(education=True))
                state = f.chief(f.state('Education', initialized=True))
                f.freeze_for_education(c, state)
                owner = c.sessions['Education']
                owner.prepare_plan(state, c.client)
                owner.prepare_delivery(state, c.client)
                if result == 'delivered':
                    while state.interview.queue:
                        c.select_action(state)
                        c.mouth.validate_action(state)
                        c.mouth.execute_action(state, c.client)
                        c.ear.process_input(state, c.knowledge, c.client)
                    self.assertTrue(all(a.outcome == 'delivered' for a in state.interview.answers))
                elif result == 'undelivered':
                    self.assertEqual(len(state.interview.answers), 5)
                    self.assertTrue(all(a.outcome == 'undelivered' for a in state.interview.answers))
                calls = len(c.client.requests)
                before = copy.deepcopy((state.case.model_dump(), state.interview.model_dump()))
                owner.prepare_delivery(state, c.client)
                owner.prepare_delivery(state, c.client)
                self.assertEqual(len(c.client.requests), calls)
                self.assertEqual((state.case.model_dump(), state.interview.model_dump()), before)
