"""Task A semantic regressions; all model responses are offline protocol fixtures."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Literal, RDF, RDFS, SKOS
import fixtures as f
from education_fixtures import education_response
from knowledge.conditions import ExpectedValue, QuestionTemplate
from knowledge.guidelines import GuidelineLibrary
from workflow.education import references
from workflow.input_types import ContextStatement
from workflow.rules.assessment import graph_candidates
from workflow.rules.normalization import candidate_contracts, concept_rank
from workflow.state.evidence import fixed_case_payload
from workflow.state.models import Assessment, DifferentialEntry, EvidenceRef, GraphRef, TurnContext


def check_references(test, payload):
    """Resolve the wire tables independently of the producer."""
    facts, scopes = payload['facts'], payload['scopes']
    diseases = {row['ref'] for row in payload['candidates']}
    if payload['chief'] is not None:
        test.assertIn(payload['chief'], facts)
    for fact in facts.values():
        test.assertIn(fact['scope'], scopes)
    for row in [*payload['evidence'].values(), *payload['questions']]:
        if 'scope' in row:
            test.assertIn(row['scope'], scopes)
        test.assertTrue(set(row.get('facts', [])) <= set(facts))
        if row.get('relation'):
            test.assertIn(row['relation'], payload['relations'])
            if row.get('feature') is not None:
                test.assertIn(row['feature'], range(len(payload['relations'][row['relation']]['full_pattern'])))
        for disease, entries in row.get('expected_by_disease', {}).items():
            test.assertIn(disease, diseases)
            for entry in entries:
                relation = payload['relations'][entry['relation']]
                if entry.get('feature') is not None:
                    test.assertIn(entry['feature'], range(len(relation['full_pattern'])))
                    test.assertNotIn('expected', entry)
                else:
                    test.assertIn('expected', entry)
    for row in payload['candidates']:
        for category in ('supports', 'against', 'unresolved'):
            test.assertTrue(set(row.get(category, [])) <= set(payload['evidence']))
    for relation in payload['relations'].values():
        if relation['applicability'] is not None:
            test.assertIn(relation['applicability'], payload['conditions'])


def decode_feature(knowledge, feature):
    """Restore a typed expectation, including defaults omitted on the wire."""
    value = feature['expected']
    if feature['attribute'] is None:
        return None
    attribute = knowledge.term_id(feature['attribute'], 'FindingAttribute')
    if isinstance(value, str):
        raw = dict(kind='concept', concept=knowledge.value_id(feature['attribute'], value))
    elif 'subsumption' in value:
        raw = dict(kind='concept', concept=knowledge.value_id(feature['attribute'], value['subsumption']), match='subsumption')
    elif 'any_of' in value or 'all_of' in value:
        selection = 'any_of' if 'any_of' in value else 'all_of'
        raw = dict(kind='concept_set', selection=selection, match=value['match'],
            concepts=[knowledge.value_id(feature['attribute'], name) for name in value[selection]])
    else:
        raw = value
    return attribute, ExpectedValue.model_validate(raw).signature()


class ScopedRecallTests(unittest.TestCase):
    def relation(self, *, effect='support', status='present', conditions=None, features=(), presence=True):
        knowledge = f.knowledge()
        f.add_pattern(knowledge, 'isolated', f.OW.Other, list(features), effect=effect,
            applicability=conditions, presence=presence)
        if presence:
            knowledge._graph.set((f.OW.isolatedPresence, f.OW.expectedStatus, Literal(status)))
            knowledge.validate_graph()
        return knowledge

    def prior(self, state):
        state.case.assessment = Assessment(differential=(DifferentialEntry(kind='disease', name='Disease beta'),),
            based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id)

    def test_contradicted_only_route_cannot_recall_or_protect_prior(self):
        k = self.relation()
        s = f.state()
        s.case.apply([f.fact('denied', target='Other symptom', status='absent')])
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))
        self.prior(s)
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))
        # A different valid path still retains the candidate.
        s.case.apply([f.fact('complaint')])
        self.assertIn(str(f.OW.Beta), graph_candidates(s.case, k))

    def test_absence_support_and_prior_opposition_remain_valid(self):
        for effect in ('support', 'strong_support', 'against', 'strong_against'):
            k = self.relation(effect=effect, status='absent')
            s = f.state()
            s.case.apply([f.fact('denied', target='Other symptom', status='absent')])
            if effect in {'against', 'strong_against'}:
                self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))
                self.prior(s)
            entry = graph_candidates(s.case, k)[str(f.OW.Beta)].entry
            refs = entry.supports if effect in {'support', 'strong_support'} else entry.against
            self.assertEqual([ref.fact_ids for ref in refs], [('denied',)])

    def test_context_only_unknown_target_is_allowed_but_known_contradiction_is_not(self):
        conditions = [dict(concept_id=str(f.OW.Context), subject='patient', status='present', time_context='any')]
        k = self.relation(conditions=conditions)
        s = f.state()
        s.case.apply([f.fact('history', kind='context', target='Test history', category='medical_history')])
        entry = graph_candidates(s.case, k)[str(f.OW.Beta)].entry
        self.assertFalse(entry.supports)
        self.assertTrue(entry.unresolved)
        s.case.apply([f.fact('denied', target='Other symptom', status='absent')])
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))
        self.prior(s)
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))
        s.case.apply([f.fact('second', target='Other symptom', observation_id='second', episode_id='second')])
        entry = graph_candidates(s.case, k)[str(f.OW.Beta)].entry
        self.assertEqual([ref.fact_ids for ref in entry.supports], [('history', 'second')])

    def test_contradicted_applicability_blocks_target_but_unknown_keeps_partial(self):
        conditions = [dict(concept_id=str(f.OW.Context), subject='patient', status='present', time_context='past')]
        k = self.relation(conditions=conditions)
        s = f.state()
        s.case.apply([f.fact('other', target='Other symptom')])
        self.assertTrue(graph_candidates(s.case, k)[str(f.OW.Beta)].entry.unresolved)
        s.case.apply([f.fact('history', kind='context', target='Test history', status='absent',
            time_context='past', category='medical_history')])
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))

    def test_partial_values_and_incomparable_units_are_unknown_not_opposition(self):
        cases = [(f.OW.Location, dict(kind='concept', concept=str(f.OW.Here)),
                  dict(attribute='Location', values=('abdomen',))),
                 (f.OW.Quality, dict(kind='quantity', value=0., operator='ge', unit='kg'),
                  dict(attribute='Quality', measurement=dict(kind='quantity', value=3., unit='day')))]
        for attribute, expected, observed in cases:
            k = self.relation(features=[(attribute, expected)])
            s = f.state()
            s.case.apply([f.fact('other', target='Other symptom'), f.fact('value', kind='attribute',
                target='Other symptom', **observed)])
            entry = graph_candidates(s.case, k)[str(f.OW.Beta)].entry
            self.assertFalse(entry.supports)
            self.assertFalse(entry.against)
            self.assertTrue(entry.unresolved)

    def test_episodes_and_acquisition_do_not_complete_each_others_pattern(self):
        k = self.relation(features=[(f.OW.Location, dict(kind='concept', concept=str(f.OW.Here))),
                                    (f.OW.Quality, dict(kind='concept', concept=str(f.OW.Dull)))])
        for second_scope in (dict(observation_id='second', episode_id='second'), dict(acquisition='EXAM')):
            s = f.state()
            s.case.apply([f.fact('base', target='Other symptom'),
                f.fact('location', kind='attribute', target='Other symptom', attribute='Location', values=('head',)),
                f.fact('quality', kind='attribute', target='Other symptom', attribute='Quality', values=('dull',), **second_scope)])
            entry = graph_candidates(s.case, k)[str(f.OW.Beta)].entry
            self.assertFalse(entry.supports)
            self.assertTrue(entry.unresolved)

    def test_attribute_only_requires_same_group_presence(self):
        k = self.relation(features=[(f.OW.Quality, dict(kind='concept', concept=str(f.OW.Dull)))], presence=False)
        s = f.state()
        s.case.apply([f.fact('other', target='Other symptom', status='unknown')])
        entry = graph_candidates(s.case, k)[str(f.OW.Beta)].entry
        self.assertTrue(any(ref.reason == 'presence_required' for ref in entry.unresolved))
        s.case.apply([f.fact('other', target='Other symptom', status='absent')])
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))

    def test_named_family_absence_is_not_whole_family_evidence_or_other_member(self):
        k = f.knowledge()
        for predicate, value in ((RDF.type, f.OW.ContextFactor), (RDFS.label, Literal('Family history', lang='en')),
                (f.OW.contextType, Literal('family_history'))):
            k._graph.add((f.OW.Family, predicate, value))
        k.questions[str(f.OW.Family)] = QuestionTemplate(text='가족 병력이 있나요?', answer_type='presence')
        f.add_pattern(k, 'familyCondition', f.OW.Other, [], applicability=[
            dict(concept_id=str(f.OW.Family), subject='family', time_context='any', status='absent')])
        s = f.state()
        s.case.apply([f.fact('mother', kind='context', target='Family history', subject='family', subject_member='mother',
            time_context='past', status='absent', category='family_history')])
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))
        s.case.apply([f.fact('whole', kind='context', target='Family history', subject='family', subject_member=None,
            time_context='past', status='absent', category='family_history')])
        self.assertIn(str(f.OW.Beta), graph_candidates(s.case, k))
        # A mother-specific condition cannot be recalled by a father's record.
        k = self.relation(conditions=[dict(concept_id=str(f.OW.Context), subject='family',
            subject_member='mother', time_context='past', status='present')])
        s = f.state()
        s.case.apply([f.fact('father', kind='context', target='Test history', subject='family', subject_member='father',
            time_context='past', category='family_history')])
        self.assertNotIn(str(f.OW.Beta), graph_candidates(s.case, k))


class ProjectionTests(unittest.TestCase):
    def check_fixed(self, payload):
        ids = {row['id'] for row in payload['patient']['facts']}
        self.assertTrue(set(payload['fixed_diagnosis']['evidence_ids']) <= ids)
        self.assertTrue(ids)
        self.assertTrue(all(ident.startswith('f_') for ident in ids))
        self.assertFalse({'supports', 'against', 'graph_ref'} & set(payload['fixed_diagnosis']))

    def test_plan_repairs_mouth_repairs_and_announcement_share_case_projection(self):
        c, s = f.consultation(prepared=f.resources(education=True)), f.chief(f.state())
        f.freeze_for_education(c, s)
        frozen = s.case.model_dump(exclude={'plan'})
        first = True
        def respond(payload):
            nonlocal first
            if payload['task'] == 'education' and first:
                first = False
                return {'P': {}}
            return education_response(payload)
        c.client.chat_handler = respond
        c.sessions['Education'].prepare_plan(s, c.client)
        ident = s.case.plan[0].id
        c.mouth.render_education(s, c.client, [dict(id=ident, text=s.case.plan[0].text)], {ident: 1}, 1,
            initial={ident: ['x' * 31]})
        with patch.object(c.knowledge, 'label', return_value='Disease alpha'):
            c.mouth.render_diagnosis(s, c.client, c.knowledge)
        self.assertEqual([p['phase'] for p in c.client.requests if p['task'] == 'education'], ['direct', 'repair'])
        requests = [p for p in c.client.requests if p['task'] in {'education', 'education_doctor'}]
        self.assertEqual(len(requests), 4)
        for payload in requests:
            self.check_fixed(payload)
            self.assertEqual(payload['fixed_diagnosis']['evidence_ids'], ['f_1'])
        self.assertEqual(s.case.model_dump(exclude={'plan'}), frozen)

    def test_missing_frozen_evidence_is_reported_without_mutation(self):
        s = f.chief(f.state())
        f.freeze(s)
        primary = s.case.primary().model_copy(update={'supports': (EvidenceRef(
            graph_ref=GraphRef(kind='association', id='a'), fact_ids=('missing',)),)})
        s.case.assessment = s.case.assessment.model_copy(update={'differential': (primary,)})
        before = s.case.model_dump()
        with self.assertRaisesRegex(ValueError, 'evidence_outside_current_facts'):
            fixed_case_payload(s.case)
        self.assertEqual(s.case.model_dump(), before)

    def test_questions_keep_unobserved_observations_and_episodes_in_scope_table(self):
        k = ScopedRecallTests().relation(conditions=[dict(concept_id=str(f.OW.Context), subject='patient',
            time_context='any', status='present')])
        c, s = f.consultation(prepared=f.resources(k)), f.state('DifferentialDiagnosis')
        s.case.apply([f.fact('context', kind='context', target='Test history', category='medical_history')])
        candidates = graph_candidates(s.case, k)
        candidate = candidates[str(f.OW.Beta)]
        original = next(ref for ref in candidate.entry.unresolved if ref.scope[1] == 'Other symptom')
        candidate.entry = candidate.entry.model_copy(update={'unresolved': tuple(original.model_copy(update={
            'scope': (*original.scope[:6], observation, episode)})
            for observation, episode in [('unobserved-a', 'episode-a'), ('unobserved-b', 'episode-b'), ('unobserved-c', 'episode-a')])})
        payload = c.differential.prepare_decision(s, candidates={str(f.OW.Beta): candidate}).payload
        rows = [q for q in payload['questions'] if q['target'] == 'Other symptom']
        self.assertEqual(len(rows), 3)
        scopes = [payload['scopes'][row['scope']] for row in rows]
        self.assertEqual(len({row['observation'] for row in scopes}), 3)
        self.assertEqual(len({row['episode'] for row in scopes}), 2)
        self.assertNotIn('unobserved-', json.dumps(payload))
        check_references(self, payload)

    def test_same_attribute_questions_keep_two_observations_in_one_episode(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        s.case.apply([f.fact('second', observation_id='second')])
        payload = c.differential.prepare_decision(s).payload
        rows = [payload['scopes'][q['scope']] for q in payload['questions'] if q.get('attribute') == 'Location']
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row['observation'] for row in rows}), 2)
        self.assertEqual(len({row['episode'] for row in rows}), 1)
        check_references(self, payload)

    def test_feature_references_restore_complete_patterns_and_preserve_zero_false(self):
        k = f.knowledge()
        f.add_pattern(k, 'numeric', f.OW.Complaint, [(f.OW.Quality,
            dict(kind='interval', lower=0., upper=2., lower_inclusive=False, approximate=False, unit='day'))],
            applicability=[dict(concept_id=str(f.OW.Context), subject='patient', time_context='past', status='absent')])
        c, s = f.consultation(prepared=f.resources(k)), f.chief(f.state('DifferentialDiagnosis'))
        s.case.apply([f.fact('unknown', target='Other symptom', status='unknown')])
        before = s.case.model_dump()
        work = c.differential.prepare_decision(s)
        check_references(self, work.payload)
        def source_definition(detail):
            return (detail['target'], detail['effect'], json.dumps(detail['target_scope'], sort_keys=True),
                tuple((c['name'], c['status'], c['subject'], c['subject_member'], c['time_context']) for c in detail['conditions']),
                tuple((feature['attribute'], ExpectedValue.model_validate(feature['expected']).signature()
                    if feature['attribute'] else None, feature['expected_status']) for feature in detail['features']))
        def wire_definition(row):
            conditions = work.payload['conditions'].get(row['applicability'], [])
            return (row['target'], row['effect'], json.dumps(row['rule_scope'], sort_keys=True),
                tuple((c['target'], c['status'], c['subject'], c['member'], c['time']) for c in conditions),
                tuple((feature['attribute'], decode_feature(k, feature)[1] if feature['attribute'] else None,
                    feature['expected_status']) for feature in row['full_pattern']))
        definitions = {ref: wire_definition(row) for ref, row in work.payload['relations'].items()}
        required = set()
        fact_refs = {fact.id: f'f_{index}' for index, fact in enumerate(s.case.current_facts(), 1)}
        for candidate in work.candidates.values():
            disease = next(row for row in work.payload['candidates'] if row['name'] == candidate.entry.name)
            for category in ('supports', 'against', 'unresolved'):
                for evidence in getattr(candidate.entry, category):
                    graph = evidence.graph_ref
                    detail = next(d for d in candidate.details if d['association'] == (graph.association_id or graph.id))
                    definition = source_definition(detail)
                    required.add(definition)
                    matching = [work.payload['evidence'][ref] for ref in disease[category]
                        if definitions[work.payload['evidence'][ref]['relation']] == definition
                        and work.payload['evidence'][ref].get('facts', []) == [fact_refs[ident] for ident in evidence.fact_ids]
                        and work.payload['evidence'][ref]['level'] == graph.kind]
                    self.assertTrue(matching, (candidate.entry.name, category, evidence))
                    if graph.kind == 'feature':
                        index = next(i for i, feature in enumerate(detail['features']) if feature['id'] == graph.id)
                        self.assertTrue(any(row['feature'] == index for row in matching))
        self.assertEqual(set(definitions.values()), required)
        numeric = next(feature['expected'] for relation in work.payload['relations'].values()
            for feature in relation['full_pattern'] if isinstance(feature['expected'], dict) and feature['expected'].get('kind') == 'interval')
        self.assertEqual(numeric['lower'], 0.)
        self.assertIs(numeric['lower_inclusive'], False)
        self.assertIs(numeric['approximate'], False)
        self.assertTrue(any(not row['against'] for row in work.payload['candidates']))
        self.assertTrue(any(row['status'] == 'unknown' for row in work.payload['facts'].values()))
        self.assertTrue(any(row.get('context') == 'Test history' and row['expects'] == {'presence': 'absent'}
            for row in work.payload['evidence'].values()))
        self.assertTrue(any(row['feature'] == 0 for row in work.payload['evidence'].values() if 'feature' in row))
        self.assertEqual(s.case.model_dump(), before)

    def test_presence_prerequisite_keeps_explicit_expectation_and_full_attribute_pattern(self):
        k = ScopedRecallTests().relation(features=[(f.OW.Quality, dict(kind='concept', concept=str(f.OW.Dull)))], presence=False)
        c, s = f.consultation(prepared=f.resources(k)), f.state('DifferentialDiagnosis')
        s.case.apply([f.fact('unknown', target='Other symptom', status='unknown')])
        payload = c.differential.prepare_decision(s).payload
        evidence = next(row for row in payload['evidence'].values()
            if row.get('reason') == 'presence_required' and row.get('target') == 'Other symptom')
        self.assertEqual(evidence['expects'], {'presence': 'present'})
        self.assertEqual(payload['relations'][evidence['relation']]['full_pattern'][0]['expected'], 'dull')
        question = next(q for q in payload['questions'] if q['target'] == 'Other symptom')
        self.assertTrue(all(e['expected'] == 'present' and e['feature'] is None
            for entries in question['expected_by_disease'].values() for e in entries))
        check_references(self, payload)


class EarAndVocabularyTests(unittest.TestCase):
    def test_first_exact_lookup_builds_index_without_changing_the_query(self):
        k = f.knowledge()
        fresh = f.ClinicalKnowledge(k._graph)
        self.assertEqual(fresh.resolve_concept('Other symptom'), [str(f.OW.Other)])

    def test_initial_segments_are_the_only_raw_input_and_acquisition_stays_distinct(self):
        rows = [f.statement('보고한 증상', input_segment='opening'),
                f.statement('관찰한 소견', input_segment='vital_signs', target_terms=['Test examination finding'],
                    record_category='objective_observation')]
        client = f.FakeSDK(chat_handler=lambda p: {'statements': rows})
        c, s = f.consultation(client), f.state()
        s.turn = TurnContext(kind='initial', response={'opening': '보고한 증상', 'vital_signs': '관찰한 소견'})
        c.ear.process_input(s, c.knowledge, client)
        payload = client.requests[0]
        self.assertNotIn('input', payload)
        self.assertEqual(payload['dialogue'], [])
        self.assertEqual(payload['input_segments'], {'opening': '보고한 증상', 'vital_signs': '관찰한 소견'})
        self.assertEqual({row.source_ref for row in s.case.facts.values()}, {'initial:opening', 'initial:vital_signs'})
        self.assertEqual(len(client.requests), 1)

    def test_mapping_preserves_resolved_short_reply_in_normal_and_repair_payloads(self):
        def respond(payload):
            if payload['task'] == 'input_context':
                return {'statements': [f.statement('그것도 있어요', target_terms=['test'], note_value='Also reports the test complaint')]}
            return [{}]
        _, _, client = f.interpret([], text='그것도 있어요', responses=respond)
        mapping = [p for p in client.requests if p['task'] == 'input_mapping']
        self.assertEqual(len(mapping), 2)
        self.assertTrue(all(p['statements'][0]['normalized_claim'] == 'Also reports the test complaint' for p in mapping))

    def test_query_union_precedes_cap_and_alias_multiplicity_does_not_add_votes(self):
        k = f.knowledge()
        for index in range(80):
            ident = f.OW[f'Distractor{index:03}']
            k._graph.add((ident, RDF.type, f.OW.Symptom))
            k._graph.add((ident, RDFS.label, Literal(f'Broad candidate {index}', lang='en')))
        k._graph.add((f.OW.Other, SKOS.altLabel, Literal('독립적인 표적', lang='ko')))
        k._graph.add((f.OW.Other, SKOS.altLabel, Literal('Broad candidate specific', lang='en')))
        k.validate_graph()
        ranked = concept_rank(k, ['broad candidate', '독립적인 표적이 있어요'], ('Symptom',))
        self.assertIn(str(f.OW.Other), ranked[:8])
        baseline = k.search_concepts(['test', '독립적인 표적'], kind='Symptom')
        for index in range(30):
            k._graph.add((f.OW.Complaint, SKOS.altLabel, Literal('Test complaint' + ' ' * index)))
        k.validate_graph()
        self.assertEqual(k.search_concepts(['test', '독립적인 표적'], kind='Symptom'), baseline)

    def test_actual_bundle_night_sweats_exact_korean_and_unrelated_input(self):
        k = f.prepare().knowledge
        if not k.term_id('Night sweats', 'Symptom'):
            self.skipTest('Require the installed real vocabulary; synthetic archive has separate structural checks')
        for quote, hints in [('밤에 땀이 많이 나요', ['night-time perspiration']), ('야간에 땀이 나요', []),
                             ('밤에 옷이 젖어요', []), ('Night sweats', ['Night sweats'])]:
            statement = ContextStatement.model_validate(f.statement(quote, target_terms=hints))
            contracts = candidate_contracts(k, statement, None)
            self.assertIn('Night sweats', [row['id'] for row in contracts])
            self.assertLessEqual(len(contracts), 8)
            self.assertTrue(all(row['attributes'] == [] for row in contracts))
        for quote in ('purple notebook', '보라색 공책을 책상에 놓았어요', 'zzqvxxj'):
            statement = ContextStatement.model_validate(f.statement(quote, target_terms=[]))
            self.assertEqual(candidate_contracts(k, statement, None), [])

    def test_family_exam_and_numeric_role_filters_survive_query_union(self):
        k = f.knowledge()
        cases = [(f.statement('가상소견', target_terms=['Test examination finding']), None),
                 (f.statement('가상병력', target_terms=['Test history'], subject='family', record_category='family_history'), None),
                 (f.statement('Three days', focus='attribute', target_terms=['Test complaint'],
                    measurement=dict(kind='quantity', value=3., unit='day')), None)]
        for raw, question in cases:
            self.assertEqual(candidate_contracts(k, ContextStatement.model_validate(raw), question), [])


class GuidelineAndGetterTests(unittest.TestCase):
    def sources(self, root):
        rows = []
        for index in range(8):
            raw = f'\ufeff# 원문 {index}\n\n  원문 인용입니다.\n'.encode()
            (root / f'{index}.md').write_bytes(raw)
            rows.append(dict(document_id=f'd{index}', path=f'{index}.md', sha256=hashlib.sha256(raw).hexdigest(),
                relation='exact' if index in {3, 6, 7} else 'related',
                evidence_use='care_navigation' if index in {5, 6, 7} else 'background_only',
                scope='Adults in outpatient care', audit_private={'future': True}))
        return rows

    def test_direct_partition_freezes_five_before_reads_and_failure_never_backfills(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', NOVA_GUIDELINES_DIR=folder):
            root = Path(folder)
            rows = self.sources(root)
            library = GuidelineLibrary({'disease': rows})
            documents, _ = library.read('disease')
            self.assertEqual([d['document_id'] for d in documents], ['d6', 'd7', 'd0', 'd1', 'd2'])
            (root / '6.md').write_text('Changed')
            opened, original = [], Path.read_bytes
            def read(path):
                opened.append(path.name)
                return original(path)
            with patch.object(Path, 'read_bytes', read):
                documents, failures = library.read('disease')
            self.assertEqual(opened, ['6.md', '7.md', '0.md', '1.md', '2.md'])
            self.assertEqual([d['document_id'] for d in documents], ['d7', 'd0', 'd1', 'd2'])
            self.assertEqual([d['document_id'] for d in failures], ['d6'])
            self.assertEqual(documents[1]['relation'], 'related')

    def test_document_projection_repair_and_non_ascii_citation_preserve_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', NOVA_GUIDELINES_DIR=folder):
            root = Path(folder)
            rows = self.sources(root)
            rows[0]['scope'] = 'Fresh disease label or alias match in the supplied guideline catalog'
            c, s = f.consultation(prepared=f.resources(education=True)), f.chief(f.state())
            f.freeze_for_education(c, s)
            requested = []
            library = GuidelineLibrary({'primary': rows})
            def read(disease):
                requested.append(disease)
                return library.read('primary')
            c.knowledge.guidelines.read = read
            c.client.chat_handler = lambda payload: {'P': {}} if payload.get('phase') == 'direct' else education_response(payload)
            c.sessions['Education'].prepare_plan(s, c.client)
            self.assertEqual(requested, [c.knowledge.term_id(s.case.primary().name, 'Disease')])
            payloads = [p for p in c.client.requests if p['task'] == 'education']
            self.assertEqual(len(payloads), 2)
            for payload in payloads:
                for doc in payload['documents']:
                    self.assertTrue(set(doc) <= {'document_id', 'relation', 'evidence_use', 'scope', 'text'})
                    self.assertEqual(doc['text'].encode(), (root / f"{doc['document_id'][1:]}.md").read_bytes())
                    if doc['document_id'] == 'd0':
                        self.assertNotIn('scope', doc)
                    else:
                        self.assertEqual(doc['scope'], 'Adults in outpatient care')
            contexts = {d['document_id']: [(0, d['text'])] for d in payloads[0]['documents']}
            quote = '원문 인용입니다.'
            ref = references([dict(document_id='d7', quote=quote)], contexts)[0]
            raw = (root / '7.md').read_bytes()
            self.assertEqual(raw[ref['start_byte']:ref['end_byte']], quote.encode())
            with self.assertRaises(ValueError):
                references([dict(document_id='d5', quote=quote)], contexts)

    def test_invalid_links_are_filtered_without_casting_attributes_to_presence(self):
        k = f.knowledge()
        k._graph.add((f.OW.Complaint, f.OW.hasAttribute, f.OW.Other))
        k._graph.add((f.OW.Quality, f.OW.canHaveValue, f.OW.Other))
        k._graph.add((f.OW.Other, f.OW.canHaveValue, f.OW.Dull))
        k.validate_graph()
        self.assertNotIn(str(f.OW.Other), k.get_symptom_attributes(str(f.OW.Complaint)))
        self.assertEqual(k.get_attribute_values(str(f.OW.Quality)), [str(f.OW.Dull)])
        self.assertEqual(k.get_attribute_values(str(f.OW.Other)), [])
        c, s = f.consultation(prepared=f.resources(k)), f.chief(f.state('ChiefComplaint'))
        self.assertIsNone(c.tools._spec(s, str(f.OW.Complaint), str(f.OW.Other)))
        self.assertIsNotNone(c.tools._spec(s, str(f.OW.Complaint)))
        c.sessions['ChiefComplaint'].prepare_collection(s)
        self.assertTrue(all(q.attribute != 'Other symptom' for q in s.interview.queue))
        self.assertIn((f.OW.Complaint, f.OW.hasAttribute, f.OW.Other), k._graph)


if __name__ == '__main__':
    unittest.main()
