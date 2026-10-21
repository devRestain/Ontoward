"""Keyless augmentation acceptance through real compiler, loader and runtime."""
import copy
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge.conditions import QuestionTemplate
from knowledge.graph import ClinicalKnowledge
from ontoward_extraction.augmentation import (apply_delta, compile_delta, file_hash,
    load_parent, make_plan, nullable_hash, read_plan, resolve_tasks)
from ontoward_extraction.augmentation_models import ConceptTask, Delta
from ontoward_extraction.augmentation_run import (activate, discoveries, packets, rebuild, repair_discovery, repair_review, reviewed_results, run_augmentation, validate_reply)
from ontoward_extraction.augmentation_verify import runtime_fact, runtime_state, runtime_tools
from ontoward_extraction.install import install
from ontoward_extraction.jobs import Jobs, OutcomeUnknown
from ontoward_extraction.llm import ProviderError
from ontoward_extraction.models import Concept, Relation, canonical, digest, identifier
from workflow.rules.assessment import graph_candidates
from workflow.rules.decision import prepare_decision
from workflow.state.models import Answer

from augmentation_fixture import (SEED, SHORT, SHORT2, INSOMNIA, HYPNOTIC, GHD,
    SCOPE, MockProvider, config, parent_bundle, specifications)


class AugmentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = parent_bundle(self.root / 'parent')
        self.config = config()
        self.seed_path = self.root / 'seed.json'
        synthetic_seed = dict(SEED, replace_association_ids=[])
        self.seed_path.write_text(canonical(synthetic_seed))
        self.summary = make_plan(self.manifest, self.seed_path, self.config, self.root / 'plans')
        self.plan_path = self.summary['plan']
        self.plan, self.parent = read_plan(self.plan_path)

    def changed_plan(self, **changes):
        value = copy.deepcopy(self.plan)
        value['scope'].update(changes)
        return value

    def mock_run(self, **kwargs):
        provider = MockProvider(self.config, self.root, **kwargs)
        result = run_augmentation(self.plan_path, self.config, self.root / 'work', self.root / 'output', 20, provider=provider)
        return result, provider

    def test_empty_roundtrip_preserves_graphs_overrides_units_roles_and_values(self):
        proof = self.summary['roundtrip']
        self.assertEqual(proof['parent_meanings_unauthorized_changes'], 0)
        self.assertTrue(proof['exact_empty_clinical_graph'])
        self.assertTrue(proof['questions_roles_exact'])
        self.assertEqual(proof['changed_numeric_units'], {})
        self.assertEqual(proof['value_matches_preserved'], 1)
        report = compile_delta(self.parent, self.plan, Delta(), self.root / 'empty')
        child = load_parent(report['manifest'])
        self.assertEqual(child.questions, self.parent.questions)
        self.assertEqual(child.knowledge.numeric_units(SHORT, 'urn:fixture:quantity'), ['cm'])
        self.assertTrue(child.knowledge.value_matches('urn:fixture:related', 'urn:fixture:value', hierarchy=True))

    def test_append_only_extension_and_precondition_rejection(self):
        delta = dict(operations=[dict(op='extend_concept', id=SHORT,
            before_hash=self.plan['preconditions']['concepts'][SHORT], aliases=['Additional alias'])])
        applied = apply_delta(self.parent, self.plan, delta)
        node = next(n for n in applied['concepts'] if n['id'] == SHORT)
        self.assertEqual(node['attributes'], self.parent.concepts[SHORT]['attributes'])
        self.assertEqual(node['name'], self.parent.concepts[SHORT]['name'])
        delta['operations'][0]['before_hash'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'precondition_mismatch'):
            apply_delta(self.parent, self.plan, delta)
        with self.assertRaises(ValueError):
            Delta.model_validate(dict(operations=[dict(op='upsert', concept=self.parent.concepts[SHORT])]))

    def test_add_existing_and_invalid_endpoint_or_context_attributes_rejected(self):
        with self.assertRaisesRegex(ValueError, 'requires_new_identity'):
            apply_delta(self.parent, self.plan, dict(operations=[dict(op='add_concept', concept=self.parent.concepts[SHORT])]))
        with self.assertRaisesRegex(ValueError, 'invalid_vocabulary_endpoint'):
            apply_delta(self.parent, self.plan, dict(operations=[dict(op='extend_concept', id=SHORT,
                before_hash=self.plan['preconditions']['concepts'][SHORT], attributes=[GHD])]))
        node = Concept(id=identifier('ContextFactor', ['ContextFactor', 'bad']), kind='ContextFactor', name='Bad', korean='잘못된문맥',
            context_type='medication_history', attributes=['urn:fixture:quantity']).model_dump()
        with self.assertRaisesRegex(ValueError, 'context_cannot_own'):
            apply_delta(self.parent, self.plan, dict(operations=[dict(op='add_concept', concept=node)]))

    def test_effect_conflict_requires_exact_allowlisted_parent_hash(self):
        assoc, relation = next(iter(self.parent.associations.items()))
        altered = dict(relation.model_dump(), effect='against')
        with self.assertRaisesRegex(ValueError, 'effect_conflict'):
            apply_delta(self.parent, self.plan, dict(operations=[dict(op='add_relation', relation=altered)]))
        operation = dict(op='replace_relation', association_id=assoc,
            before_hash=self.plan['preconditions']['relations'][assoc], relation=altered)
        with self.assertRaisesRegex(ValueError, 'replacement_precondition'):
            apply_delta(self.parent, self.plan, dict(operations=[operation]))
        plan = self.changed_plan(replace_association_ids=[assoc])
        result = apply_delta(self.parent, plan, dict(operations=[operation]))
        self.assertEqual(result['changes']['replaced_associations'], [assoc])
        operation['before_hash'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'replacement_precondition'):
            apply_delta(self.parent, plan, dict(operations=[operation]))

    def test_duplicate_meanings_skip_without_changing_effect(self):
        row = next(iter(self.parent.associations.values())).model_dump()
        result = apply_delta(self.parent, self.plan, dict(operations=[dict(op='add_relation', relation=row)] * 2))
        self.assertEqual(len(result['relations']), len(self.parent.associations))
        self.assertEqual(result['changes']['duplicate_relations_skipped'], 2)

    def test_question_override_does_not_implicitly_modify_global_role(self):
        key = SHORT + '|urn:fixture:quantity'
        question = dict(self.parent.questions['questions'][key], text='키를 다시 확인할까요?')
        op = dict(op='set_question', key=key, before_hash=self.plan['preconditions']['questions'][key], question=question)
        plan = self.changed_plan(question_keys=[key])
        result = apply_delta(self.parent, plan, dict(operations=[op]))
        self.assertEqual(result['questions']['attribute_roles'], self.parent.questions['attribute_roles'])
        op['role'] = dict(attribute_id='urn:fixture:quantity', before_hash=None,
            value=dict(order=3, category='measurement', clarification='값을 다시 알려주세요'))
        with self.assertRaisesRegex(ValueError, 'role_precondition'):
            apply_delta(self.parent, plan, dict(operations=[op]))
        op['role']['before_hash'] = self.plan['preconditions']['roles']['urn:fixture:quantity']
        plan['scope']['role_ids'] = ['urn:fixture:quantity']
        result = apply_delta(self.parent, plan, dict(operations=[op]))
        self.assertIn(SHORT2, result['changes']['role_impacts']['urn:fixture:quantity'])

    def test_value_ownership_cannot_be_extended_to_another_attribute(self):
        plan = self.changed_plan(extend_ids=['urn:fixture:quantity'])
        with self.assertRaisesRegex(ValueError, 'existing_value_ownership_changed'):
            apply_delta(self.parent, plan, dict(operations=[dict(op='extend_concept', id='urn:fixture:quantity',
                before_hash=plan['preconditions']['concepts']['urn:fixture:quantity'], values=['urn:fixture:value'])]))

    def test_numeric_mismatch_and_malformed_question_contract_rejected(self):
        row = next(r for r in self.parent.associations.values() if any(f.attribute for f in r.features)).model_dump()
        row['features'][0]['expected']['unit'] = 'kg'
        with self.assertRaisesRegex(ValueError, 'unit_mismatch'):
            apply_delta(self.parent, self.plan, dict(operations=[dict(op='add_relation', relation=row)]))
        with self.assertRaises(ValueError):
            QuestionTemplate(text='성장속도는 얼마인가요?', answer_type='quantity', affirmative=True, units=['cm/year'])

    def test_python_identity_mapping_reuses_only_explicit_registered_role(self):
        task = dict(ref='new:height', kind='Symptom', name=self.parent.concepts[SHORT]['name'], owner_ref=None,
            reuse_id=None, instruction='A lexical hit needs an explicit same-role decision')
        with self.assertRaisesRegex(ValueError, 'requires_explicit_reuse'):
            resolve_tasks(self.parent, [ConceptTask.model_validate(task)])
        task['reuse_id'] = SHORT
        self.assertEqual(resolve_tasks(self.parent, [ConceptTask.model_validate(task)])['new:height'], SHORT)
        task['reuse_id'] = GHD
        with self.assertRaisesRegex(ValueError, 'role_mismatch'):
            resolve_tasks(self.parent, [ConceptTask.model_validate(task)])

    def test_plan_contract_and_active_parent_drift_are_rejected(self):
        changed = dict(self.config, batch_size=1)
        with self.assertRaisesRegex(ValueError, 'config_or_contract_changed'):
            read_plan(self.plan_path, changed)
        self.manifest.write_text(self.manifest.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'active_parent_changed'):
            read_plan(self.plan_path)

    def test_mock_generation_repairs_only_invalid_sibling_and_resume_calls_zero(self):
        before = {p: file_hash(p) for p in self.manifest.parent.iterdir()}
        result, provider = self.mock_run(invalid_once=True)
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['build']['preservation']['parent_meanings_unauthorized_changes'], 0)
        self.assertEqual({p: file_hash(p) for p in before}, before)
        jobs = Jobs(self.root / 'work' / self.plan['plan_id'], readonly=True)
        try:
            attempts = [r[0] for r in jobs.db.execute("SELECT attempt_count FROM jobs WHERE phase='augment_concepts'")]
            self.assertEqual(attempts.count(2), 1)
            self.assertEqual(attempts.count(1), len(attempts) - 1)
            self.assertTrue(any(r['relation']['effect'] == 'neutral' for r in jobs.results('augment_review')))
            self.assertIsNotNone(jobs.get('workset:augment_questions'))
        finally:
            jobs.close()
        calls = len(provider.calls)
        run_augmentation(self.plan_path, self.config, self.root / 'work', self.root / 'output', 20, resume=True, provider=provider)
        self.assertEqual(len(provider.calls), calls)
        # Rebuild is keyless and cannot construct a Provider.
        with patch('ontoward_extraction.augmentation_run.Provider', side_effect=AssertionError('no model client')):
            self.assertEqual(rebuild(self.plan_path, self.root / 'work', self.root / 'output')['build_id'], result['build']['build_id'])

    def test_request_ceiling_stops_before_network_and_resumes_same_frozen_workset(self):
        provider = MockProvider(self.config, self.root)
        result = run_augmentation(self.plan_path, self.config, self.root / 'work', self.root / 'output', 1, provider=provider)
        self.assertEqual(result['state'], 'paused')
        self.assertEqual(result['model_transmissions'], 1)
        self.assertEqual(len(provider.calls), 1)
        result = run_augmentation(self.plan_path, self.config, self.root / 'work', self.root / 'output', 20, resume=True, provider=provider)
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(sum(phase == 'augment_discover' for phase, _ in provider.calls), 1)

    def test_saved_response_recovery_and_pause_keep_accepted_rows(self):
        provider = MockProvider(self.config, self.root)
        def pause():
            jobs = Jobs(self.root / 'work' / self.plan['plan_id'])
            jobs.pause()
            jobs.close()
        provider.after_send = pause
        result = run_augmentation(self.plan_path, self.config, self.root / 'work', self.root / 'output', 20, provider=provider)
        self.assertEqual(result['state'], 'paused')
        jobs = Jobs(self.root / 'work' / self.plan['plan_id'])
        try:
            request = jobs.db.execute('SELECT * FROM requests').fetchone()
            # Simulate a crash after durable response save, before acceptance.
            jobs.db.execute("UPDATE requests SET state='received'")
            jobs.db.execute("UPDATE jobs SET status='running', result=NULL WHERE phase='augment_discover'")
            jobs.db.commit()
        finally:
            jobs.close()
        provider.after_send = None
        result = run_augmentation(self.plan_path, self.config, self.root / 'work', self.root / 'output', 20, resume=True, provider=provider)
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(sum(phase == 'augment_discover' for phase, _ in provider.calls), 1)

    def test_nova_contract_is_opt_in_and_shares_complete_definitions_once(self):
        configuration = dict(self.config, provider='nova_dev')
        provider = MockProvider(configuration, self.root)
        from ontoward_extraction.augmentation_run import OUTPUT_CONTRACT
        payload = provider.payload('test', [dict(role='system', content='Generate')], {'type': 'object'}, True, output_contract=OUTPUT_CONTRACT)
        self.assertNotIn('Each result has job_id, concepts, relations, and value_matches', payload['messages'][0]['content'])
        legacy = provider.payload('test', [], {'type': 'object'})
        self.assertIn('Each result has job_id, concepts, relations, and value_matches', legacy['messages'][0]['content'])
        parts = packets('augment_review', [dict(job_id='a'), dict(job_id='b')], {'concepts': [dict(id='only', units=['cm/year'], attributes=['growth'])]})
        self.assertEqual(sum('only' in m['content'] for m in parts), 1)
        self.assertIn('cm/year', parts[0]['content'])

    def test_api_unknown_outcome_requires_explicit_retry_and_preserves_original(self):
        provider = MockProvider(self.config, self.root)
        original = provider.send
        transmissions = []
        def uncertain(payload):
            transmissions.append(payload['request_id'])
            if len(transmissions) == 1:
                raise ProviderError('fixture_unknown', unknown=True)
            return original(payload)
        provider.send = uncertain
        with self.assertRaises(OutcomeUnknown):
            run_augmentation(self.plan_path, self.config, self.root/'work', self.root/'output', 20, provider=provider)
        with self.assertRaises(OutcomeUnknown):
            run_augmentation(self.plan_path, self.config, self.root/'work', self.root/'output', 20, provider=provider, resume=True)
        self.assertEqual(len(transmissions), 1)
        result = run_augmentation(self.plan_path, self.config, self.root/'work', self.root/'output', 20,
            provider=provider, resume=True, retry_unknown=True)
        self.assertEqual(result['state'], 'complete')
        jobs = Jobs(self.root/'work'/self.plan['plan_id'], readonly=True)
        try:
            old = jobs.db.execute('SELECT state,error FROM requests WHERE request_id=?', (transmissions[0],)).fetchone()
            self.assertEqual(tuple(old), ('superseded', 'explicit_retry_unknown'))
            self.assertEqual(jobs.get('model_transmissions'), len(transmissions))
        finally:
            jobs.close()

    def test_augmentation_activation_uses_current_target_without_cleanup(self):
        target = self.root / 'active'
        install(self.manifest, target)
        old = {p: file_hash(p) for p in (target / 'builds/fixture-parent').iterdir()}
        summary = make_plan(target / 'manifest.json', self.seed_path, self.config, self.root/'latest-plan')
        result = run_augmentation(summary['plan'], self.config, self.root/'latest-work', self.root/'latest-output', 20,
            provider=MockProvider(self.config, self.root))
        installed = activate(summary['plan'], self.root/'latest-work', self.root/'latest-output', target)
        self.assertEqual(installed['build_id'], result['build']['build_id'])
        self.assertFalse(installed['cleanup'])
        self.assertEqual({p: file_hash(p) for p in old}, old)
        with self.assertRaisesRegex(ValueError, 'active_parent_changed'):
            activate(summary['plan'], self.root/'latest-work', self.root/'latest-output', target)

    def test_scoped_discovery_repair_preserves_original_database_rows_requests_and_usage(self):
        old = copy.deepcopy(self.plan)
        old['contracts']['generator']['augmentation_run.py'] = 'previous_scope_adapter'
        old.pop('plan_id')
        old['plan_id'] = digest(old)[:32]
        old_path = self.root/'source-plan.json'
        old_path.write_text(canonical(old))
        work = self.root/'repair-work'
        jobs = Jobs(work/old['plan_id'], dict(contract='augmentation-1', plan_id=old['plan_id'], config=self.config))
        _, fixture, _ = specifications()
        raw, projected = [], []
        for cluster in self.plan['seed']['clusters']:
            ident = jobs.add('augment_discover', dict(cluster=cluster))
            value = dict(copy.deepcopy(fixture), job_id=ident)
            if cluster['id'] == 'short_stature':
                value['concepts'] = value['concepts'][3:]
                value['relations'] = [r for r in value['relations'] if r['instruction'] not in {'use_insomnia','use_behavior','neutral'}]
            raw.append(value)
            corrected = copy.deepcopy(value)
            if cluster['id'] == 'insomnia_medication':
                corrected['concepts'] = corrected['concepts'][:3]
                corrected['extensions'] = []
                corrected['relations'] = [r for r in corrected['relations'] if r['instruction'] in {'use_insomnia','use_behavior','neutral'}]
            projected.append(corrected)
        jobs.prepare_request('original', 'openai_api', dict(original=True), [r['job_id'] for r in raw])
        jobs.accept('original', {r['job_id']:r for r in raw}, {}, dict(day='2026-10-21', model='fixture', input_tokens=123, output_tokens=45))
        jobs.set('state', 'failed')
        jobs.set('error', 'ambiguous_new_identity_use_registered_ref')
        jobs.close()
        source_hash = file_hash(work/old['plan_id']/'jobs.sqlite3')
        amendments = {p['job_id']:dict(before_hash=digest(r), result=p) for r,p in zip(raw, projected) if r!=p}
        amendments_path = self.root/'amendments.json'
        amendments_path.write_text(canonical(amendments))
        result = repair_discovery(old_path, self.plan_path, work, amendments_path)
        self.assertEqual(result['state'], 'paused')
        self.assertEqual(file_hash(work/old['plan_id']/'jobs.sqlite3'), source_hash)
        copied = Jobs(work/self.plan['plan_id'], readonly=True)
        try:
            self.assertEqual(sorted(copied.results('augment_discover'),key=lambda r:r['job_id']), sorted(raw,key=lambda r:r['job_id']))
            self.assertEqual(sorted(discoveries(copied),key=lambda r:r['job_id']), sorted(projected,key=lambda r:r['job_id']))
            self.assertEqual(copied.status()['usage'][0]['input_tokens'], 123)
            self.assertEqual(copied.db.execute('SELECT payload FROM requests').fetchone()[0], canonical(dict(original=True)))
        finally:
            copied.close()

    def test_discovery_cannot_extend_a_different_jobs_cluster(self):
        jobs = Jobs(self.root/'scope')
        try:
            _, fixture, _ = specifications()
            raw = dict(fixture, job_id='scope')
            with self.assertRaisesRegex(ValueError, 'outside_job_cluster'):
                validate_reply(jobs, 'augment_discover', dict(cluster=self.plan['seed']['clusters'][0]), raw, self.parent, self.plan)
        finally:
            jobs.close()

    def test_review_semantic_guards_reject_target_negation_and_unscoped_family_support(self):
        jobs=Jobs(self.root/'semantic')
        try:
            jobs.set('uri_mapping', {})
            jobs.set('effective_vocabulary', self.parent.concepts)
            row=next(r for r in self.parent.associations.values() if any(f.attribute for f in r.features)).model_dump()
            row['features'].append(dict(status='absent'))
            row['features'].append(dict(status='present'))
            source=dict(task=dict(disease_ref=row['disease_id'],target_ref=row['target_id']))
            raw=dict(job_id='semantic',relation=row,rationale='Typed representation fixture',evidence_kind='model_medical_knowledge')
            with self.assertRaisesRegex(ValueError,'Target_presence'):
                validate_reply(jobs,'augment_review',source,raw,self.parent,self.plan)
            disease=identifier('Disease',['Disease','constitutional growth delay'])
            vocabulary=dict(self.parent.concepts)
            vocabulary[disease]=Concept(id=disease,kind='Disease',name='Constitutional growth delay',korean='체질성성장지연').model_dump()
            jobs.set('effective_vocabulary',vocabulary);jobs.set('uri_mapping',{'new:CDGP':disease})
            raw['relation']=dict(disease_id=disease,target_id=HYPNOTIC,target_scope=SCOPE,
                features=[dict(status='present')],applicability=[],effect='support')
            source=dict(task=dict(disease_ref=disease,target_ref=HYPNOTIC))
            with self.assertRaisesRegex(ValueError,'cannot_encode_required_child_trajectory'):
                validate_reply(jobs,'augment_review',source,raw,self.parent,self.plan)
        finally:jobs.close()

    def test_settled_review_repair_retries_only_invalid_rows_without_overwriting_source(self):
        result,_=self.mock_run()
        source_dir=self.root/'work'/self.plan['plan_id']
        jobs=Jobs(source_dir)
        # Simulate a settled old adapter accepting one contradictory condition.
        original=jobs.db.execute("SELECT * FROM jobs WHERE phase='augment_review' ORDER BY job_id LIMIT 1").fetchone()
        raw=json.loads(original['result'])
        raw['relation']['features'].extend([dict(status='absent'),dict(status='present')])
        with jobs.db:jobs.db.execute('UPDATE jobs SET result=? WHERE job_id=?',(canonical(raw),original['job_id']))
        jobs.set('state','failed');jobs.set('error','required_candidate_unreachable:fixture')
        jobs.close()
        old_path=self.root/'review-source-plan.json'
        old=copy.deepcopy(self.plan)
        old['contracts']['generator']['augmentation_run.py']='old_review_semantics'
        old.pop('plan_id');old['plan_id']=digest(old)[:32]
        # Relocate only this synthetic checkpoint to its synthetic old identity.
        moved=self.root/'work'/old['plan_id'];source_dir.rename(moved)
        jobs=Jobs(moved);jobs.set('identity',dict(contract='augmentation-1',plan_id=old['plan_id'],config=self.config));jobs.close()
        old_path.write_text(canonical(old))
        before=file_hash(moved/'jobs.sqlite3')
        repaired=repair_review(old_path,self.plan_path,self.root/'work')
        self.assertEqual(file_hash(moved/'jobs.sqlite3'),before)
        self.assertEqual(repaired['recovery']['invalid_review_rows'],1)
        jobs=Jobs(source_dir,readonly=True)
        try:
            self.assertEqual(jobs.db.execute('SELECT result FROM jobs WHERE job_id=?',(original['job_id'],)).fetchone()[0],canonical(raw))
            pending=jobs.pending('augment_review')
            self.assertEqual(len(pending),1)
            self.assertEqual(pending[0]['attempt_count'],original['attempt_count'])
            self.assertEqual(jobs.get('model_transmissions'),result['model_transmissions'])
        finally:jobs.close()

    def test_install_preserves_all_builds_and_stale_parent_cannot_activate(self):
        target = self.root / 'target'
        install(self.manifest, target)
        extra = target / 'unrelated.json'
        extra.write_text('{"retained":true}')
        before = (target / 'manifest.json').read_bytes()
        child_dir = self.root / 'child'
        child_dir.mkdir()
        for path in self.manifest.parent.iterdir():
            (child_dir / path.name).write_bytes(path.read_bytes())
        manifest = json.loads((child_dir / 'manifest.json').read_text())
        manifest['build_id'] = 'fixture-child'
        guideline = json.loads((child_dir / manifest['guidelines']['path']).read_text())
        guideline['build_id'] = 'fixture-child'
        (child_dir / manifest['guidelines']['path']).write_text(canonical(guideline))
        manifest['guidelines']['sha256'] = file_hash(child_dir / manifest['guidelines']['path'])
        (child_dir / 'manifest.json').write_text(canonical(manifest))
        with self.assertRaisesRegex(ValueError, 'child_preserved_not_activated'):
            install(child_dir / 'manifest.json', target, cleanup=False, expected_parent_manifest_sha256='stale')
        self.assertEqual((target / 'manifest.json').read_bytes(), before)
        self.assertTrue((target / 'builds/fixture-child/manifest.json').is_file())
        install(child_dir / 'manifest.json', target, cleanup=False,
            expected_parent_manifest_sha256=hashlib.sha256(before).hexdigest())
        self.assertTrue((target / 'builds/fixture-parent/manifest.json').is_file())
        self.assertTrue(extra.is_file())
        with (target / '.install.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'install_already_running'):
                install(self.manifest, target)

    def test_real_candidate_questions_scopes_unknown_normal_use_and_growth_controls(self):
        result, _ = self.mock_run()
        knowledge = ClinicalKnowledge.load(result['build']['manifest'])
        tools = runtime_tools(knowledge)
        names = lambda name, kind='ContextFactor': knowledge.term_id(name, kind)
        use = names('Sedative, hypnotic, or anxiolytic use disorder', 'Disease')
        failed = names('Unsuccessful attempts to reduce hypnotic use')
        harm = names('Continued hypnotic use despite harm')
        s = runtime_state()
        s.case.apply([runtime_fact(knowledge, INSOMNIA), runtime_fact(knowledge, HYPNOTIC)])
        candidates = graph_candidates(s.case, knowledge)
        self.assertIn(use, candidates)
        self.assertFalse(candidates[use].entry.supports)
        options = tools._options(s, {use: candidates[use]})
        self.assertIn(failed, {spec['target_id'] for spec, _ in options.values()})
        # Production decision refs resolve to these same eligible Context options.
        work = prepare_decision(s, knowledge, tools, candidates={use: candidates[use]})
        self.assertTrue(work.options)
        self.assertTrue(all(q['ref'] in work.options for q in work.payload['questions']))
        spec = next(spec for spec, _ in options.values() if spec['target_id'] == failed)
        self.assertTrue(tools._allowed_now(s, dict(spec, purpose='clarification')))
        self.assertFalse(tools._allowed_now(s, dict(spec, purpose='feature')))
        s.case.apply([runtime_fact(knowledge, failed, status='absent')])
        remaining = graph_candidates(s.case, knowledge)
        self.assertTrue(use not in remaining or not remaining[use].entry.supports)
        self.assertFalse(any(spec['target_id'] == failed for spec, _ in tools._options(s, remaining).values()))
        # Behavior without insomnia is a separate candidate path; complete facts activate its effect.
        s = runtime_state()
        s.case.apply([runtime_fact(knowledge, failed), runtime_fact(knowledge, HYPNOTIC), runtime_fact(knowledge, harm)])
        self.assertTrue(graph_candidates(s.case, knowledge)[use].entry.supports)
        # A prior unknown answer remains blocked by the existing question lifecycle.
        s = runtime_state()
        s.case.apply([runtime_fact(knowledge, INSOMNIA), runtime_fact(knowledge, HYPNOTIC)])
        candidates = graph_candidates(s.case, knowledge)
        spec = next(spec for spec, _ in tools._options(s, {use: candidates[use]}).values() if spec['target_id'] == failed)
        question = tools._question(spec, 'asked', 0, 0)
        s.interview.answers.append(Answer(question_id='asked', source_ref='answer', scope='DifferentialDiagnosis', purpose='context',
            key=question.semantic_key(), outcome='unknown'))
        self.assertFalse(tools._allowed_now(s, spec))
        # Family negative alone cannot remove every CDGP path; actual impaired growth is not support.
        cdgp = names('Constitutional growth delay', 'Disease')
        fss = names('Familial short stature', 'Disease')
        late = names('Family history of late growth or maturation')
        trajectory = names('Linear growth trajectory', 'FindingAttribute')
        impaired = knowledge.value_id('Linear growth trajectory', 'Declining linear growth trajectory')
        velocity = names('Height velocity', 'FindingAttribute')
        for target in (SHORT, SHORT2):
            s = runtime_state()
            s.case.apply([runtime_fact(knowledge, target), runtime_fact(knowledge, late, status='absent', subject='family', time='past')])
            candidates = graph_candidates(s.case, knowledge)
            self.assertTrue({cdgp, fss} <= set(candidates))
            s.case.apply([runtime_fact(knowledge, target, attribute=trajectory, values=[impaired]),
                runtime_fact(knowledge, target, attribute=velocity, measurement=dict(kind='quantity', value=1.0, unit='cm/year'))])
            candidates = graph_candidates(s.case, knowledge)
            self.assertFalse(candidates[cdgp].entry.supports)
            self.assertFalse(candidates[fss].entry.supports)
            self.assertEqual(knowledge.numeric_units(target, velocity), ['cm/year'])
            self.assertFalse(any(spec['attribute_id'] == velocity for spec, _ in tools._options(s, candidates).values()))
        # C10-style pathological route stays independent of a complaint or medication explanation.
        s = runtime_state()
        s.case.apply([runtime_fact(knowledge, 'urn:fixture:weight'), runtime_fact(knowledge, 'urn:fixture:heat'), runtime_fact(knowledge, INSOMNIA)])
        candidates = graph_candidates(s.case, knowledge)
        self.assertIn('urn:fixture:thyroid', candidates)
        self.assertTrue(candidates['urn:fixture:thyroid'].entry.supports)
        self.assertTrue(use not in candidates or not candidates[use].entry.supports)
        # Qualified ambiguous drug behavior cannot activate graph support.
        s = runtime_state()
        s.case.apply([runtime_fact(knowledge, HYPNOTIC), runtime_fact(knowledge, failed, polarity_scope='qualified')])
        self.assertTrue(use not in graph_candidates(s.case, knowledge) or not graph_candidates(s.case, knowledge)[use].entry.supports)


if __name__ == '__main__':
    unittest.main()
