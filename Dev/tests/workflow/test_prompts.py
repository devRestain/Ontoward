import copy
import unittest

import fixtures as f
from education_fixtures import education_response
from workflow.state.models import Question, TurnContext


class PromptSDK(f.FakeSDK):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.exchanges = []

    def chat(self, messages, **kwargs):
        self.exchanges.append((f.decode_context(messages[-1]['content']), messages[0]['content']))
        return super().chat(messages, **kwargs)


def accept_input(client, text, question=None):
    c, state = f.consultation(client), f.state()
    if question:
        c.questions.register(state, question)
        c.interactions.select_question(state, question)
        state.turn.stage = 'received'
        state.turn.response = {'content': text, 'result': text, 'turn': 1}
    else:
        state.turn = TurnContext(kind='initial', response={'opening': text})
    c.ear.process_input(state, c.knowledge, client)
    return c, state


class PromptTests(unittest.TestCase):
    def test_selected_tasks_complete_with_one_output_contract_per_request(self):
        client = PromptSDK()
        c, state, _ = f.run(client, f.resources(education=True))
        self.assertEqual(state.session.termination, 'submitted')
        self.assertTrue(state.case.assessment.frozen)
        self.assertEqual(len(state.case.plan), 5)
        self.assertEqual(sum(len(fields) for fields in client.submissions[0]['note'].values()), 15)
        seen = set()
        for payload, prompt in client.exchanges:
            task = payload['task']
            seen.add(task)
            if task == 'input_context':
                self.assertNotIn('Repair only the rows', prompt)
                if payload['question'] is None:
                    self.assertIn('Interpret the server-provided initial input', prompt)
                    self.assertNotIn('Resolve short answers', prompt)
                elif payload['question']['kind'] == 'EXAM':
                    self.assertIn('Interpret the returned physical examination result', prompt)
                    self.assertNotIn('Emit empathy only', prompt)
                else:
                    self.assertIn('Resolve short answers', prompt)
                    self.assertNotIn('Assign every statement an input_segment', prompt)
            elif task == 'clinical_rank':
                self.assertIn('Perform ranking only', prompt)
                self.assertNotIn('Select one executable supplied question', prompt)
            elif task == 'clinical_action':
                self.assertIn('without reranking it', prompt)
                self.assertNotIn('Rank the supplied registered disease candidates', prompt)
            elif task == 'clinical_decision':
                self.assertIn('Rank the supplied registered disease candidates', prompt)
                self.assertIn('Select one executable supplied question', prompt)
            elif task == 'education':
                self.assertIn('Generate the complete plan', prompt)
                self.assertNotIn('Repair the management plan', prompt)
            elif task == 'education_doctor':
                self.assertIn('Translate and simplify each requested English plan sentence', prompt)
                self.assertNotIn('fixed working-diagnosis notice', prompt)
                self.assertNotIn('Regenerate only the requested invalid IDs', prompt)
        self.assertTrue({'input_context', 'clinical_rank', 'clinical_action', 'clinical_decision',
                         'education', 'education_doctor'} <= seen)

    def test_input_row_repair_keeps_valid_sibling_and_activates_only_repair_module(self):
        def reply(payload):
            if payload['phase'] == 'context':
                return {'statements': [f.statement('Complaint', primary_concern=True),
                                       f.statement('Other', observation_id='foreign')]}
            return {'statements': [f.statement('Other', target_terms=['Other symptom'])]}
        client = PromptSDK(chat_handler=reply)
        _, state = accept_input(client, 'Complaint Other')
        self.assertEqual(len(state.case.facts), 2)
        first, repair = client.exchanges
        self.assertNotIn('Repair only the rows', first[1])
        self.assertIn('Repair only the rows named in statement_indices', repair[1])
        self.assertEqual(repair[0]['statement_indices'], [1])
        self.assertNotIn('Review the indicated initial presenting-complaint statements', repair[1])
        self.assertEqual(state.case.chief().target, 'Test complaint')

    def test_initial_chief_review_keeps_unknown_existence_without_other_repairs(self):
        def reply(payload):
            return {'statements': [f.statement('Complaint', assertion='unknown', primary_concern=True)]}
        client = PromptSDK(chat_handler=reply)
        _, state = accept_input(client, 'Complaint')
        self.assertEqual([p['phase'] for p, _ in client.exchanges], ['context', 'initial_chief_repair'])
        self.assertNotIn('Review the indicated initial presenting-complaint statements', client.exchanges[0][1])
        self.assertIn('Retain genuinely unknown existence', client.exchanges[1][1])
        self.assertIsNone(state.case.chief(confirmed=True))

    def test_exam_input_keeps_objective_acquisition_without_reply_or_empathy_instructions(self):
        def reply(payload):
            return {'statements': [f.statement('Observed', target_terms=['Test examination finding'],
                                              record_category='objective_observation')]}
        client = PromptSDK(chat_handler=reply)
        q = Question(item_id='exam', purpose='feature', kind='EXAM', text='진찰할게요.',
                     target='Test examination finding')
        _, state = accept_input(client, 'Observed', q)
        prompt = client.exchanges[0][1]
        self.assertIn('Assign actual observed patient findings to objective_observation', prompt)
        self.assertNotIn('Interpret the current patient or caregiver reply', prompt)
        self.assertNotIn('Emit empathy only', prompt)
        self.assertEqual(next(iter(state.case.facts.values())).acquisition, 'EXAM')

    def test_mapping_repair_retains_selected_policy_and_forced_stage_is_separate(self):
        def reply(payload):
            if payload['task'] == 'input_context':
                return {'statements': [f.statement('Complaint', target_terms=['unresolved concern'])]}
            return 'broken JSON' if payload['phase'] == 'mapping' else [{}]
        client = PromptSDK(chat_handler=reply)
        _, state = accept_input(client, 'Complaint')
        calls = [(p, text) for p, text in client.exchanges if p['task'] == 'input_mapping']
        self.assertEqual([p['phase'] for p, _ in calls], ['mapping', 'format_repair', 'forced'])
        self.assertNotIn('Repair only syntax', calls[0][1])
        self.assertIn('Repair only syntax', calls[1][1])
        self.assertNotIn('Choose the closest type-compatible', calls[1][1])
        self.assertIn('Choose the closest type-compatible', calls[2][1])
        self.assertNotIn('Return {} for an unresolved statement', calls[2][1])
        self.assertEqual(next(iter(state.case.facts.values())).binding, 'forced')

    def test_action_repair_keeps_accepted_ranking_and_omits_ranking_instructions(self):
        def reply(payload):
            if payload['task'] == 'clinical_decision':
                result = f.clinical_response(payload)
                result['ranked_disease_refs'].reverse()
                result['next_action'] = {'kind': 'ask', 'question_ref': 'missing'}
                return result
        client = PromptSDK(chat_handler=reply)
        c, state = f.consultation(client), f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(state, client)
        self.assertEqual([p['task'] for p, _ in client.exchanges], ['clinical_decision', 'clinical_action'])
        repair = client.exchanges[1][1]
        self.assertIn('Correct the listed validation_error', repair)
        self.assertNotIn('Rank the supplied registered disease candidates', repair)
        self.assertEqual(state.case.assessment.differential[0].name, 'Disease beta')
        self.assertIsNone(c.differential.error)

    def test_plan_repair_preserves_accepted_sentences_without_full_plan_obligation(self):
        def reply(payload):
            if payload['task'] == 'education':
                result = education_response(payload)
                if payload['phase'] == 'direct':
                    result['P']['tests'] = []
                else:
                    result['P'] = {'tests': result['P']['tests']}
                return result
        client = PromptSDK(chat_handler=reply)
        c, state = f.consultation(client, f.resources(education=True)), f.chief(f.state())
        f.freeze_for_education(c, state)
        c.sessions['Education'].prepare_plan(state, client)
        calls = [(p, text) for p, text in client.exchanges if p['task'] == 'education']
        self.assertEqual(len(calls), 2)
        self.assertIn('Generate the complete plan', calls[0][1])
        self.assertNotIn('Generate the complete plan', calls[1][1])
        self.assertIn('return only missing or invalid items', calls[1][1])
        self.assertEqual(len(calls[1][0]['accepted']), 4)
        self.assertEqual(len(state.case.plan), 5)

    def test_mouth_keeps_response_and_text_repair_budgets_and_frozen_assessment(self):
        client = PromptSDK()
        original, number = client.chat, 0
        def chat(messages, **kwargs):
            nonlocal number
            payload = f.decode_context(messages[-1]['content'])
            if payload['task'] == 'education_doctor':
                number += 1
                if number == 1:
                    client.exchanges.append((payload, messages[0]['content']))
                    raise f.NovaError('PROVIDER_RESPONSE_INVALID', 503)
                if number == 2:
                    client.exchanges.append((payload, messages[0]['content']))
                    return client.completion({'items': [{'id': r['id'], 'utterances': ['x' * 31]}
                                                         for r in payload['sentences']]})
            return original(messages, **kwargs)
        client.chat = chat
        c, state = f.consultation(client, f.resources(education=True)), f.chief(f.state())
        f.freeze_for_education(c, state)
        frozen = copy.deepcopy(state.case.assessment)
        c.sessions['Education'].prepare_plan(state, client)
        c.sessions['Education'].prepare_delivery(state, client)
        calls = [(p, text) for p, text in client.exchanges if p['task'] == 'education_doctor']
        self.assertEqual(len(calls), 3)
        self.assertNotIn('Recover the unavailable or truncated generation', calls[0][1])
        self.assertIn('Recover the unavailable or truncated generation', calls[1][1])
        self.assertNotIn('Regenerate only the requested invalid IDs', calls[1][1])
        self.assertIn('Regenerate only the requested invalid IDs', calls[2][1])
        self.assertNotIn('Recover the unavailable or truncated generation', calls[2][1])
        self.assertTrue(state.interview.queue)
        self.assertEqual(state.case.assessment, frozen)

    def test_diagnosis_notice_selects_disease_or_symptom_without_plan_instructions(self):
        for kind in ('disease', 'symptom'):
            with self.subTest(kind=kind):
                client = PromptSDK()
                c, state = f.consultation(client), f.chief(f.state())
                f.freeze_for_education(c, state)
                primary = state.case.assessment.differential[0].model_copy(update={
                    'kind': kind, 'name': 'Disease beta' if kind == 'disease' else 'Test complaint'})
                state.case.assessment = state.case.assessment.model_copy(update={'differential': (primary,)})
                c.knowledge.label = lambda ident: 'Long English diagnosis name'
                self.assertTrue(c.sessions['Education'].prepare_diagnosis(state, client))
                payload, prompt = next((p, text) for p, text in client.exchanges if p['task'] == 'education_doctor')
                self.assertEqual(payload['fixed_diagnosis']['kind'], kind)
                self.assertNotIn('Translate and simplify each requested English plan sentence', prompt)
                if kind == 'disease':
                    self.assertIn('State suspicion without claiming confirmation', prompt)
                    self.assertNotIn('Preserve the undetermined cause', prompt)
                else:
                    self.assertIn('Preserve the undetermined cause', prompt)
                    self.assertNotIn('State suspicion without claiming confirmation', prompt)
