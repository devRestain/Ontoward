"""DD Context and input-scope regressions; no real model or clinical claims."""
import unittest

import fixtures as f
from workflow.rules.assessment import graph_candidates
from workflow.rules.decision import prepare_decision
from workflow.state.models import Answer, TurnContext


class DDContextTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = f.knowledge()
        self.consultation = f.consultation(prepared=f.resources(self.knowledge))
        self.state = f.chief(f.state('DifferentialDiagnosis', initialized=True))

    def options(self):
        candidates = graph_candidates(self.state.case, self.knowledge)
        return self.consultation.tools._options(self.state, candidates)

    def test_only_current_unresolved_context_and_clarification_are_executable(self):
        options = self.options()
        specs = [spec for spec, _ in options.values() if spec['target_id'] == str(f.OW.Context)]
        self.assertEqual(len(specs), 1)
        tools, spec = self.consultation.tools, specs[0]
        self.assertTrue(tools._allowed_now(self.state, dict(spec, purpose='context')))
        self.assertTrue(tools._allowed_now(self.state, dict(spec, purpose='clarification')))
        self.assertFalse(tools._allowed_now(self.state, dict(spec, purpose='feature')))
        work = prepare_decision(self.state, self.knowledge, tools)
        self.assertTrue(any(q['target'] == 'Test history' for q in work.payload['questions']))
        self.assertTrue(all(row['ref'] in work.options for row in work.payload['questions']))
        self.state.case.facts.clear()
        self.assertEqual(self.options(), {})

    def test_unknown_resolved_and_unaffordable_contexts_stay_blocked(self):
        tools = self.consultation.tools
        spec = next(spec for spec, _ in self.options().values() if spec['target_id'] == str(f.OW.Context))
        question = tools._question(spec, 'q', 0, 0)
        self.state.interview.answers.append(Answer(question_id='q', source_ref='say', scope='DifferentialDiagnosis',
            purpose='context', key=question.semantic_key(), outcome='unknown'))
        self.assertFalse(tools._allowed_now(self.state, dict(spec)))
        self.state.interview.answers.clear()
        self.state.case.apply([f.fact('history', kind='context', target='Test history', time_context=spec['time_context'])])
        self.assertFalse(tools._allowed_now(self.state, dict(spec)))
        self.state.session.turns_remaining = 0
        self.assertEqual(self.options(), {})


class InputScopeTests(unittest.TestCase):
    def test_scripted_child_caregiver_family_and_planned_tests_remain_distinct(self):
        text = ('The child has the test complaint. The child is 6 years old. I am his 37-year-old mother. '
            'His father matured late. I worry about hormone deficiency. Bone age and IGF-1 are planned.')
        def context(payload):
            if payload['task'] == 'input_context':
                return dict(statements=[
                    f.statement('The child has the test complaint.', primary_concern=True, reported_by='mother'),
                    f.statement('His father matured late.', target_terms=[], subject='family', subject_member='father',
                        reported_by='mother', time_context='past', record_category='family_history', note_value='Father had late growth and maturation'),
                    f.statement('I worry about hormone deficiency.', target_terms=[], role='emotion', assertion='uncertain',
                        reported_by='mother', note_value='Caregiver worries about hormone deficiency'),
                    f.statement('Bone age and IGF-1 are planned.', target_terms=[], role='clinical', assertion='uncertain',
                        polarity_scope='qualified', reported_by='mother', record_category='other', note_value='Bone age and IGF-1 tests are planned; no results available')],
                    patient_context=[dict(key='age', value='6 years', quote='The child is 6 years old.', measurement=dict(kind='quantity', value=6., unit='year')),
                        dict(key='age', value='37 years', quote='37-year-old mother', subject='family', subject_member='mother', measurement=dict(kind='quantity', value=37., unit='year')),
                        dict(key='reporter', value='mother', quote='I am his 37-year-old mother.')])
            if payload['task'] == 'input_mapping':
                return [{} for _ in payload['statements']]
        client = f.FakeSDK(chat_handler=context)
        consultation = f.consultation(client)
        state = f.state()
        state.turn = TurnContext(kind='initial', response=dict(opening=text))
        consultation.ear.process_input(state, consultation.knowledge, client)
        facts = state.case.current_facts()
        ages = {(fact.subject, fact.subject_member): fact.measurement.value for fact in facts
                if fact.measurement and fact.id.endswith(':age')}
        self.assertEqual(ages[('patient', None)], 6.)
        self.assertEqual(ages[('family', 'mother')], 37.)
        family = next(fact for fact in facts if 'Father had late' in fact.value)
        self.assertEqual((family.subject, family.subject_member, family.time_context), ('family', 'father', 'past'))
        planned = next(fact for fact in facts if 'tests are planned' in fact.value)
        self.assertIsNone(planned.graph_binding)
        self.assertNotEqual(planned.acquisition, 'EXAM')
        self.assertFalse(any(fact.kind == 'finding' for fact in facts))
        self.assertFalse(any(fact.graph_binding and 'hormone' in fact.target.casefold() for fact in facts))


if __name__ == '__main__':
    unittest.main()
