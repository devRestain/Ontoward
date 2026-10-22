"""Focused offline checks for the saved 20261022T075835Z failures."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import fixtures as f
from protocol import decode_context
from education_fixtures import education_response
from test_d66 import collection_knowledge, finish_early, receipt
from workflow.education import _EducationWork, generate_plan, parse_plan
from workflow.rules.dd import action_counts
from workflow.rules.decision import clinical_messages
from workflow.rules.limits import LIMITS, PLAN_FIELDS, PLAN_SECTIONS


class SavedRunRepairs(unittest.TestCase):
    def test_rejected_exam_reselects_then_exhausts_remaining_questions(self):
        client = f.FakeSDK(chat_handler=finish_early)
        original = client._action
        rejected = []
        def action(kind, text, request_id):
            if kind == 'EXAM' and not rejected:
                rejected.append(request_id)
                raise f.NovaError('EXAM_NOT_SPECIFIC')
            raw = original(kind, text, request_id)
            raw['content' if kind == 'SAY' else 'result'] = '모르겠습니다'
            return raw
        client._action = action
        c = f.consultation(client, f.resources(collection_knowledge(say=4, exam=3)))
        state = f.chief(f.state('DifferentialDiagnosis'))
        c.differential.prepare = Mock(wraps=c.differential.prepare)
        c.run(state)
        self.assertEqual(state.session.termination, 'submitted')
        self.assertEqual(action_counts(state.interview), {'SAY': 4, 'EXAM': 2})
        failed = next(a for a in state.interview.answers if a.source_ref == rejected[0])
        self.assertEqual((failed.outcome, failed.turn, failed.response),
                         ('undelivered', None, {'error': 'EXAM_NOT_SPECIFIC'}))
        self.assertTrue(any(p['task'] == 'clinical_action' for p in client.requests))
        self.assertGreater(c.differential.prepare.call_count, len(client.actions) - state.session.fixed_actions)
        self.assertTrue(any(a.key[0] == 'EXAM' and a.turn for a in state.interview.answers))
        self.assertIn('registered_questions_exhausted', state.interview.collection['DifferentialDiagnosis:EXAM_shortfall'])

    def test_missing_wrapper_uses_same_row_and_citation_validation(self):
        raw = education_response({'task': 'education'})['P']
        progress = _EducationWork()
        _, errors = parse_plan(raw, {}, progress)
        self.assertFalse(errors)
        self.assertEqual(len(progress.sentences), 5)
        raw['tests'][0]['basis'] = 'guideline'
        raw['tests'][0]['references'] = [{'document_id': 'unknown', 'quote': 'Absent source'}]
        progress = _EducationWork()
        _, errors = parse_plan(raw, {}, progress)
        self.assertTrue(any('outside the supplied source context' in e for e in errors))
        self.assertFalse(any(s.field == 'tests' for s in progress.sentences))
        _, errors = parse_plan({**raw, 'unexpected': []}, {}, _EducationWork())
        self.assertEqual(errors, ['expected P object with assigned sentence arrays'])

    def test_two_unwrapped_sections_need_no_paid_format_repair(self):
        client = f.FakeSDK(chat_handler=lambda p: education_response(p)['P'])
        c = f.consultation(client, f.resources(education=True))
        state = f.chief(f.state('Education'))
        f.freeze(state)
        c.sessions['Education'].prepare_plan(state, client)
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual(len(client.requests), 2)
        self.assertEqual({s.field for s in state.case.plan}, set(PLAN_FIELDS))
        self.assertEqual(sum(p['delivery_turn_budget'] for p in client.requests), c.budget.action_capacity(state))

    def test_near_limit_documents_leave_space_for_two_repairs(self):
        def reply(payload):
            return {} if payload['phase'] == 'direct' else education_response(payload)
        c = f.consultation(f.FakeSDK(chat_handler=reply), f.resources(education=True))
        state = f.chief(f.state('Education'))
        f.freeze(state)
        source = dict(document_id='doc', path='doc.md', relation='exact', evidence_use='care_navigation',
            text='# Management\nAdults.\n' + ''.join(f'## Treatment {i}\n' + 'Complete advice. ' * 65 + '\n' for i in range(9)))
        c.knowledge.guidelines = SimpleNamespace(read=lambda *args, **kwargs: ([source], []))
        config = SimpleNamespace(prompt=lambda *routes: c.config.prompt(*routes) + '\n' + 'x' * 25000)
        c.client.chat = Mock(wraps=c.client.chat)
        generate_plan(state, c.client, c.knowledge, config, c.brain)
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual(len(c.client.requests), 4)
        packets = [p['documents'] for p in c.client.requests]
        self.assertTrue(all(p == packets[0] for p in packets))
        self.assertLess(len(packets[0][0]['excerpts']) if packets[0] else 0, 7)
        for call in c.client.chat.call_args_list:
            size = len(json.dumps(call.kwargs['messages'], ensure_ascii=False,
                separators=(',', ':'), allow_nan=False).encode())
            self.assertLessEqual(size, LIMITS.education_max_messages_bytes)
        for section in PLAN_SECTIONS:
            self.assertEqual(len({p['delivery_turn_budget'] for p in c.client.requests if p['section'] == section}), 1)

    def test_unknown_attribute_repeat_blocks_same_episode_and_preserves_distinct_scopes(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        spec = c.tools._spec(state, str(f.OW.Complaint), str(f.OW.Quality), 'obs2', 'episode1')
        state.interview.answers.append(receipt('SAY', 1, scope='ChiefComplaint',
            key=('SAY', 'Test complaint', 'Quality', 'patient', '', 'current', 'obs1', 'episode1')))
        self.assertFalse(c.tools._eligible(state, spec))
        for changes in ({'episode_id': 'episode2'}, {'time_context': 'past'},
                        {'subject': 'family', 'subject_member': 'father'},
                        {'attribute_id': str(f.OW.Location)}):
            with self.subTest(changes=changes):
                self.assertFalse(c.tools.repeated_unknown_attribute(state, {**spec, **changes}))
        # Shared generic wording alone cannot prove that two targets are equivalent.
        c.knowledge._graph.add((f.OW.Other, f.OW.hasAttribute, f.OW.Quality))
        other = c.tools._spec(state, str(f.OW.Other), str(f.OW.Quality), 'obs3', 'episode1')
        self.assertFalse(c.tools.repeated_unknown_attribute(state, other))
        self.assertFalse(any(fact.attribute == 'Quality' for fact in state.case.current_facts()))

    def test_cc_and_dd_share_unknown_repeat_rule_and_wire_keeps_attempt_scope(self):
        c, state = f.consultation(), f.chief(f.state('ChiefComplaint'))
        state.interview.answers.append(receipt('SAY', 1, scope='ChiefComplaint',
            key=('SAY', 'Test complaint', 'Quality', 'patient', '', 'current', 'old-observation', 'episode1')))
        c.sessions['ChiefComplaint'].prepare_collection(state)
        self.assertFalse(any(q.attribute == 'Quality' for q in state.interview.queue))
        state.interview.current = 'DifferentialDiagnosis'
        before = copy.deepcopy(state.case.model_dump())
        work = c.differential.prepare_decision(state)
        wire = decode_context(clinical_messages(c.config, work)[-1]['content'])
        asked = wire['asked_questions'][0]
        self.assertEqual((asked['attribute'], asked['outcome']), ('Quality', 'unknown'))
        self.assertIn(asked['scope'], wire['scopes'])
        self.assertIn('episode', wire['scopes'][asked['scope']])
        self.assertEqual(state.case.model_dump(), before)


if __name__ == '__main__':
    unittest.main()
