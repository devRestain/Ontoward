"""Regressions for information preservation and the D50 execution contract."""
import unittest
from unittest.mock import Mock

import fixtures as f
from workflow.input_types import PatientContextFact
from workflow.state.evidence import EvidenceIndex
from workflow.state.models import ObservedNumber, Question


class InputPreservationTests(unittest.TestCase):
    def test_chief_review_and_invalid_sibling_share_one_repair(self):
        calls = []
        def respond(payload):
            calls.append(payload)
            if payload['phase'] == 'context':
                return {'statements': [f.statement('Complaint', primary_concern=True, assertion='unknown'),
                                       f.statement('Medicine', note_value='약')],
                        'patient_context': [{'key': 'age', 'value': '6 years', 'quote': '6 years'}]}
            return {'statements': [f.statement('Complaint', primary_concern=True, assertion='unknown'),
                f.statement('Medicine', target_terms=[], assertion_scope='domain',
                    record_category='medication', note_value='Taking medicine')]}
        s, c, _ = f.interpret([], text='6 years Complaint Medicine', responses=respond)
        self.assertEqual([p['phase'] for p in calls], ['context', 'context_repair'])
        self.assertEqual(calls[1]['statement_indices'], [0, 1])
        self.assertIsNone(s.case.chief(confirmed=True))
        self.assertTrue(any(v.value == 'Taking medicine' for v in s.case.facts.values()))
        self.assertTrue(any(v.context_key == 'age' for v in s.case.facts.values()))

    def test_mapping_repair_keeps_valid_rows_and_never_selects_first_candidate(self):
        calls = []
        def respond(payload):
            calls.append(payload)
            if payload['task'] == 'input_context':
                return {'statements': [f.statement('First', target_terms=['test'], note_value='First complaint'),
                    f.statement('Second', target_terms=['test'], assertion='absent',
                        polarity_scope='qualified', note_value='No complaint while resting')]}
            if payload['phase'] == 'mapping':
                return [{'Test complaint': '(+)'}, 'invalid row']
            self.assertEqual(payload['statement_indices'], [1])
            return [{}]
        s, c, _ = f.interpret([], text='First Second', responses=respond)
        self.assertEqual([p['phase'] for p in calls], ['context', 'mapping', 'mapping_repair'])
        self.assertEqual(len(f.graph_facts(s.case)), 1)
        note = next(iter(f.unbound(s.case).values()))
        self.assertEqual((note.value, note.status, note.polarity_scope),
                         ('No complaint while resting', 'absent', 'qualified'))
        self.assertFalse(any(row.status == 'absent' for row in EvidenceIndex.from_case(s.case, c.knowledge).entries))

    def test_korean_hint_with_candidates_preserves_english_note_with_four_call_ceiling(self):
        calls = []
        def respond(payload):
            calls.append(payload)
            if payload['task'] == 'input_context':
                row = f.statement('가상', target_terms=['가상'], assertion='absent')
                if payload['phase'] == 'context_repair':
                    row['note_value'] = 'No reported test complaint'
                return {'statements': [row]}
            return '{'
        s, c, _ = f.interpret([], text='가상', responses=respond)
        self.assertEqual([p['phase'] for p in calls], ['context', 'context_repair', 'mapping', 'mapping_repair'])
        self.assertFalse(f.graph_facts(s.case))
        self.assertEqual(next(iter(f.unbound(s.case).values())).value, 'No reported test complaint')

    def test_exhausted_mapping_repair_keeps_notes_and_final_assessment_resources(self):
        c, s = f.consultation(prepared=f.resources(education=True)), f.chief(f.state('DifferentialDiagnosis'))
        # Three gateway calls are available; the fourth must leave the four final calls protected.
        s.session.doctor_calls = s.session.call_limit - 7
        def respond(payload):
            if payload['task'] == 'input_context':
                row = f.statement('New', target_terms=['test'], note_value='Additional reported complaint')
                if payload['phase'] == 'context':
                    row['note_value'] = '한글'
                return {'statements': [row]}
            return '{'
        from workflow.state.models import TurnContext
        client = c.client
        client.chat_handler = respond
        s.turn = TurnContext(kind='initial', response={'opening': 'New'})
        c.ear.process_input(s, c.knowledge, client)
        self.assertEqual(len(client.requests), 3)
        self.assertEqual(c.budget.calls_left(s.session), 4)
        self.assertTrue(any(v.value == 'Additional reported complaint' for v in f.unbound(s.case).values()))
        c.close_collection(s)
        self.assertTrue(s.case.assessment.frozen)
        self.assertIsNone(s.session.termination)

    def test_statement_repair_preserves_demographics_and_siblings(self):
        calls = []
        def respond(payload):
            calls.append(payload)
            if payload['phase'] == 'context_repair':
                return {'statements': [f.statement('약', target_terms=[], record_category='medication',
                                                  note_value='Taking medication')]}
            return {'statements': [f.statement('복통'), f.statement('약', note_value='약')],
                    'patient_context': [{'key': 'age', 'value': '25 years', 'quote': '25세'},
                                        {'key': 'sex', 'value': 'male', 'quote': '남성'}]}
        s, c, _ = f.interpret([], text='25세 남성 복통 약', responses=respond)
        self.assertEqual({v.context_key for v in s.case.facts.values() if v.context_key}, {'age', 'sex'})
        self.assertTrue(any(v.target == 'Test complaint' for v in s.case.facts.values()))
        self.assertTrue(any(v.value == 'Taking medication' for v in s.case.facts.values()))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]['statement_indices'], [1])

    def test_typed_korean_age_is_normalized_without_another_call(self):
        def respond(payload):
            return {'statements': [], 'patient_context': [{'key': 'age', 'value': '62세', 'quote': '62세',
                'measurement': {'kind': 'quantity', 'value': 62, 'unit': 'year'}}]}
        s, c, client = f.interpret([], text='62세', responses=respond)
        age = next(v for v in s.case.facts.values() if v.context_key == 'age')
        self.assertEqual(age.value, '62 years')
        self.assertEqual(age.measurement.value, 62)
        self.assertEqual(len(client.requests), 1)

    def test_demographic_repair_preserves_statements_and_valid_demographic(self):
        def respond(payload):
            if payload['phase'] == 'context_repair':
                self.assertEqual(payload['statement_indices'], [])
                self.assertEqual(payload['patient_context_indices'], [0])
                return {'statements': [], 'patient_context': [{'key': 'age', 'value': '62 years', 'quote': '62세'}]}
            return {'statements': [f.statement('복통')], 'patient_context': [
                {'key': 'age', 'value': '62세', 'quote': '62세'},
                {'key': 'sex', 'value': 'male', 'quote': '남성'}]}
        s, c, client = f.interpret([], text='62세 남성 복통', responses=respond)
        self.assertEqual({v.context_key for v in s.case.facts.values() if v.context_key}, {'age', 'sex'})
        self.assertTrue(any(v.target == 'Test complaint' for v in s.case.facts.values()))
        self.assertEqual(len(client.requests), 2)

    def test_unmapped_korean_hint_gets_bounded_note_repair(self):
        calls = []
        def respond(payload):
            calls.append(payload['phase'])
            row = f.statement('졸피뎀', target_terms=['졸피뎀'], record_category='medication')
            if payload['phase'] == 'context_repair':
                row['note_value'] = 'Taking zolpidem'
            return {'statements': [row]}
        s, c, _ = f.interpret([], text='졸피뎀', responses=respond)
        self.assertEqual(calls, ['context', 'context_repair'])
        self.assertEqual(next(iter(s.case.facts.values())).value, 'Taking zolpidem')

    def test_age_bounds_units_and_approximation_survive_normalization(self):
        measured = ObservedNumber(kind='interval', lower=6, upper=2, unit='month', upper_unit='year',
                                  lower_inclusive=False, upper_inclusive=True, approximate=True)
        age = PatientContextFact(key='age', value='나이', quote='나이', measurement=measured)
        self.assertEqual(age.measurement, measured)
        self.assertEqual(age.value, 'Approximately > 6 months and <= 2 years')

    def test_attribute_eligibility_follows_current_presence_and_scope(self):
        c = f.consultation()
        attribute = f.fact('quality', kind='attribute', attribute='Quality', values=('dull',), category='quality')
        for order in ((attribute, f.fact()), (f.fact(), attribute)):
            s = f.state()
            for fact in order:
                s.case.apply([fact])
            self.assertIn('quality', {r.id for r in EvidenceIndex.from_case(s.case, c.knowledge).entries})
            for status in ('absent', 'uncertain', 'unknown'):
                s.case.apply([f.fact(status=status)])
                self.assertNotIn('quality', {r.id for r in EvidenceIndex.from_case(s.case, c.knowledge).entries})
        for changes in ({'subject': 'family', 'subject_member': 'mother'}, {'episode_id': 'another'},
                        {'time_context': 'past'}, {'acquisition': 'EXAM'}, {'polarity_scope': 'qualified'}):
            s = f.state()
            s.case.apply([attribute, f.fact(**changes)])
            self.assertNotIn('quality', {r.id for r in EvidenceIndex.from_case(s.case, c.knowledge).entries})


