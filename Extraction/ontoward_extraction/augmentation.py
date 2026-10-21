"""Augment the active static bundle without re-extracting registered knowledge."""
import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import unicodedata

from rdflib import RDF
from knowledge.graph import ClinicalKnowledge, OW
from .augmentation_models import Delta, Seed
from .compile import compile_bundle
from .maintenance import ROLES, read_parent, registered_concepts, relations, triple_rows
from .models import Concept, Relation, ValuePath, canonical, digest, identifier
from .verify import verify


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def nullable_hash(value):
    return None if value is None else digest(value)


def relation_hash(row):
    return digest([row.meaning(), row.effect])


@dataclass
class Parent:
    path: Path
    knowledge: ClinicalKnowledge
    manifest: dict
    graphs: dict
    questions: dict
    concepts: dict
    associations: dict
    value_paths: list
    pin: dict


def load_parent(path):
    path = Path(path).resolve()
    knowledge, manifest, graphs, questions = read_parent(path)
    knowledge.validate_vocabulary_endpoints()
    # Production loading is deliberately unconditional for augmentation.
    ClinicalKnowledge.load(path)
    nodes = registered_concepts(knowledge, questions['questions'], questions['attribute_roles'])
    paths = [ValuePath(observed=str(knowledge._one(node, OW.observedConcept)),
        expected=str(knowledge._one(node, OW.expectedConcept)),
        relation=knowledge._optional(node, OW.relationKind)).model_dump()
        for node in graphs['vocabulary'].subjects(RDF.type, OW.ValueMatch)]
    return Parent(path, knowledge, manifest, graphs, questions, {n['id']: n for n in nodes},
        {profile.association_id: row for profile, row in relations(knowledge)},
        sorted(paths, key=canonical),
        dict(build_id=manifest['build_id'], manifest_sha256=file_hash(path),
             assets={role: manifest[role]['sha256'] for role in ROLES}))


def check_parent(plan):
    parent = load_parent(plan['parent_manifest'])
    if parent.pin != plan['parent']:
        raise ValueError('active_parent_changed_create_new_plan')
    return parent


def unit_projection(knowledge):
    return {target + '|' + attribute: sorted(knowledge.numeric_units(target, attribute))
        for kind in ('Symptom', 'ExamFinding', 'ContextFactor', 'Disease')
        for target in sorted(map(str, knowledge._graph.subjects(RDF.type, OW[kind])))
        for attribute in knowledge.get_symptom_attributes(target)}


def implementation_pins(config):
    package = Path(__file__).parent
    from knowledge import graph as graph_module
    runtime = Path(graph_module.__file__).parent.parent
    runtime_files = [*Path(graph_module.__file__).parent.glob('*.py'),
        *(runtime / name for name in ('settings.py', 'workflow/rules/assessment.py', 'workflow/rules/questions.py',
            'workflow/rules/budget.py', 'workflow/state/evidence.py', 'workflow/state/models.py', 'workflow/text_config.py'))]
    return dict(generator={p.name: file_hash(p) for p in sorted(package.glob('*.py'))},
        prompts={p.name: file_hash(p) for p in sorted(Path(config['prompt_directory']).glob('augment_*.txt'))},
        runtime={p.relative_to(runtime).as_posix(): file_hash(p) for p in sorted(runtime_files)})


