"""Verify bounded offline corrections and strict activation with no providers."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rdflib import Graph, Literal, RDF, URIRef
from knowledge.graph import ClinicalKnowledge, OW
from ontoward_extraction.compile import compile_bundle
from ontoward_extraction.install import install
from ontoward_extraction.maintenance import correct_bundle, read_parent
from ontoward_extraction.models import canonical
from support import nodes


def ident(name):
    return 'urn:fixture:' + name


def registered_nodes():
    result = nodes()
    for row in result:
        row['id'] = ident(row['id'])
        for field in ('attributes', 'values', 'systems'):
            row[field] = [ident(value) for value in row[field]]
        if row['exam_method']:
            row['exam_method'] = ident(row['exam_method'])
    return result


def clinical(target='symptom', effect='support', **changes):
    row = dict(disease_id=ident('disease'), target_id=ident(target),
        target_scope=dict(subject='patient', subject_member=None, time_context='current'),
        applicability=[], features=[dict(status='present')], effect=effect)
    row.update(changes)
    return row


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def bundle(self, *, extra=(), relations=None, value_paths=(), overrides=None, name='parent'):
        rows = registered_nodes() + list(extra)
        compile_bundle(self.root / name, name, rows, relations if relations is not None else [clinical()],
            value_paths=value_paths, preserve_ids=True, question_overrides=overrides)
        return self.root / name / 'manifest.json'

    def edit(self, manifest, triples):
        metadata = json.loads(manifest.read_text())
        path = manifest.parent / metadata['vocabulary']['path']
        graph = Graph().parse(path, format='turtle')
        for triple in triples:
            graph.add(tuple(URIRef(value) for value in triple))
        path.write_text('\n'.join(sorted(graph.serialize(format='nt').splitlines())) + '\n')
        metadata['vocabulary']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.write_text(canonical(metadata))

    def plan(self, manifest, *, edges=(), merges=()):
        metadata = json.loads(manifest.read_text())
        value = dict(version='v5-maintenance-1', parent=dict(build_id=metadata['build_id'],
            manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            assets={role: metadata[role]['sha256'] for role in ('schema', 'vocabulary', 'clinical', 'questions', 'guidelines')}),
            remove_edges=[dict(zip(('subject', 'predicate', 'object'), map(str, edge))) for edge in edges],
            merges=list(merges), deferred=[])
        path = self.root / 'plan.json'
        path.write_text(canonical(value))
        return path

    def merge(self, canonical_name='symptom', other='other'):
        return dict(canonical=ident(canonical_name), members=[ident(canonical_name), ident(other)],
            same_role_meaning_verified=True, evidence=['Explicit synthetic same-role equivalence fixture'])

    def other(self, **changes):
        raw = registered_nodes()[1]
        return dict(raw, id=ident('other'), name='Equivalent complaint', korean='동등증상', **changes)

    def correct(self, manifest, plan):
        summary = correct_bundle(manifest, plan, self.root / 'output')
        report = json.loads(Path(summary['receipt']).read_text())
        return summary, report, ClinicalKnowledge.load(Path(summary['manifest']))

    def test_kind_specific_fresh_emission_and_strict_invalid_range_rejection(self):
        rows = nodes()
        rows[0]['attributes'] = ['symptom']
        rows[1]['values'] = ['sharp']
        compile_bundle(self.root / 'fresh', 'fresh', rows, [dict(disease_id='disease', target_id='symptom',
            target_scope=dict(subject='patient', subject_member=None, time_context='current'), features=[dict(status='present')], effect='support')])
        knowledge = ClinicalKnowledge.load(self.root / 'fresh/manifest.json')
        disease = next(iter(knowledge._disease_profiles))
        self.assertFalse(list(knowledge._graph.objects(URIRef(disease), OW.hasAttribute)))
        symptom = next(iter(knowledge._target_profiles))
        self.assertFalse(list(knowledge._graph.objects(URIRef(symptom), OW.canHaveValue)))
        rows[1]['attributes'] = ['symptom']
        with self.assertRaisesRegex(ValueError, 'invalid_vocabulary_endpoints'):
            compile_bundle(self.root / 'bad', 'bad', rows, [])

    def test_strict_loader_rejects_all_three_global_endpoint_faults(self):
        edges = [(ident('symptom'), str(OW.hasAttribute), ident('finding')),
                 (ident('symptom'), str(OW.canHaveValue), ident('sharp')),
                 (ident('quality'), str(OW.canHaveValue), ident('symptom'))]
        for index, edge in enumerate(edges):
            with self.subTest(edge=edge):
                manifest = self.bundle(name='bad' + str(index))
                self.edit(manifest, [edge])
                with self.assertRaisesRegex(ValueError, 'invalid_vocabulary_endpoints'):
                    ClinicalKnowledge.load(manifest)

    def test_exact_invalid_edge_plan_and_parent_hashes_are_enforced(self):
        manifest = self.bundle()
        edge = (ident('symptom'), str(OW.canHaveValue), ident('sharp'))
        self.edit(manifest, [edge])
        plan = self.plan(manifest)
        with self.assertRaisesRegex(ValueError, 'enumerate_exactly_invalid'):
            self.correct(manifest, plan)
        valid = (ident('symptom'), str(OW.hasAttribute), ident('quality'))
        plan = self.plan(manifest, edges=[edge, valid])
        with self.assertRaisesRegex(ValueError, 'enumerate_exactly_invalid'):
            self.correct(manifest, plan)
        plan = self.plan(manifest, edges=[edge])
        manifest.write_text(manifest.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'parent_manifest_digest_mismatch'):
            self.correct(manifest, plan)

    def test_type_repair_completes_when_equivalence_is_not_verified(self):
        manifest = self.bundle(extra=[self.other()], relations=[clinical(), clinical('other')])
        edge = (ident('symptom'), str(OW.canHaveValue), ident('sharp'))
        self.edit(manifest, [edge])
        proposal = self.merge()
        proposal['same_role_meaning_verified'] = False
        summary, report, knowledge = self.correct(manifest, self.plan(manifest, edges=[edge], merges=[proposal]))
        self.assertEqual(summary['removed_invalid_edges'], 1)
        self.assertEqual(summary['merged_nodes'], 0)
        self.assertEqual(report['deferred'][0]['reason'], 'require_explicit_same_role_semantic_review')
        knowledge.validate_vocabulary_endpoints()
        self.assertTrue(knowledge.has_type(ident('other'), 'Symptom'))

    def test_effect_conflict_defers_whole_merge_without_changing_either_effect(self):
        manifest = self.bundle(extra=[self.other()], relations=[clinical(), clinical('other', 'against')])
        _, report, knowledge = self.correct(manifest, self.plan(manifest, merges=[self.merge()]))
        self.assertFalse(report['canonical_mapping'])
        self.assertEqual(report['deferred'][0]['reason'], 'conflicting_effects_after_canonical_projection')
        self.assertEqual({profile.effect for profile in knowledge.get_disease_patterns(ident('disease'))}, {'support', 'against'})

    def test_same_effect_exact_duplicates_merge_and_preserve_question_meaning(self):
        other = self.other()
        other['question']['text'] = '같은 증상이 있나요?'
        manifest = self.bundle(extra=[other], relations=[clinical(), clinical('other')])
        parent = {path.name: path.read_bytes() for path in manifest.parent.iterdir()}
        _, report, knowledge = self.correct(manifest, self.plan(manifest, merges=[self.merge()]))
        self.assertEqual(report['exact_duplicate_relations_removed'], 1)
        self.assertEqual(len(knowledge.get_disease_patterns(ident('disease'))), 1)
        self.assertEqual(knowledge.resolve_concept('Equivalent complaint'), [ident('symptom')])
        self.assertFalse(knowledge.has_type(ident('other'), 'Symptom'))
        self.assertEqual(knowledge.questions[ident('symptom')].text, '가상증상이 있나요?')
        self.assertEqual({path.name: path.read_bytes() for path in manifest.parent.iterdir()}, parent)

    def test_question_time_and_role_conflicts_never_merge(self):
        for conflict in ('time', 'role'):
            with self.subTest(conflict=conflict):
                other = self.other()
                if conflict == 'time':
                    other['question']['time_context'] = 'past'
                else:
                    other.update(kind='ExamFinding', exam_method=ident('method'))
                manifest = self.bundle(extra=[other], relations=[clinical()], name=conflict)
                summary, report, _ = self.correct(manifest, self.plan(manifest, merges=[self.merge()]))
                self.assertEqual(summary['merged_nodes'], 0)
                self.assertTrue(report['deferred'])
                # Each immutable input is independent even though this test shares a scratch root.
                (self.root / 'plan.json').unlink()

    def test_registered_exam_methods_with_same_name_keep_distinct_actions(self):
        rows = registered_nodes()
        method = copy.deepcopy(rows[-1])
        method.update(id=ident('method2'), exam_text='가슴을 청진하겠습니다')
        finding = copy.deepcopy(rows[-2])
        finding.update(id=ident('finding2'), name='Synthetic chest sound', korean='가상흉부소견', exam_method=ident('method2'))
        manifest = self.bundle(extra=[method, finding])
        _, report, knowledge = self.correct(manifest, self.plan(manifest))
        self.assertTrue(knowledge.has_type(ident('method'), 'ExamMethod'))
        self.assertTrue(knowledge.has_type(ident('method2'), 'ExamMethod'))
        self.assertEqual(knowledge.get_exam_methods(ident('finding'))[0]['text'], '배를 눌러 확인하겠습니다')
        self.assertEqual(knowledge.get_exam_methods(ident('finding2'))[0]['text'], '가슴을 청진하겠습니다')
        self.assertFalse(report['graph_identity_changes'])

    def test_value_owners_paths_numeric_bounds_and_family_scope_survive(self):
        extra = [dict(id=ident('secondAttribute'), kind='FindingAttribute', name='Second dimension', korean='별도차원',
            values=[ident('secondSharp')], question=dict(text='다른 느낌은 어떤가요?', answer_type='category'),
            attribute_role=dict(order=1, category='quality')),
            dict(id=ident('secondSharp'), kind='AttributeValue', name='Sharp', korean='날카로움'),
            dict(id=ident('duration'), kind='FindingAttribute', name='Elapsed duration', korean='지속시간',
                question=dict(text='얼마나 지속되었나요?', answer_type='duration', units=['day']),
                attribute_role=dict(order=2, category='duration'))]
        other = self.other(attributes=[ident('secondAttribute'), ident('duration')])
        extra.append(other)
        rows = [clinical(),
            dict(disease_id=ident('disease'), target_id=ident('other'), effect='strong_support',
                target_scope=dict(subject='family', subject_member='mother', time_context='past'),
                applicability=[dict(concept_id=ident('context'), subject='family', subject_member='mother',
                    time_context='past', status='present')], features=[dict(status='present'), dict(attribute=ident('duration'),
                    expected=dict(kind='interval', lower=0., upper=2., lower_inclusive=False, upper_inclusive=True,
                        unit='day', approximate=True))])]
        path = dict(observed=ident('secondSharp'), expected=ident('sharp'), relation='regional_part')
        manifest = self.bundle(extra=extra, relations=rows, value_paths=[path])
        _, report, knowledge = self.correct(manifest, self.plan(manifest, merges=[self.merge()]))
        self.assertTrue(report['canonical_relation_semantics_equal'])
        self.assertEqual(knowledge.value_id('Second dimension', 'Sharp'), ident('secondSharp'))
        self.assertEqual(knowledge.value_id('Synthetic quality', 'Sharp'), ident('sharp'))
        profiles = knowledge.get_disease_patterns(ident('disease'))
        scoped = next(profile for profile in profiles if profile.effect == 'strong_support')
        self.assertEqual(scoped.target_scope.subject_member, 'mother')
        self.assertEqual(scoped.target_scope.time_context, 'past')
        self.assertEqual(scoped.applicability[0].concept_id, ident('context'))
        self.assertEqual(scoped.applicability[0].subject_member, 'mother')
        self.assertEqual(scoped.applicability[0].status, 'present')
        measured = next(f.expected for f in knowledge.get_pattern_features(scoped.id) if f.expected)
        self.assertEqual(measured.lower, 0.)
        self.assertIs(measured.lower_inclusive, False)
        self.assertIs(measured.approximate, True)
        self.assertTrue(knowledge.value_matches(ident('secondSharp'), ident('sharp'), hierarchy=True))

    def test_question_override_keys_follow_the_same_canonical_target(self):
        other = self.other()
        key = ident('other') + '|' + ident('quality')
        override = dict(other['question'], text='특정 양상은 어떤가요?', answer_type='category', affirmative=False)
        manifest = self.bundle(extra=[other], overrides={key: override})
        _, report, knowledge = self.correct(manifest, self.plan(manifest, merges=[self.merge()]))
        self.assertIn(ident('symptom') + '|' + ident('quality'), knowledge.questions)
        self.assertNotIn(key, knowledge.questions)

    def test_installer_preserves_requested_parent_and_rejects_invalid_child_before_commit(self):
        parent = self.bundle()
        install(parent, self.root / 'target')
        target = self.root / 'target'
        retained = target / 'builds/parent'
        before = {path.name: path.read_bytes() for path in retained.iterdir()}
        child = self.bundle(name='child')
        invalid = self.bundle(name='invalid')
        self.edit(invalid, [(ident('symptom'), str(OW.canHaveValue), ident('sharp'))])
        old = (target / 'manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'invalid_vocabulary_endpoints'):
            install(invalid, target, preserve_build_ids=['parent'])
        self.assertEqual((target / 'manifest.json').read_bytes(), old)
        install(child, target, preserve_build_ids=['parent'])
        self.assertEqual({path.name: path.read_bytes() for path in retained.iterdir()}, before)
        self.assertEqual(json.loads((target / 'manifest.json').read_text())['build_id'], 'child')

    def test_registered_output_is_immutable_and_unexplained_changes_are_rejected(self):
        manifest = self.bundle()
        plan = self.plan(manifest)
        summary, _, _ = self.correct(manifest, plan)
        with self.assertRaisesRegex(ValueError, 'maintenance_output_must_be_fresh'):
            correct_bundle(manifest, plan, self.root / 'output')
        self.edit(manifest, [(ident('disease'), str(OW.evaluatedBy), ident('sharp'))])
        plan = self.plan(manifest)
        with self.assertRaisesRegex(ValueError, 'unexplained_vocabulary_transition'):
            correct_bundle(manifest, plan, self.root / 'unsupported')


if __name__ == '__main__':
    unittest.main()