class DeterministicReplyTests(unittest.TestCase):
    def test_unknown_and_acknowledgement_skip_ear_but_complete_and_record(self):
        for text, outcome in (('모르겠어요.', 'unknown'), ('감사합니다!', 'nonclinical')):
            q = Question(item_id='q', purpose='feature', text='어떤 느낌인가요?',
                         target='Test complaint', attribute='Quality')
            s, c, client = f.interpret([], q=q, text=text, s=f.chief(f.state('DifferentialDiagnosis')))
            self.assertFalse(client.requests)
            self.assertEqual(s.interview.answers[-1].outcome, outcome)
            self.assertEqual(c.ear.dialogue[-1]['patient'], text)
            self.assertIsNone(s.turn)
            c.differential.decide(s, client)
            self.assertEqual([p['task'] for p in client.requests], ['clinical_decision'])

    def test_canonical_presence_reply_uses_exact_question_scope(self):
        for text, status in (('네.', 'present'), ('아니요.', 'absent')):
            q = Question(item_id='q', purpose='feature', text='별도증상이 있나요?',
                target='Other symptom', affirmative_presence=True, answer_type='presence',
                observation_id='named-observation', episode_id='named-episode', time_context='past')
            s, c, client = f.interpret([], q=q, text=text)
            self.assertFalse(client.requests)
            value = next(iter(s.case.facts.values()))
            self.assertEqual((value.target, value.status, value.observation_id, value.episode_id, value.time_context),
                ('Other symptom', status, 'named-observation', 'named-episode', 'past'))

    def test_added_clinical_content_and_noncanonical_questions_are_interpreted(self):
        for text, purpose, wording in (('모르겠어요. 그런데 열이 나요', 'feature', '별도증상이 있나요?'),
                                      ('네', 'intake', '언제부터 불편하셨나요?'),
                                      ('아니요', 'feature', '별도증상이 없으신가요?'),
                                      ('네', 'history', '현재 복용하는 약이 있나요?')):
            q = Question(item_id='q', purpose=purpose, text=wording, target='Other symptom',
                         affirmative_presence=True, answer_type='presence')
            s, c, client = f.interpret([f.statement(text, role='unknown')], q=q, text=text)
            self.assertTrue(client.requests)

    def test_active_attribute_candidates_are_supplied_without_dropping_new_information(self):
        q = Question(item_id='q', purpose='feature', text='어떤 느낌인가요?', target='Test complaint',
                     attribute='Quality', observation_id='obs1', episode_id='episode1')
        rows = [f.statement('dull', focus='attribute', attribute_terms=['Quality'], value_terms=['dull']),
                f.statement('Other', target_terms=['Other symptom'])]
        s, c, client = f.interpret(rows, q=q, text='dull Other', s=f.chief(f.state()))
        binding = client.requests[0]['question']
        self.assertEqual(binding['allowed_values'], ['dull'])
        self.assertEqual(binding['allowed_units'], [])
        self.assertTrue(any(v.target == 'Other symptom' for v in s.case.facts.values()))