def local_catalog(parent, cluster, replacements):
    """Include complete local definitions, their relations, and owned references."""
    ids = set(cluster['target_ids']) | set(cluster['reference_ids'])
    lookup = {}
    needs = [dict(name=name, kind='Disease') for name in cluster['required_candidates']] + cluster['required_concepts']
    for need in needs:
        name, kind = need['name'], need['kind']
        exact = [i for i in parent.knowledge.resolve_concept(name) if parent.concepts.get(i, {}).get('kind') == kind]
        lexical = parent.knowledge.search_concepts(name, kind=kind)[:8]
        ids.update([*exact, *lexical])
        lookup[name] = dict(exact=exact, lexical_candidates=lexical,
            boundary='Lexical candidates require an explicit same-role semantic reuse decision')
    for target in list(ids):
        ids.update(row.disease_id for row in parent.associations.values() if row.target_id == target)
    selected = [(assoc, row) for assoc, row in parent.associations.items()
                if row.target_id in ids or row.disease_id in ids or assoc in replacements]
    for _, row in selected:
        ids.update([row.disease_id, row.target_id])
        ids.update(c.concept_id for c in row.applicability)
        for feature in row.features:
            if feature.attribute:
                ids.add(feature.attribute)
                ids.update([feature.expected.concept] if feature.expected.kind == 'concept' else feature.expected.concepts)
    pending = list(ids)
    while pending:
        node = parent.concepts[pending.pop()]
        links = [*node['attributes'], *node['values'], *node['systems']]
        if node['exam_method']:
            links.append(node['exam_method'])
        for ref in links:
            if ref not in ids:
                ids.add(ref)
                pending.append(ref)
    return dict(concepts=[parent.concepts[i] for i in sorted(ids)], lookup=lookup,
        relations=[dict(association_id=i, relation=r.model_dump()) for i, r in sorted(selected)],
        questions={k: v for k, v in parent.questions['questions'].items()
                   if all(i in ids for i in k.split('|'))})


def scope_for(parent, seed):
    ids = {i for c in seed['clusters'] for i in [*c['target_ids'], *c['reference_ids']]}
    ids.update(seed['extend_ids'])
    for ident in ids:
        if ident not in parent.concepts:
            raise ValueError('seed_reference_missing:' + ident)
    for cluster in seed['clusters']:
        if any(parent.concepts[i]['kind'] not in {'Symptom', 'ExamFinding', 'ContextFactor'} for i in cluster['target_ids']):
            raise ValueError('seed_target_role_mismatch')
    for assoc in seed['replace_association_ids']:
        if assoc not in parent.associations:
            raise ValueError('seed_replacement_missing:' + assoc)
    catalogs = {c['id']: local_catalog(parent, c, seed['replace_association_ids']) for c in seed['clusters']}
    local_ids = {n['id'] for catalog in catalogs.values() for n in catalog['concepts']}
    if any(i not in local_ids for i in seed['role_ids']):
        raise ValueError('seed_role_outside_local_scope')
    if any(not set(key.split('|')) <= local_ids for key in seed['question_keys']):
        raise ValueError('seed_question_outside_local_scope')
    return dict(local_ids=sorted(local_ids),
        extend_ids=sorted({i for c in seed['clusters'] for i in c['target_ids']} | set(seed['extend_ids'])),
        replace_association_ids=seed['replace_association_ids'],
        question_keys=seed['question_keys'], role_ids=seed['role_ids']), catalogs


def preconditions(parent):
    return dict(concepts={i: digest(v) for i, v in parent.concepts.items()},
        relations={i: relation_hash(v) for i, v in parent.associations.items()},
        questions={i: digest(v) for i, v in parent.questions['questions'].items()},
        roles={i: digest(v) for i, v in parent.questions['attribute_roles'].items()})


def validate_relations(nodes, rows, questions):
    for row in rows:
        if nodes.get(row.disease_id, {}).get('kind') != 'Disease' or nodes.get(row.target_id, {}).get('kind') not in {'Symptom', 'ExamFinding', 'ContextFactor'}:
            raise ValueError('invalid_relation_endpoint')
        target = nodes[row.target_id]
        if any(nodes.get(c.concept_id, {}).get('kind') != 'ContextFactor' for c in row.applicability):
            raise ValueError('invalid_applicability_endpoint')
        if len({canonical(c.model_dump()) for c in row.applicability}) != len(row.applicability):
            raise ValueError('duplicate_applicability')
        for feature in row.features:
            if not feature.attribute:
                continue
            if target['kind'] == 'ContextFactor':
                raise ValueError('context_target_cannot_have_attribute_condition')
            if feature.attribute not in target['attributes'] or nodes.get(feature.attribute, {}).get('kind') != 'FindingAttribute':
                raise ValueError('unregistered_target_attribute')
            expected = feature.expected
            values = [expected.concept] if expected.kind == 'concept' else expected.concepts
            if any(i not in nodes[feature.attribute]['values'] for i in values):
                raise ValueError('unregistered_attribute_value')
            if expected.kind in {'quantity', 'interval'}:
                contract = questions.get(row.target_id + '|' + feature.attribute, questions.get(feature.attribute))
                if contract and (expected.unit not in contract.get('units', []) or
                        expected.upper_unit and expected.upper_unit not in contract.get('units', [])):
                    raise ValueError('relation_question_unit_mismatch')


