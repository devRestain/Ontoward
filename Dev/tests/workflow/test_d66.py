"""D66 collection receipts, SOAP provenance and independent Education sections."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fixtures as f
from education_fixtures import education_response
from knowledge.guidelines import GuidelineLibrary
from workflow.education import _EducationWork, parse_plan
from workflow.rules.dd import action_counts
from workflow.rules.decision import clinical_messages
from workflow.rules.limits import DD_MINIMUMS, PLAN_SECTIONS, SESSION_INTERVIEW_LIMITS
from workflow.rules.minimal_record import minimal_payload
from workflow.state.models import Answer, CaseFact, ObservedNumber
from protocol import decode_context


def receipt(kind, number, *, scope='DifferentialDiagnosis', outcome='unknown', source=None, key=None, fact_ids=()):
    return Answer(question_id=f'q{number}', source_ref=source or f'request{number}', scope=scope,
        purpose='feature', outcome=outcome, turn=number, fact_ids=fact_ids,
        key=key or (kind, 'Test complaint', '', 'patient', '', 'current', 'obs1', 'episode1'),
        response=dict(status='OK', turn=number, turns_remaining=50-number,
                      **{'content' if kind == 'SAY' else 'result': '모르겠습니다'}))


def collection_knowledge(say=12, exam=7):
    k = f.knowledge()
    # The base fixture has Location and Context SAY options and one EXAM.
    for kind, amount in (('SAY', max(0, say-2)), ('EXAM', max(0, exam-1))):
        for number in range(amount):
            ident = f.OW[f'zz{kind}{number:03d}']
            k._graph.add((ident, f.RDF.type, f.OW.Symptom if kind == 'SAY' else f.OW.ExamFinding))
            k._graph.add((ident, f.RDFS.label, f.Literal(f'{kind} observation {number}', lang='en')))
            if kind == 'SAY':
                k.questions[str(ident)] = f.QuestionTemplate(text=f'등록 증상 {number} 있나요?', answer_type='presence', affirmative=True)
            else:
                method = f.OW[f'zzMethod{number:03d}']
                k._graph.add((ident, f.OW.detectedBy, method))
                k._graph.add((method, f.RDF.type, f.OW.ExamMethod))
                k._graph.add((method, f.OW.examRequestText, f.Literal(f'등록 부위 {number} 진찰합니다.')))
            f.add_pattern(k, f'zz{kind}Pattern{number:03d}', ident, [])
    k.validate_question_assets()
    k.prepare_terms()
    return k


def finish_early(payload):
    if payload['task'] in {'clinical_rank', 'clinical_decision', 'clinical_action'}:
        reply = {} if payload['task'] == 'clinical_action' else {
            'ranked_disease_refs': [row['ref'] for row in payload['candidates']]}
        if payload['task'] != 'clinical_rank':
            reply['next_action'] = {'kind': 'finish_collection'}
        return reply
    if payload['task'] == 'input_context':
        return {'statements': []}


class DDCollectionTests(unittest.TestCase):
    def run_collection(self, knowledge, handler=finish_early):
        c = f.consultation(f.FakeSDK(chat_handler=handler), f.resources(knowledge))
        state = f.chief(f.state('DifferentialDiagnosis'))
        original = c.client._action
        def unknown(kind, content, request_id):
            raw = original(kind, content, request_id)
            raw['content' if kind == 'SAY' else 'result'] = '모르겠습니다'
            return raw
        c.client._action = unknown
        initial = c.tools._options(state, c.differential.prepare_decision(state).candidates)
        c.run(state)
        return c, state, initial

    def test_early_finish_and_invalid_action_repair_still_collect_ten_say_five_exam(self):
        c, state, _ = self.run_collection(collection_knowledge())
        self.assertEqual(action_counts(state.interview), DD_MINIMUMS)
        self.assertEqual(state.session.usage['DifferentialDiagnosis'].actions, 15)
        self.assertEqual(state.session.termination, 'submitted')
        self.assertTrue(state.case.assessment.frozen)
        self.assertIn('DifferentialDiagnosis:action_fallback', state.interview.collection)
        self.assertFalse(any(key.endswith('_shortfall') for key in state.interview.collection))
        self.assertEqual(SESSION_INTERVIEW_LIMITS['ChiefComplaint'], (5, 10))
        self.assertEqual(SESSION_INTERVIEW_LIMITS['DifferentialDiagnosis'], (15, 20))
        self.assertTrue(all(a.outcome == 'unknown' for a in state.interview.answers))
        self.assertLessEqual(sum(u.actions for u in state.session.usage.values()), 50)

    def test_short_lists_are_exhausted_without_generating_or_repeating_questions(self):
        c, state, options = self.run_collection(collection_knowledge(say=4, exam=2))
        expected = Counter(spec['kind'] for spec, _ in options.values())
        self.assertEqual(action_counts(state.interview), dict(expected))
        self.assertEqual(len(c.client.actions) - state.session.fixed_actions, len(options))
        keys = [a.key for a in state.interview.answers]
        self.assertEqual(len(keys), len(set(keys)))
        for kind, minimum in DD_MINIMUMS.items():
            self.assertIn(str(minimum-expected[kind]), state.interview.collection[f'DifferentialDiagnosis:{kind}_shortfall'])
            self.assertIn('registered_questions_exhausted', state.interview.collection[f'DifferentialDiagnosis:{kind}_shortfall'])
        supplied = {spec['text'] for spec, _ in options.values()}
        from workflow.rules.limits import FIXED_UTTERANCES
        fixed = {text for lines in FIXED_UTTERANCES.values() for text in lines}
        self.assertTrue(all(row['content'] in supplied | fixed for row in c.client.actions))
        self.assertEqual(state.session.termination, 'submitted')

    def test_counts_require_actual_receipts_and_deduplicate_requests(self):
        state = f.state('DifferentialDiagnosis')
        good = receipt('SAY', 1)
        state.interview.answers = [good, good.model_copy(), receipt('EXAM', 2),
            receipt('SAY', 3, scope='ChiefComplaint'), receipt('SAY', 4, outcome='undelivered'),
            receipt('SAY', 5).model_copy(update={'response': {'error': 'API_UNAVAILABLE'}}),
            receipt('SAY', 6).model_copy(update={'turn': None})]
        self.assertEqual(action_counts(state.interview), {'SAY': 1, 'EXAM': 1})
        from inspection import dd_collection_metrics
        metrics = dd_collection_metrics(state.interview.model_dump(mode='json'))
        self.assertEqual({kind: value['received'] for kind, value in metrics.items()}, action_counts(state.interview))
        self.assertEqual(metrics['SAY']['shortfall'], 9)
        self.assertIsNone(dd_collection_metrics({'answers': [{'scope': 'DifferentialDiagnosis'}]}))

    def test_unavailable_channels_and_invalid_exam_assets_are_not_options(self):
        k = collection_knowledge(say=4, exam=3)
        k._graph.set((f.OW.MethodX, f.OW.examRequestText, f.Literal('x' * 31)))
        c, state = f.consultation(prepared=f.resources(k)), f.chief(f.state('DifferentialDiagnosis'))
        work = c.differential.prepare_decision(state)
        self.assertFalse(any(spec['target_id'] == str(f.OW.ExamX) for spec in work.options.values()))
        state.session.allowed_actions = ['SAY', 'DIAGNOSE']
        work = c.differential.prepare_decision(state)
        self.assertTrue(work.options)
        self.assertTrue(all(spec['kind'] == 'SAY' for spec in work.options.values()))

    def test_input_question_keeps_every_registered_value_above_fifty(self):
        k = f.knowledge()
        for index in range(60):
            value = f.OW[f'ExtraValue{index}']
            k._graph.add((value, f.RDF.type, f.OW.AttributeValue))
            k._graph.add((value, f.RDFS.label, f.Literal(f'Extra value {index}', lang='en')))
            k._graph.add((f.OW.Quality, f.OW.canHaveValue, value))
        k.prepare_terms()
        c, state = f.consultation(prepared=f.resources(k)), f.chief(f.state('DifferentialDiagnosis'))
        q = c.tools._question(c.tools._spec(state, str(f.OW.Complaint), str(f.OW.Quality), 'obs1', 'episode1'), 'value-question', 0, 0)
        c.questions.register(state, q)
        c.interactions.select_question(state, q)
        c.client.chat_handler = lambda payload: {'statements': []}
        c.ear._context(state, k, c.client, 'A detailed reply')
        supplied = c.client.requests[0]['question']['allowed_values']
        self.assertEqual(len(supplied), 61)
        self.assertEqual(set(supplied), {k.term(value) for value in k.get_attribute_values(str(f.OW.Quality))})

    def test_dd_ceiling_and_education_reservation_survive_more_available_questions(self):
        def keep_asking(payload):
            if payload['task'].startswith('clinical_'):
                from brain_double import clinical_response
                return clinical_response(payload)
            return finish_early(payload)
        c, state, _ = self.run_collection(collection_knowledge(say=24, exam=9), keep_asking)
        self.assertEqual(state.session.usage['DifferentialDiagnosis'].actions, 20)
        self.assertGreaterEqual(action_counts(state.interview)['SAY'], 10)
        self.assertGreaterEqual(action_counts(state.interview)['EXAM'], 5)
        enabled = f.consultation(prepared=f.resources(education=True))
        late = f.chief(f.state('DifferentialDiagnosis', turns=22))
        self.assertEqual(enabled.budget.action_capacity(late), 13)
        self.assertEqual(state.session.termination, 'submitted')

    def test_all_options_relations_and_fact_scopes_survive_above_fifty(self):
        k = collection_knowledge(say=65, exam=2)
        c, state = f.consultation(prepared=f.resources(k)), f.chief(f.state('DifferentialDiagnosis'))
        exam = next((spec for spec, _ in c.tools._options(state, c.differential.prepare_decision(state).candidates).values()
                     if spec['kind'] == 'EXAM' and spec['target_id'] == str(f.OW.ExamX)))
        key = c.tools._question(exam, '', 0, 0).semantic_key()
        state.interview.answers.append(receipt('EXAM', 1, key=key))
        state.case.apply([CaseFact(id=f'n{i}', category='other', value=f'Accepted report {i}',
            source_ref='initial', observation_id=f'preserved{i}', episode_id=f'preserved{i}') for i in range(55)])
        work = c.differential.prepare_decision(state)
        wire = decode_context(clinical_messages(c.config, work)[-1]['content'])
        self.assertEqual({q['kind'] for q in wire['questions']}, {'SAY', 'EXAM'})
        self.assertEqual(len(wire['facts']), 56)
        self.assertGreater(len(wire['relations']), 50)
        self.assertGreater(len(wire['evidence']), 50)
        self.assertGreater(len(wire['questions']), 50)
        self.assertEqual(len(wire['questions']), len(work.options))
        self.assertFalse(wire['resources']['finish_allowed'])
        self.assertEqual(wire['resources']['required_exam'], 4)
        for q in wire['questions']:
            self.assertIn(q['scope'], wire['scopes'])
            for group in q['expected_groups']:
                for entry in group['entries']:
                    if entry.get('relation'):
                        self.assertIn(entry['relation'], wire['relations'])


class ROSProvenanceTests(unittest.TestCase):
    def test_dd_symptom_details_use_ros_in_normal_and_independent_minimal_writer(self):
        c, state = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        rows = [f.fact('dd-quality', kind='attribute', attribute='Quality', values=('dull',),
                       category='quality', source_ref='request1', turn=1),
            f.fact('dd-absent', target='Other symptom', status='absent', category=None,
                   source_ref='request1', turn=1, observation_id='other', episode_id='other'),
            CaseFact(id='dd-note', category='other', value='Frequency is intermittent', source_ref='request1', acquisition='SAY', turn=1),
            CaseFact(id='dd-number', category='measurement', value='Reported weight change',
                measurement=ObservedNumber(kind='quantity', value=7, unit='kg'), source_ref='request1', acquisition='SAY', turn=1),
            CaseFact(id='med', category='medication', value='Taking prescribed medicine', source_ref='request1', acquisition='SAY', turn=1),
            CaseFact(id='family', category='family_history', value='Family thyroid disease', subject='family',
                     source_ref='request1', acquisition='SAY', turn=1),
            f.graph_fact(id='exam', kind='finding', target='Test examination finding', acquisition='EXAM',
                         source_ref='request2', turn=2, observation_id='exam', episode_id='exam')]
        state.case.apply(rows)
        state.interview.answers = [receipt('SAY', 1, outcome='mapped', fact_ids=tuple(row.id for row in rows[:-1])),
                                   receipt('EXAM', 2, outcome='mapped', fact_ids=('exam',))]
        f.freeze(state)
        c.writer.build_soap(state)
        normal = state.turn.payload['note']
        with patch.object(c.knowledge, 'term_id', side_effect=AssertionError('Minimal Writer must avoid graph calls')):
            minimal = minimal_payload(state.case, state.interview, state.case.primary().name)['note']
        for note in (normal, minimal):
            for fragment in ('Quality', 'Other symptom', 'Frequency is intermittent', 'Reported weight change', '7'):
                self.assertIn(fragment, note['S']['ros'])
            self.assertNotIn('Frequency is intermittent', note['S']['hpi'])
            self.assertNotIn('Quality', note['S']['hpi'])
            self.assertIn('Test complaint', note['S']['hpi'])
            self.assertIn('Taking prescribed medicine', note['S']['pmh'])
            self.assertIn('Family thyroid disease', note['S']['fh'])
            self.assertIn('Test examination finding', note['O']['exam'])
        self.assertEqual(normal['S']['ros'].count('Frequency is intermittent'), 1)


class SectionPlanningTests(unittest.TestCase):
    def planning(self, handler=None):
        c = f.consultation(f.FakeSDK(chat_handler=handler), f.resources(education=True))
        state = f.chief(f.state('Education'))
        f.freeze(state)
        c.client.chat = Mock(wraps=c.client.chat)
        return c, state

    def test_two_distinct_medium_requests_preserve_all_five_fields_and_fixed_context(self):
        c, state = self.planning()
        frozen = copy.deepcopy(state.case.model_dump(exclude={'plan'}))
        c.sessions['Education'].prepare_plan(state, c.client)
        requests = c.client.requests
        self.assertEqual([p['section'] for p in requests], list(PLAN_SECTIONS))
        self.assertEqual([p['fields'] for p in requests], [list(fields) for fields in PLAN_SECTIONS.values()])
        prompts = [call.kwargs['messages'][0]['content'] for call in c.client.chat.call_args_list]
        self.assertEqual(len(set(prompts)), 2)
        for call in c.client.chat.call_args_list:
            self.assertEqual(call.kwargs['reasoning_effort'], 'medium')
            self.assertEqual(call.kwargs['max_tokens'], 8000)
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual({s.field for s in state.case.plan}, set(f for fields in PLAN_SECTIONS.values() for f in fields))
        self.assertEqual(state.case.model_dump(exclude={'plan'}), frozen)
        self.assertEqual([len(p['accepted_plan']) for p in requests], [0, 2])
        self.assertEqual([p['fields'] for p in requests],
                         [['tests', 'treatment'], ['disposition', 'follow_up', 'education']])
        self.assertEqual([p['delivery_turn_budget'] for p in requests], [4, 6])
        c.sessions['Education'].prepare_plan(state, c.client)
        self.assertEqual(c.client.chat.call_count, 2)

    def test_initial_sections_precede_one_local_truncation_repair(self):
        def respond(payload):
            if payload['task'] == 'education':
                if payload['section'] == 'disposition_follow_up_education' and payload['phase'] == 'direct':
                    return f.FakeSDK.completion('', finish_reason='length')
                return education_response(payload)
        c, state = self.planning(respond)
        c.sessions['Education'].prepare_plan(state, c.client)
        self.assertEqual([(p['section'], p['phase']) for p in c.client.requests],
                         [(s, 'direct') for s in PLAN_SECTIONS] + [('disposition_follow_up_education', 'repair')])
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual(len(state.case.plan), 5)
        self.assertEqual(c.client.requests[-1]['generation_error'], 'OUTPUT_TRUNCATED')

    def test_partial_pair_repair_keeps_accepted_test_bytes_and_other_sections(self):
        accepted = []
        def respond(payload):
            raw = education_response(payload)
            if payload['section'] == 'tests_treatment':
                if payload['phase'] == 'direct':
                    accepted.append(copy.deepcopy(raw['P']['tests'][0]))
                    raw['P']['treatment'] = []
                else:
                    self.assertEqual(payload['accepted'][0]['text'], accepted[0]['text'])
                    raw['P'] = {'treatment': raw['P']['treatment']}
            return raw
        c, state = self.planning(respond)
        c.sessions['Education'].prepare_plan(state, c.client)
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual(len(state.case.plan), 5)
        self.assertEqual(next(s.text for s in state.case.plan if s.field == 'tests'), accepted[0]['text'])

    def test_failed_sections_are_each_repaired_at_most_once_and_not_replayed(self):
        c, state = self.planning(lambda payload: {'P': {}})
        c.sessions['Education'].prepare_plan(state, c.client)
        c.sessions['Education'].prepare_plan(state, c.client)
        self.assertEqual(Counter(p['section'] for p in c.client.requests), dict.fromkeys(PLAN_SECTIONS, 2))
        self.assertEqual(c.client.chat.call_count, 4)
        self.assertEqual(state.interview.education_status, 'failed')

    def test_triple_group_repair_preserves_accepted_disposition_and_education(self):
        def respond(payload):
            raw = education_response(payload)
            if payload['section'] == 'disposition_follow_up_education':
                if payload['phase'] == 'direct':
                    raw['P']['follow_up'] = []
                else:
                    self.assertEqual({row['field'] for row in payload['accepted']}, {'disposition', 'education'})
                    self.assertEqual(payload['delivery_turn_budget'], 6)
                    raw['P'] = {'follow_up': raw['P']['follow_up']}
            return raw
        c, state = self.planning(respond)
        c.sessions['Education'].prepare_plan(state, c.client)
        self.assertEqual(state.interview.education_status, 'complete')
        self.assertEqual(len(c.client.requests), 3)
        self.assertEqual(len(state.case.plan), 5)

    def test_assigned_field_validation_cannot_accept_another_sections_content(self):
        raw = education_response({'task': 'education'})
        progress = _EducationWork()
        _, errors = parse_plan(raw, {}, progress, fields=('education',))
        self.assertIn('unexpected P fields', errors)
        self.assertEqual([s.field for s in progress.sentences], ['education'])

    def test_no_output_left_keeps_accepted_pair_and_finishes_without_another_model_call(self):
        c, state = self.planning()
        state.session.output_tokens = 99_990
        c.sessions['Education'].prepare_plan(state, c.client)
        self.assertEqual(c.client.chat.call_count, 1)
        self.assertEqual({s.field for s in state.case.plan}, {'tests', 'treatment'})
        self.assertEqual(state.interview.education_status, 'partial')
        c.run(state)
        self.assertEqual(state.session.termination, 'submitted')
        self.assertEqual(c.client.chat.call_count, 1)
        self.assertEqual(state.session.output_tokens, 100_000)

    def test_three_verified_documents_are_shared_across_both_sections(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', NOVA_GUIDELINES_DIR=folder):
            root = Path(folder)
            selections = []
            for index in range(6):
                raw = f'# Management\nAdults.\n## Treatment\nComplete advice {index}.\n'.encode()
                (root / f'{index}.md').write_bytes(raw)
                selections.append(dict(document_id=f'd{index}', path=f'{index}.md',
                    sha256=hashlib.sha256(raw).hexdigest(), relation='exact', evidence_use='care_navigation', scope='Adults'))
            (root/'0.md').write_text('Hash failure')
            library = GuidelineLibrary({'disease': selections})
            documents, failures = library.read('disease', max_documents=3)
            self.assertEqual([d['document_id'] for d in documents], ['d1', 'd2', 'd3'])
            self.assertEqual([d['document_id'] for d in failures], ['d0'])
            c, state = self.planning()
            c.knowledge.guidelines = GuidelineLibrary({str(f.OW.Alpha): selections})
            c.sessions['Education'].prepare_plan(state, c.client)
            packets = [p['documents'] for p in c.client.requests]
            self.assertEqual(len(packets), 2)
            self.assertTrue(all(packet == packets[0] for packet in packets))
            self.assertEqual({d['document_id'] for packet in packets for d in packet}, {'d1', 'd2', 'd3'})


if __name__ == '__main__':
    unittest.main()