class SharedWorkTests(unittest.TestCase):
    def test_clarification_assets_reject_bad_text_before_actions(self):
        import unicodedata
        from knowledge.conditions import AttributeRole
        for text in ('', '   ', 'English only', '가' * 31,
                     unicodedata.normalize('NFD', '다시 말씀해 주세요')):
            with self.subTest(text=text):
                k = f.knowledge()
                k.attribute_roles[str(f.OW.Quality)] = AttributeRole(order=1, category='quality', clarification=text)
                with self.assertRaisesRegex(ValueError, 'Prepared clarification'):
                    k.validate_question_assets()
        k = f.knowledge()
        default = f.CONFIG.texts.clarification_question
        self.assertEqual(k.clarification(str(f.OW.Quality), default), default)
        k.attribute_roles[str(f.OW.Quality)] = AttributeRole(order=1, category='quality', clarification='양상을 다시 알려주세요')
        k.validate_question_assets()
        self.assertEqual(k.clarification(str(f.OW.Quality), default), '양상을 다시 알려주세요')

    def test_context_rules_reuse_does_not_reuse_unknown_or_unaffordable_questions(self):
        c, s = f.consultation(), f.chief(f.state('ChiefComplaint'))
        c.sessions['ChiefComplaint'].close(s, c.client)
        s.interview.current = 'ContextFactor'
        context = c.sessions['ContextFactor']
        context.enter(s, s.case.assessment)
        rules = context.rules
        specs = context.context_specs(s)
        self.assertTrue(specs)
        revision = s.case.revision
        context.context_specs = Mock(wraps=context.context_specs)
        c.prepare_session(s)
        self.assertEqual(context.context_specs.call_count, 1)
        c.questions.discard_unasked(s, {q.item_id for q in s.interview.queue})
        c.tools._register(s, next(iter(specs.values())), 0, 1)
        question = s.interview.queue[-1]
        c.questions.complete(s, question, 'unknown-context', outcome='unknown')
        self.assertEqual(s.case.revision, revision)
        self.assertFalse(context.context_specs(s))
        s.interview.answers[-1] = s.interview.answers[-1].model_copy(update={'outcome': 'conflict'})
        self.assertTrue(context.context_specs(s))
        s.session.turns_remaining = 0
        self.assertFalse(context.context_specs(s))
        self.assertIs(context.rules, rules)

    def test_fresh_facts_choose_preferred_chief_and_update_conflicts(self):
        s = f.chief(f.state())
        s.case.current_facts()
        second = f.fact('second', target='Other symptom', observation_id='second', episode_id='second')
        s.case.apply([second], preferred='second')
        self.assertEqual(s.case.chief().id, 'second')
        s.case.apply([f.fact('negative', status='absent')])
        self.assertEqual({f.status for f in s.case.current_facts() if f.target == 'Test complaint'}, {'uncertain'})
        s.case.apply([f.fact('negative', status='present')])
        self.assertEqual({f.status for f in s.case.current_facts() if f.target == 'Test complaint'}, {'present'})

    def test_relation_definitions_are_shared_and_all_question_references_resolve(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        work = c.differential.prepare_decision(s)
        payload = work.payload
        self.assertTrue(payload['relations'])
        for candidate in payload['candidates']:
            for category in ('supports', 'against', 'unresolved'):
                for ref in candidate.get(category, []):
                    row = payload['evidence'][ref]
                    self.assertNotIn('full_pattern', row)
                    self.assertIn(row['relation'], payload['relations'])
        for question in payload['questions']:
            for rows in question['expected_by_disease'].values():
                for row in rows:
                    self.assertNotIn('full_pattern', row)
                    relation = payload['relations'][row['relation']]
                    self.assertTrue(relation['full_pattern'])
                    if row['feature'] is not None:
                        self.assertLess(row['feature'], len(relation['full_pattern']))
        from workflow.model_context import messages
        import json
        self.assertEqual(json.loads(messages('instruction', payload)[1]['content']), payload)

    def test_question_specs_are_built_once_per_scoped_question(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        from workflow.rules.assessment import graph_candidates
        candidates = graph_candidates(s.case, c.knowledge, s.interview)
        expected = {ref.scope for candidate in candidates.values() for ref in candidate.entry.unresolved if ref.scope}
        c.tools._spec = Mock(wraps=c.tools._spec)
        c.tools._options(s, candidates)
        self.assertEqual(c.tools._spec.call_count, len(expected))

    def test_budget_uses_confirmed_state_without_get_and_keeps_reserve_floor(self):
        c = f.consultation(prepared=f.resources(education=True))
        s = c.nova_session.initialize_case(c.client)
        c.client.session = Mock(wraps=c.client.session)
        for _ in range(3):
            c.check_budget(s)
        c.client.session.assert_not_called()
        self.assertFalse(hasattr(c.budget, 'knowledge'))
        self.assertEqual(c.budget.collection_calls(s), 6)
        self.assertEqual(c.budget.collection_tokens(s), 36288)


class ClinicalCadenceTests(unittest.TestCase):
    def context_unknown(self):
        from workflow.state.models import Answer
        c, s = f.consultation(), f.chief(f.state('ChiefComplaint'))
        c.sessions['ChiefComplaint'].close(s, c.client)
        s.interview.current = 'ContextFactor'
        s.interview.answers.append(Answer(question_id='context', source_ref='last-context-unknown',
            scope='ContextFactor', purpose='context', outcome='unknown'))
        return c, s

    def test_unknown_context_gets_one_joint_dd_entry_without_revision_change(self):
        c, s = self.context_unknown()
        revision = s.case.revision
        before = len(c.client.requests)
        c.sessions['ContextFactor'].close(s, c.client)
        self.assertEqual(len(c.client.requests), before)
        s.interview.current = 'DifferentialDiagnosis'
        c.differential.decide(s, c.client)
        self.assertEqual(s.case.revision, revision)
        self.assertEqual(c.client.requests[-1]['task'], 'clinical_decision')
        self.assertEqual(s.case.assessment.based_on_response, 'last-context-unknown')
        c.differential.decide(s, c.client)
        self.assertEqual(len(c.client.requests), before + 1)

    def test_resource_exit_before_dd_handles_context_unknown_then_reuses_freeze(self):
        for stage in ('ContextFactor', 'DifferentialDiagnosis'):
            c, s = self.context_unknown()
            s.interview.current = stage
            s.session.turns_remaining = c.client.remaining = 0
            before = len(c.client.requests)
            c.check_budget(s)
            self.assertEqual(len(c.client.requests), before + 1)
            self.assertEqual(c.client.requests[-1]['task'], 'clinical_rank')
            self.assertTrue(s.case.assessment.frozen)
            self.assertEqual(s.case.assessment.based_on_response, 'last-context-unknown')
            c.close_collection(s)
            c.finalize(s)
            self.assertEqual(len(c.client.requests), before + 1)


class JointEducationTests(unittest.TestCase):
    def test_normal_joint_plan_needs_no_translation_call(self):
        c, s, _ = f.run(prepared=f.resources(education=True))
        self.assertEqual(s.session.termination, 'submitted')
        self.assertEqual(sum(p['task'] == 'education' for p in c.client.requests), 1)
        self.assertFalse(any(p['task'] == 'education_doctor' for p in c.client.requests))
        self.assertEqual(len(s.case.plan), 5)

    def test_bad_korean_repairs_only_its_group_without_losing_english_or_citations(self):
        from education_fixtures import education_response
        import copy
        requests = []
        def response(payload):
            requests.append(copy.deepcopy(payload))
            if payload['task'] == 'education':
                raw = education_response(payload)
                raw['P']['treatment'][0]['utterances'] = ['가' * 31]
                return raw
        c = f.consultation(f.FakeSDK(chat_handler=response), f.resources(education=True))
        s = f.chief(f.state())
        f.freeze_for_education(c, s)
        owner = c.sessions['Education']
        owner.prepare_plan(s, c.client)
        accepted = copy.deepcopy(s.case.plan)
        owner.prepare_delivery(s, c.client)
        repair = [p for p in requests if p['task'] == 'education_doctor']
        self.assertEqual(len(repair), 1)
        self.assertEqual([row['id'] for row in repair[0]['sentences']], ['plan:treatment:0'])
        self.assertEqual(s.case.plan, accepted)
        self.assertEqual(len(s.interview.queue), 5)
        count = len(requests)
        owner.prepare_delivery(s, c.client)
        self.assertEqual(len(requests), count)


if __name__ == '__main__':
    unittest.main()