def apply_delta(parent, plan, delta):
    """Apply only explicit operations, checking every precondition against parent."""
    delta = Delta.model_validate(delta)
    pins, scope = plan['preconditions'], plan['scope']
    if parent.pin != plan['parent'] or preconditions(parent) != pins:
        raise ValueError('parent_precondition_mismatch')
    nodes = copy.deepcopy(parent.concepts)
    qs = copy.deepcopy(parent.questions)
    associations = dict(parent.associations)
    additions, replaced, touched_questions, touched_roles = [], set(), set(), set()
    added_ids, extended = set(), set()
    # Merge all new definitions and allowed append-only links before endpoint validation.
    for op in delta.operations:
        if op.op == 'add_concept':
            node = op.concept.model_dump()
            if node['id'] in parent.concepts:
                raise ValueError('add_concept_requires_new_identity')
            if node['id'] in nodes and nodes[node['id']] != node:
                raise ValueError('conflicting_new_concept')
            nodes[node['id']] = node
            added_ids.add(node['id'])
        elif op.op == 'extend_concept':
            if op.id not in scope['extend_ids'] or pins['concepts'].get(op.id) != op.before_hash:
                raise ValueError('extend_concept_precondition_mismatch')
            for key in ('aliases', 'attributes', 'values'):
                nodes[op.id][key] = sorted(set(nodes[op.id][key]) | set(getattr(op, key)))
            extended.add(op.id)
    limits = plan['seed']['limits']
    if len(added_ids) > limits['max_new_concepts'] or sum(nodes[i]['kind'] == 'Disease' for i in added_ids) > limits['max_new_diseases']:
        raise ValueError('new_concept_limit_exceeded')
    permitted = set(scope['local_ids']) | added_ids
    owners = {}
    for ident, node in nodes.items():
        Concept.model_validate(node)
        if ident in added_ids | extended:
            if node['kind'] == 'ContextFactor' and node['attributes']:
                raise ValueError('context_cannot_own_attributes')
            if node['values'] and node['kind'] != 'FindingAttribute':
                raise ValueError('invalid_value_owner')
            for field, kind in (('attributes', 'FindingAttribute'), ('values', 'AttributeValue')):
                if any(nodes.get(i, {}).get('kind') != kind for i in node[field]):
                    raise ValueError('invalid_vocabulary_endpoint')
                if any(i not in permitted for i in set(node[field]) - set(parent.concepts.get(ident, {}).get(field, []))):
                    raise ValueError('extension_outside_scope')
        for value in node['values']:
            owners.setdefault(value, set()).add(ident)
    for ident in added_ids:
        normalized = unicodedata.normalize('NFC', nodes[ident]['name']).strip().casefold()
        identity = ([next(iter(owners[ident])), normalized] if nodes[ident]['kind'] == 'AttributeValue'
                    and len(owners.get(ident, set())) == 1 else [nodes[ident]['kind'], normalized])
        if ident != identifier(nodes[ident]['kind'], identity):
            raise ValueError('new_identity_must_be_assigned_by_python')
        if nodes[ident]['kind'] == 'AttributeValue' and len(owners.get(ident, set())) != 1:
            raise ValueError('new_value_requires_exactly_one_owner')
        node = nodes[ident]
        if node['question']:
            qs['questions'][ident] = node['question']
        if node['attribute_role']:
            if node['kind'] != 'FindingAttribute':
                raise ValueError('role_requires_attribute')
            qs['attribute_roles'][ident] = node['attribute_role']
    # An existing value cannot silently acquire a different owner.
    for ident, node in parent.concepts.items():
        if node['kind'] == 'AttributeValue':
            before = {i for i, v in parent.concepts.items() if ident in v['values']}
            if owners.get(ident, set()) != before:
                raise ValueError('existing_value_ownership_changed')
    relation_ops = [op for op in delta.operations if op.op in {'add_relation', 'replace_relation'}]
    if len(relation_ops) > limits['max_new_relations']:
        raise ValueError('relation_limit_exceeded')
    for op in delta.operations:
        if op.op == 'set_question':
            parts = op.key.split('|')
            if len(parts) not in {1, 2} or any(i not in nodes for i in parts):
                raise ValueError('invalid_question_key')
            if op.key in touched_questions:
                raise ValueError('duplicate_question_operation')
            before = parent.questions['questions'].get(op.key)
            allowed = op.key in scope['question_keys'] or (before is None and set(parts) <= permitted and
                (parts[-1] in added_ids or len(parts) == 2 and parts[0] in scope['extend_ids']))
            if not allowed or nullable_hash(before) != op.before_hash:
                raise ValueError('question_precondition_mismatch')
            if len(parts) == 2 and (nodes[parts[-1]]['kind'] != 'FindingAttribute' or parts[-1] not in nodes[parts[0]]['attributes']):
                raise ValueError('question_override_requires_target_attribute')
            qs['questions'][op.key] = op.question.model_dump()
            touched_questions.add(op.key)
            if op.role:
                role = op.role
                if role.attribute_id != parts[-1] or nodes[role.attribute_id]['kind'] != 'FindingAttribute':
                    raise ValueError('role_question_attribute_mismatch')
                old = parent.questions['attribute_roles'].get(role.attribute_id)
                if (role.attribute_id not in added_ids and role.attribute_id not in scope['role_ids']
                        or nullable_hash(old) != role.before_hash):
                    raise ValueError('role_precondition_mismatch')
                value = role.value.model_dump()
                if role.attribute_id in touched_roles and qs['attribute_roles'][role.attribute_id] != value:
                    raise ValueError('conflicting_shared_role_changes')
                qs['attribute_roles'][role.attribute_id] = value
                touched_roles.add(role.attribute_id)
        elif op.op in {'add_relation', 'replace_relation'}:
            row = op.relation
            refs = {row.disease_id, row.target_id, *(c.concept_id for c in row.applicability)}
            if not refs <= permitted:
                raise ValueError('relation_outside_scope')
            if op.op == 'replace_relation':
                if (op.association_id not in scope['replace_association_ids'] or op.association_id in replaced
                        or pins['relations'].get(op.association_id) != op.before_hash):
                    raise ValueError('replacement_precondition_mismatch')
                if row.disease_id != parent.associations[op.association_id].disease_id:
                    raise ValueError('replacement_disease_changed')
                associations.pop(op.association_id)
                replaced.add(op.association_id)
            additions.append(row)
    if len(touched_questions) > limits['max_questions']:
        raise ValueError('question_limit_exceeded')
    merged, duplicates = {}, 0
    for row in [*associations.values(), *additions]:
        key = row.meaning()
        if key in merged:
            if merged[key].effect != row.effect:
                raise ValueError('effect_conflict_requires_explicit_replace')
            duplicates += 1
        else:
            merged[key] = row
    rows = list(merged.values())
    validate_relations(nodes, rows, qs['questions'])
    for ident, node in nodes.items():
        node['question'] = qs['questions'].get(ident)
        node['attribute_role'] = qs['attribute_roles'].get(ident)
    paths = {canonical(row): row for row in parent.value_paths}
    for row in delta.value_matches:
        if any(nodes.get(i, {}).get('kind') != 'AttributeValue' for i in (row.observed, row.expected)):
            raise ValueError('invalid_value_match_endpoint')
        if not {row.observed, row.expected} <= permitted:
            raise ValueError('value_match_outside_scope')
        paths[canonical(row.model_dump())] = row.model_dump()
    affected_roles = {i: sorted(n['id'] for n in nodes.values() if i in n['attributes']) for i in touched_roles}
    affected_questions = {key: sorted(n['id'] for n in nodes.values() if key in n['attributes'])
                          for key in touched_questions if '|' not in key and nodes[key]['kind'] == 'FindingAttribute'}
    return dict(concepts=list(nodes.values()), relations=[r.model_dump() for r in rows],
        value_paths=list(paths.values()), questions=qs,
        changes=dict(added_concepts=sorted(added_ids), extended_concepts=sorted(extended),
            replaced_associations=sorted(replaced),
            changed_parent_associations=sorted(op.association_id for op in delta.operations
                if op.op == 'replace_relation' and relation_hash(op.relation) != pins['relations'][op.association_id]),
            added_relations=sum(op.op == 'add_relation' for op in delta.operations),
            duplicate_relations_skipped=duplicates, neutral_relations=sum(r.effect == 'neutral' for r in rows),
            question_keys=sorted(touched_questions), role_impacts=affected_roles,
            global_question_impacts=affected_questions))


