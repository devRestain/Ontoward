"""Preserve clinical inputs while sharing definitions and stopping rejected requests."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fixtures as f
from education_fixtures import education_response
from knowledge.guideline_passages import json_bytes, passages, project_documents, source_contexts
from workflow.education import generate_plan, parse_plan
from workflow.model_context import messages
from workflow.rules.assessment import graph_candidates
from workflow.rules.limits import LIMITS
from workflow.state.evidence import fixed_case_payload


class ClinicalRelationTests(unittest.TestCase):
    def test_identical_definitions_share_across_diseases_without_changing_assessment(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        candidates = graph_candidates(s.case, c.knowledge, s.interview)
        work = c.differential.prepare_decision(s, candidates=candidates)
        rows = work.payload['candidates']
        supports = [row['supports'] for row in rows]
        self.assertEqual(supports[0], supports[1])
        definitions = list(work.payload['relations'].values())
        self.assertEqual(len(definitions), len({json.dumps(row, sort_keys=True) for row in definitions}))
        self.assertEqual(set(work.refs.values()), set(candidates))
        c.differential.accept(s, {'ranked_disease_refs': [row['ref'] for row in rows]}, work, closing=True)
        for entry in s.case.assessment.differential:
            ident = c.knowledge.term_id(entry.name, 'Disease')
            self.assertEqual(entry, candidates[ident].entry)
        self.assertNotEqual(s.case.assessment.differential[0].supports[0].graph_ref.id,
                            s.case.assessment.differential[1].supports[0].graph_ref.id)

    def test_distinct_effect_scope_pattern_and_applicability_remain_distinct(self):
        k, s = f.knowledge(), f.chief(f.state('DifferentialDiagnosis'))
        f.add_pattern(k, 'differentEffect', f.OW.Complaint, [], effect='strong_support')
        f.add_pattern(k, 'differentScope', f.OW.Complaint, [], effect='support',
                      scope=dict(subject='patient', subject_member=None, time_context='any'))
        f.add_pattern(k, 'differentCondition', f.OW.Complaint, [], effect='support', applicability=[
            dict(concept_id=str(f.OW.Context), status='present', subject='family', time_context='past')])
        c = f.consultation(prepared=f.resources(k))
        work = c.differential.prepare_decision(s)
        relations = list(work.payload['relations'].values())
        self.assertTrue(any(r['effect'] == 'strong_support' for r in relations))
        self.assertTrue(any(r['rule_scope']['time_context'] == 'any' for r in relations))
        conditional = next(r for r in relations if r['applicability'])
        self.assertEqual(work.payload['conditions'][conditional['applicability']][0]['subject'], 'family')
        self.assertTrue(any(len(r['full_pattern']) > 1 for r in relations))
        self.assertEqual(len(relations), len({json.dumps(r, sort_keys=True) for r in relations}))

    def test_shared_relation_keeps_separate_observation_matches(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        s.case.apply([f.fact('second', observation_id='second', episode_id='second')])
        work = c.differential.prepare_decision(s)
        evidence = [work.payload['evidence'][ref] for ref in work.payload['candidates'][0]['supports']]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]['relation'], evidence[1]['relation'])
        self.assertNotEqual(evidence[0]['facts'], evidence[1]['facts'])
        self.assertEqual({i for row in evidence for i in row['facts']}, set(work.payload['facts']))


class ContextRejectionTests(unittest.TestCase):
    def test_context_rejection_returns_without_repair_or_action(self):
        for stage, closing in [('Initiation', False), ('ChiefComplaint', False),
                               ('DifferentialDiagnosis', False), ('DifferentialDiagnosis', True)]:
            with self.subTest(stage=stage, closing=closing):
                c, s = f.consultation(), f.chief(f.state(stage))
                c.client.chat = Mock(side_effect=f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400))
                if stage == 'DifferentialDiagnosis':
                    c.differential.decide(s, c.client, closing=closing)
                else:
                    c.sessions[stage].close(s, c.client)
                self.assertEqual((s.session.termination, s.session.reason), (None, None))
                c.client.chat.assert_called_once()
                self.assertEqual(c.client.chat.call_args.kwargs['max_tokens'], 8000)
                self.assertFalse(c.client.actions)
                self.assertIsNone(s.case.assessment)

        c, s = f.consultation(), f.state()
        c.client.chat = Mock(side_effect=f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400))
        c.brain.complete(s, c.client, role='gateway', messages=messages('Input', {}))
        self.assertEqual((s.session.termination, s.session.reason), (None, None))
        c.client.chat.assert_called_once()


class EducationLimitTests(unittest.TestCase):
    def test_local_guards_precede_request_ids_usage_and_executor_even_when_finalizing(self):
        for role in ('education', 'education_doctor'):
            for finalizing in (False, True):
                for guard in ('pending', 'messages', 'boundary'):
                    with self.subTest(role=role, finalizing=finalizing, guard=guard):
                        c, s = f.consultation(), f.state('Education')
                        s.session.finalizing = finalizing
                        c.brain.new_request_id = Mock(return_value='guard-request')
                        c.brain.executor.execute = Mock(return_value=f.FakeSDK.completion({}))
                        request = [{'role': 'user', 'content': ''}]
                        request[0]['content'] = 'x' * (LIMITS.education_max_messages_bytes - json_bytes(request))
                        if guard == 'pending':
                            s.session.budget_sync_required = True
                        elif guard == 'messages':
                            request[0]['content'] += 'x'
                        result = c.brain.complete(s, c.client, role=role, messages=request)
                        self.assertIsNone(s.session.termination)
                        self.assertTrue(s.session.models_available)
                        if guard == 'boundary':
                            self.assertIsNone(result.error)
                            self.assertEqual(result.request_id, 'guard-request')
                            c.brain.new_request_id.assert_called_once()
                            c.brain.executor.execute.assert_called_once()
                            self.assertEqual((s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens), (1, 20, 10))
                        else:
                            code = {'pending': 'BUDGET_SYNC_REQUIRED', 'messages': 'MESSAGE_LIMIT'}[guard]
                            self.assertEqual(result.error, 'LOCAL_EDUCATION_' + code)
                            self.assertIsNone(result.request_id)
                            c.brain.new_request_id.assert_not_called()
                            c.brain.executor.execute.assert_not_called()
                            self.assertEqual((s.session.doctor_calls, s.session.doctor_successes,
                                              s.session.input_tokens, s.session.output_tokens), (0, 0, 0, 0))

    def test_message_fit_fixes_contexts_once_and_oversized_repair_keeps_valid_english(self):
        source = dict(document_id='doc', path='doc.md', relation='exact', evidence_use='care_navigation',
            scope='Adults', text='# Management\r\nAdults only.\r\n## Treatment\r\n정확한 원문입니다.\r\n'
                '## Follow-up\r\nReview symptoms.\r\n')
        c, s = f.consultation(prepared=f.resources(education=True)), f.chief(f.state())
        f.freeze_for_education(c, s)
        c.knowledge.guidelines = SimpleNamespace(read=lambda _: ([source], []))
        initial = education_response({'task': 'education', 'phase': 'direct'})
        initial['P']['tests'][0].update(text='Discuss ' + 'care ' * 6000 + '.', basis='guideline',
            references=[dict(document_id='doc', quote='정확한 원문입니다.')])
        initial['P']['treatment'] = 'invalid rows'
        c.client.chat_handler = lambda payload: initial if payload['task'] == 'education' else None
        c.brain.new_request_id = Mock(wraps=c.brain.new_request_id)
        with patch('workflow.education.parse_plan', wraps=parse_plan) as parser:
            c.sessions['Education'].prepare_plan(s, c.client)
        self.assertEqual(len([p for p in c.client.requests if p['task'] == 'education']), 1)
        c.brain.new_request_id.assert_called_once()
        self.assertEqual(len(s.case.plan), 4)
        self.assertEqual(s.case.plan[0].text, initial['P']['tests'][0]['text'])
        self.assertEqual(s.interview.education_reason, 'education_model_error:LOCAL_EDUCATION_MESSAGE_LIMIT')
        contexts = parser.call_args.args[1]
        expected = [(source, passage) for passage in passages(source['text'])]
        self.assertEqual(contexts, source_contexts(expected))
        raw = source['text'].encode()
        ref = s.case.plan[0].references[0]
        self.assertEqual(raw[ref.start_byte:ref.end_byte], '정확한 원문입니다.'.encode())

        # Fit actual messages by dropping the last whole excerpt, then freeze validation contexts.
        for fixed_too_large in (False, True):
            c, s = f.consultation(prepared=f.resources(education=True)), f.chief(f.state())
            f.freeze_for_education(c, s)
            frozen = s.case.model_dump(exclude={'plan'})
            c.knowledge.guidelines = SimpleNamespace(read=lambda _: ([source], []))
            selected = [(source, passages(source['text'])[0])] if not fixed_too_large else []
            payload = dict(task='education', **fixed_case_payload(s.case),
                delivery_turn_budget=c.budget.action_capacity(s), phase='direct', documents=project_documents(selected))
            prompt_size = LIMITS.education_max_messages_bytes - json_bytes(messages('', payload))
            config = SimpleNamespace(prompt=lambda *routes: 'x' * (prompt_size + (1 if fixed_too_large else 0)))
            before = (s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens)
            c.brain.new_request_id = Mock(wraps=c.brain.new_request_id)
            with patch('workflow.education.parse_plan', wraps=parse_plan) as parser:
                generate_plan(s, c.client, c.knowledge, config, c.brain)
            if fixed_too_large:
                self.assertEqual(before, (s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens))
                c.brain.new_request_id.assert_not_called()
                parser.assert_not_called()
                self.assertFalse(s.case.plan)
            else:
                c.brain.new_request_id.assert_called_once()
                self.assertEqual(c.client.requests[-1]['documents'], project_documents(selected))
                self.assertEqual(parser.call_args.args[1], source_contexts(selected))
                self.assertEqual(len(s.case.plan), 5)
            self.assertEqual(s.case.model_dump(exclude={'plan'}), frozen)

    def test_context_error_blocks_same_prepare_mouth_then_syncs_and_completes_diagnose(self):
        for failed_role in ('education', 'education_doctor'):
            with self.subTest(failed_role=failed_role):
                c, s = f.consultation(prepared=f.resources(education=True)), f.chief(f.state())
                f.freeze_for_education(c, s)
                frozen = s.case.model_dump(exclude={'plan'})
                observed = []
                complete = c.brain.complete
                def track(*args, **kwargs):
                    before = (s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens, len(c.client.requests))
                    result = complete(*args, **kwargs)
                    after = (s.session.doctor_calls, s.session.input_tokens, s.session.output_tokens, len(c.client.requests))
                    observed.append((kwargs['role'], result, before, after, s.session.budget_sync_required))
                    return result
                c.brain.complete = track
                def response(payload):
                    if payload['task'] == 'education':
                        if payload['phase'] == 'repair':
                            raise f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400)
                        raw = education_response(payload)
                        for field, rows in raw['P'].items():
                            if field != 'tests':
                                rows[0]['utterances'] = ['가' * 31]
                        if failed_role == 'education':
                            raw['P']['treatment'] = 'invalid rows'
                        return raw
                    if payload['task'] == 'education_doctor':
                        raise f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400)
                c.client.chat_handler = response
                c.nova_session.refresh_snapshot = Mock(wraps=c.nova_session.refresh_snapshot)
                c.run(s)
                errors = [row for row in observed if row[1].error == 'CONTEXT_LIMIT_EXCEEDED']
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0][0], failed_role)
                self.assertIsNotNone(errors[0][1].request_id)
                self.assertTrue(errors[0][4])
                self.assertEqual(errors[0][3][0], errors[0][2][0] + 1)
                self.assertEqual(errors[0][3][1:3], errors[0][2][1:3])
                local = [row for row in observed if row[1].error == 'LOCAL_EDUCATION_BUDGET_SYNC_REQUIRED']
                if failed_role == 'education':
                    self.assertEqual(len(local), 1)
                    self.assertEqual(local[0][0], 'education_doctor')
                    self.assertIsNone(local[0][1].request_id)
                    self.assertEqual(local[0][2], local[0][3])
                self.assertEqual(s.session.termination, 'submitted')
                self.assertEqual(s.session.receipt['status'], 'completed')
                self.assertTrue(s.session.models_available)
                self.assertFalse(s.session.budget_sync_required)
                self.assertEqual(c.nova_session.refresh_snapshot.call_args_list[0].kwargs, {})
                self.assertEqual(c.nova_session.refresh_snapshot.call_args_list[-1].kwargs, {'final': True})
                self.assertEqual(len(s.case.plan), 4 if failed_role == 'education' else 5)
                self.assertEqual(s.case.model_dump(exclude={'plan'}), frozen)
                self.assertTrue(c.client.submissions[0]['note']['P']['tests'])
                undelivered = [a for a in s.interview.answers if a.plan_sentence_id and a.outcome == 'undelivered']
                self.assertTrue(undelivered)
                self.assertFalse(any(a.plan_sentence_id in {u.plan_sentence_id for u in undelivered}
                    and a.outcome == 'delivered' for a in s.interview.answers))
                self.assertTrue(any(a.plan_sentence_id == 'plan:tests:0' and a.outcome == 'delivered'
                    for a in s.interview.answers))


if __name__ == '__main__':
    unittest.main()
