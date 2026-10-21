"""Preserve clinical inputs while sharing definitions and stopping rejected requests."""
import json
import unittest
from unittest.mock import Mock

import fixtures as f
from workflow.rules.assessment import graph_candidates


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
    def test_context_rejection_stops_each_clinical_route_before_repair_or_action(self):
        for stage, closing in [('Initiation', False), ('ChiefComplaint', False),
                               ('DifferentialDiagnosis', False), ('DifferentialDiagnosis', True)]:
            with self.subTest(stage=stage, closing=closing):
                c, s = f.consultation(), f.chief(f.state(stage))
                c.client.chat = Mock(side_effect=f.NovaError('CONTEXT_LIMIT_EXCEEDED', 400))
                if stage == 'DifferentialDiagnosis':
                    c.differential.decide(s, c.client, closing=closing)
                else:
                    c.sessions[stage].close(s, c.client)
                self.assertEqual((s.session.termination, s.session.reason), ('failed', 'CONTEXT_LIMIT_EXCEEDED'))
                c.client.chat.assert_called_once()
                self.assertEqual(c.client.chat.call_args.kwargs['max_tokens'], 4096)
                self.assertFalse(c.client.actions)
                self.assertIsNone(s.case.assessment)


if __name__ == '__main__':
    unittest.main()