def compile_delta(parent, plan, delta, output):
    delta = Delta.model_validate(delta)
    applied = apply_delta(parent, plan, delta)
    build_id = digest(dict(plan=plan['plan_id'], delta=delta.model_dump()))[:32]
    destination = Path(output) / build_id
    if destination.exists():
        receipt = destination / 'augmentation.json'
        saved = json.loads(receipt.read_text()) if receipt.is_file() else {}
        if (saved.get('delta_hash') != digest(delta.model_dump())
                or file_hash(destination / 'manifest.json') != saved.get('bundle_manifest_sha256')):
            raise ValueError('immutable_augmentation_output_collision')
        verify(destination / 'manifest.json')
        check_parent(plan)
        return saved
    report = compile_bundle(destination, build_id, applied['concepts'], applied['relations'], applied['value_paths'],
        guidelines=parent.knowledge.guidelines.entries, schema_path=parent.path.parent / parent.manifest['schema']['path'],
        preserve_ids=True, question_overrides={k: v for k, v in applied['questions']['questions'].items() if '|' in k})
    coverage = verify(destination / 'manifest.json')
    child = load_parent(destination / 'manifest.json')
    if child.manifest['schema']['sha256'] != parent.manifest['schema']['sha256']:
        raise ValueError('schema_changed')
    if child.questions != applied['questions']:
        raise ValueError('question_or_role_preservation_failed')
    if child.knowledge.guidelines.entries != {**parent.knowledge.guidelines.entries,
            **{i: [] for i, n in child.concepts.items() if n['kind'] == 'Disease' and i not in parent.concepts}}:
        raise ValueError('guideline_payload_changed')
    expected = {(Relation.model_validate(r).meaning(), r['effect']) for r in applied['relations'] if r['effect'] != 'neutral'}
    if {(r.meaning(), r.effect) for r in child.associations.values()} != expected:
        raise ValueError('relation_preservation_failed')
    removed_vocab = set(parent.graphs['vocabulary']) - set(child.graphs['vocabulary'])
    if removed_vocab:
        raise ValueError('parent_vocabulary_triples_removed')
    units_before, units_after = unit_projection(parent.knowledge), unit_projection(child.knowledge)
    affected_units = set()
    for key in applied['changes']['question_keys']:
        affected_units.update([key] if '|' in key else [k for k in units_before if k.endswith('|' + key)])
    for assoc in applied['changes']['replaced_associations']:
        row = parent.associations[assoc]
        affected_units.update(row.target_id + '|' + f.attribute for f in row.features if f.attribute)
    for op in delta.operations:
        if op.op in {'add_relation', 'replace_relation'}:
            affected_units.update(op.relation.target_id + '|' + f.attribute for f in op.relation.features if f.attribute)
    changed_units = {k: dict(before=v, after=units_after.get(k)) for k, v in units_before.items() if units_after.get(k) != v}
    if set(changed_units) - affected_units:
        raise ValueError('unexplained_numeric_unit_change')
    if not delta.operations and (set(parent.graphs['vocabulary']) != set(child.graphs['vocabulary'])
            or set(parent.graphs['clinical']) != set(child.graphs['clinical']) or changed_units):
        raise ValueError('empty_delta_round_trip_changed_parent')
    # Recheck all original bytes, including the active manifest, after compilation.
    check_parent(plan)
    report.update(parent_build=parent.manifest['build_id'], delta_hash=digest(delta.model_dump()),
        bundle_manifest_sha256=child.pin['manifest_sha256'],
        plan_id=plan['plan_id'], changes=applied['changes'], coverage=coverage, installed=False,
        preservation=dict(parent_meanings_unauthorized_changes=0, parent_vocabulary_removed=0,
            questions_roles_exact=True, guideline_selections_equal=True, schema_equal=True,
            value_matches_preserved=len(parent.value_paths), unchanged_numeric_pairs=len(units_before) - len(changed_units),
            changed_numeric_units=changed_units, parent_files_hash_verified=True,
            empty_delta=not delta.operations, exact_empty_clinical_graph=(not delta.operations)),
        source_history_boundary='Reconstruct runtime knowledge only; historical neutral judgments and responses are unavailable')
    report['rdf_changes'] = {role: dict(added=triple_rows(set(child.graphs[role]) - set(parent.graphs[role])),
        removed=triple_rows(set(parent.graphs[role]) - set(child.graphs[role]))) for role in ('vocabulary', 'clinical')}
    (destination / 'augmentation.json').write_text(canonical(report) + '\n')
    return report


def make_plan(manifest, seed_path, config, output):
    parent = load_parent(manifest)
    seed = Seed.model_validate_json(Path(seed_path).read_bytes()).model_dump()
    if len({c['id'] for c in seed['clusters']}) != len(seed['clusters']):
        raise ValueError('duplicate_cluster_id')
    scope, catalogs = scope_for(parent, seed)
    plan = dict(version='augmentation-plan-1', parent_manifest=str(parent.path), parent=parent.pin,
        seed=seed, seed_hash=digest(seed), config=config, contracts=implementation_pins(config),
        scope=scope, preconditions=preconditions(parent), catalogs=catalogs,
        audit=dict(concepts=len(parent.concepts), associations=len(parent.associations),
            questions=len(parent.questions['questions']), roles=len(parent.questions['attribute_roles']),
            numeric_pairs=len(unit_projection(parent.knowledge)), value_paths=len(parent.value_paths)),
        workset_rules='discover -> concepts -> relations -> one final review -> questions; freeze each once',
        model_calls=0)
    plan['plan_id'] = digest(plan)[:32]
    root = Path(output) / plan['plan_id']
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'plan.json'
    if path.exists() and json.loads(path.read_text()) != plan:
        raise ValueError('immutable_plan_collision')
    # This gate must complete before a Provider can be constructed.
    baseline = compile_delta(parent, plan, Delta(), root / 'roundtrip')
    path.write_text(canonical(plan) + '\n')
    return dict(plan=str(path), run_id=plan['plan_id'], parent=parent.pin,
        roundtrip=baseline['preservation'], audit=plan['audit'], model_calls=0)


def read_plan(path, config=None):
    plan = json.loads(Path(path).read_text())
    identity = dict(plan)
    plan_id = identity.pop('plan_id')
    if plan.get('version') != 'augmentation-plan-1' or digest(identity)[:32] != plan_id:
        raise ValueError('invalid_augmentation_plan')
    selected = config or plan['config']
    if selected != plan['config'] or implementation_pins(selected) != plan['contracts']:
        raise ValueError('augmentation_config_or_contract_changed_create_new_plan')
    return plan, check_parent(plan)


def resolve_tasks(parent, tasks):
    """Resolve explicit reuse or assign local URIs from role/identity/owner only."""
    mapping, seen = {}, set()
    for task in tasks:
        if task.ref in seen:
            raise ValueError('duplicate_local_ref')
        seen.add(task.ref)
        if task.reuse_id:
            node = parent.concepts.get(task.reuse_id)
            if not node or node['kind'] != task.kind:
                raise ValueError('reuse_role_mismatch')
            mapping[task.ref] = task.reuse_id
        elif task.kind != 'AttributeValue':
            # Exact lookup catches accidental recreation; fuzzy hits never decide identity.
            hits = [i for i in parent.knowledge.resolve_concept(task.name) if parent.concepts[i]['kind'] == task.kind]
            if hits:
                raise ValueError('registered_exact_match_requires_explicit_reuse:' + task.name)
            name = unicodedata.normalize('NFC', task.name).strip().casefold()
            mapping[task.ref] = identifier(task.kind, [task.kind, name])
    for task in tasks:
        if task.kind == 'AttributeValue' and not task.reuse_id:
            owner = mapping.get(task.owner_ref, task.owner_ref)
            if owner.startswith('new:'):
                raise ValueError('unresolved_value_owner')
            mapping[task.ref] = identifier(task.kind, [owner, unicodedata.normalize('NFC', task.name).strip().casefold()])
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('ambiguous_new_identity_use_registered_ref')
    return mapping
