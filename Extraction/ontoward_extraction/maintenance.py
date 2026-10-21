"""Apply a pinned, reviewed offline correction to one installed v5 bundle."""
import hashlib
import json
from pathlib import Path

from rdflib import Graph, Literal, RDF, RDFS, SKOS, URIRef
from knowledge.conditions import AttributeRole, QuestionTemplate
from knowledge.graph import ClinicalKnowledge, Manifest, OW
from knowledge.guidelines import GuidelineLibrary
from .compile import compile_bundle
from .models import Concept, KINDS, Relation, ValuePath, canonical, digest, identifier
from .verify import verify

ROLES = ('schema', 'vocabulary', 'clinical', 'questions', 'guidelines')
TARGETS = {'Symptom', 'ExamFinding', 'ContextFactor'}


def read_parent(manifest_path):
    """Read a hash-verified maintenance input; production load remains strict."""
    path = Path(manifest_path).resolve()
    manifest = Manifest.model_validate_json(path.read_bytes())
    assets, paths = {}, set()
    for role in ROLES:
        entry = getattr(manifest, 'schema_asset' if role == 'schema' else role)
        relative = Path(entry.path)
        source = (path.parent / relative).resolve()
        if (relative.is_absolute() or '..' in relative.parts or not source.is_relative_to(path.parent)
                or source in paths or source == path or source.suffix != ('.ttl' if role in ROLES[:3] else '.json')):
            raise ValueError('invalid_parent_asset_path')
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise ValueError('parent_asset_digest_mismatch')
        paths.add(source)
        assets[role] = raw
    graphs = {role: Graph().parse(data=assets[role].decode('utf-8'), format='turtle') for role in ROLES[:3]}
    graph = Graph()
    for part in graphs.values():
        graph += part
    questions = json.loads(assets['questions'])
    if set(questions) != {'questions', 'attribute_roles'}:
        raise ValueError('invalid_parent_questions')
    knowledge = ClinicalKnowledge(graph,
        {key: QuestionTemplate.model_validate(value) for key, value in questions['questions'].items()},
        {key: AttributeRole.model_validate(value) for key, value in questions['attribute_roles'].items()})
    # Preserve every existing semantic check. Only the separately audited bad
    # vocabulary endpoints are permitted in this offline, explicitly pinned input.
    knowledge.validate_graph()
    knowledge.validate_question_assets()
    knowledge.prepare_terms()
    knowledge.guidelines = GuidelineLibrary.load(assets['guidelines'], manifest.build_id,
        {str(node) for node in graph.subjects(RDF.type, OW.Disease)})
    return knowledge, manifest.model_dump(by_alias=True), graphs, questions


def relations(knowledge):
    return [(profile, Relation(disease_id=profile.disease_id, target_id=profile.target,
        target_scope=profile.target_scope, applicability=profile.applicability, effect=profile.effect,
        features=[dict(status=f.status, attribute=f.attribute, expected=f.expected)
                  for f in knowledge.get_pattern_features(profile.id)]))
        for profiles in knowledge._disease_profiles.values() for profile in profiles]


def remap(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [remap(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: remap(item, mapping) for key, item in value.items()}
    return value


def question_projection(questions, mapping):
    result = {}
    # Retain the canonical question's wording when equivalent action contracts meet.
    for key in sorted(questions, key=lambda key: (any(part in mapping for part in key.split('|')), key)):
        new = '|'.join(mapping.get(part, part) for part in key.split('|'))
        value = questions[key]
        if new in result:
            if {k: v for k, v in value.items() if k != 'text'} != {k: v for k, v in result[new].items() if k != 'text'}:
                raise ValueError('question_contract_conflict:' + new)
        else:
            result[new] = value
    return result


def reviewed_mapping(knowledge, proposals, source_relations, questions):
    mapping, accepted, declined, claimed = {}, [], [], set()
    for proposal in proposals:
        members, canonical_id = proposal['members'], proposal['canonical']
        reason = None
        if (not proposal.get('same_role_meaning_verified') or not proposal.get('evidence')
                or canonical_id not in members or len(set(members)) != len(members) or len(members) < 2):
            reason = 'require_explicit_same_role_semantic_review'
        kinds = [{kind for kind in KINDS if knowledge.has_type(ident, kind)} for ident in members]
        if not kinds or any(len(kind) != 1 or not kind <= TARGETS for kind in kinds) or any(kind != kinds[0] for kind in kinds):
            reason = 'different_or_unsupported_roles'
        if claimed & set(members):
            reason = 'overlapping_merge_groups'
        if not reason and kinds[0] == {'ContextFactor'} and len({knowledge.get_context_type(ident) for ident in members}) != 1:
            reason = 'different_context_roles'
        if not reason and kinds[0] == {'ExamFinding'} and len({canonical(knowledge.get_exam_methods(ident)) for ident in members}) != 1:
            reason = 'different_examination_actions'
        tentative = {**mapping, **{ident: canonical_id for ident in members if ident != canonical_id}}
        if not reason:
            try:
                question_projection(questions, tentative)
                common_attributes = set.intersection(*(set(knowledge.get_symptom_attributes(ident)) for ident in members))
                for attribute in common_attributes:
                    contracts = [knowledge.question_contract(attribute, ident) for ident in members]
                    if len({canonical({key: value for key, value in contract.model_dump().items() if key != 'text'})
                            if contract else None for contract in contracts}) != 1:
                        raise ValueError('target_attribute_question_conflict:' + attribute)
            except ValueError as error:
                reason = str(error)
        conflicts = []
        if not reason:
            meanings = {}
            for _, row in source_relations:
                changed = Relation.model_validate(remap(row.model_dump(), tentative))
                meanings.setdefault(changed.meaning(), set()).add(changed.effect)
            conflicts = [dict(meaning=key, effects=sorted(effects)) for key, effects in meanings.items() if len(effects) > 1]
            if conflicts:
                reason = 'conflicting_effects_after_canonical_projection'
        if reason:
            declined.append(dict(proposal=proposal, reason=reason, conflicts=conflicts))
        else:
            mapping = tentative
            claimed.update(members)
            accepted.append(proposal)
    return mapping, accepted, declined


def project_graph(graph, mapping, *, vocabulary=False):
    result = Graph()
    for subject, predicate, value in graph:
        new_subject = URIRef(mapping.get(str(subject), str(subject))) if isinstance(subject, URIRef) else subject
        new_value = URIRef(mapping.get(str(value), str(value))) if isinstance(value, URIRef) else value
        if vocabulary and str(subject) in mapping and predicate == RDFS.label:
            result.add((new_subject, SKOS.altLabel, Literal(str(value))))
        else:
            result.add((new_subject, predicate, new_value))
    return result


def registered_concepts(knowledge, questions, roles):
    result, seen = [], set()
    for kind in KINDS:
        for subject in sorted(knowledge._graph.subjects(RDF.type, OW[kind]), key=str):
            ident = str(subject)
            if ident in seen:
                raise ValueError('ambiguous_registered_concept_role:' + ident)
            seen.add(ident)
            result.append(Concept(id=ident, kind=kind, name=knowledge.term(ident), korean=knowledge.label(ident),
                aliases=sorted(str(value) for value in knowledge._graph.objects(subject, SKOS.altLabel)),
                attributes=knowledge.get_symptom_attributes(ident),
                values=knowledge.get_attribute_values(ident) if kind == 'FindingAttribute' else [],
                systems=knowledge.get_symptom_systems(ident) if kind in {'Symptom', 'ExamFinding'} else [],
                context_type=knowledge._optional(subject, OW.contextType),
                exam_method=knowledge._optional(subject, OW.detectedBy), exam_text=knowledge._optional(subject, OW.examRequestText),
                question=questions.get(ident), attribute_role=roles.get(ident)).model_dump())
    return result


def clinical_identities(knowledge, source_relations, mapping):
    result = dict(mapping)
    for profile, relation in source_relations:
        changed = Relation.model_validate(remap(relation.model_dump(), mapping))
        features = sorted([feature.model_dump(exclude_none=True) for feature in changed.features], key=canonical)
        pattern = identifier('Pattern', [changed.target_id, features])
        result[profile.id] = pattern
        result[profile.association_id] = identifier('Association', changed.meaning())
        for old, feature in zip(knowledge.get_pattern_features(profile.id), changed.features):
            value = feature.model_dump(exclude_none=True)
            result[old.id] = identifier('Feature', [pattern, value])
            if feature.expected:
                expected = knowledge._one(URIRef(old.id), OW.expected)
                result[str(expected)] = identifier('Expected', value['expected'])
    return result


def triple_rows(triples):
    return sorted(' '.join(term.n3() for term in triple) + ' .' for triple in triples)


def correct_bundle(parent_path, plan_path, output):
    parent_path, plan_path = Path(parent_path), Path(plan_path)
    plan = json.loads(plan_path.read_text())
    if plan.get('version') != 'v5-maintenance-1':
        raise ValueError('unsupported_correction_plan')
    parent_pin = plan['parent']
    if hashlib.sha256(parent_path.read_bytes()).hexdigest() != parent_pin['manifest_sha256']:
        raise ValueError('parent_manifest_digest_mismatch')
    knowledge, manifest, graphs, questions = read_parent(parent_path)
    if manifest['build_id'] != parent_pin['build_id'] or any(manifest[role]['sha256'] != parent_pin['assets'][role] for role in ROLES):
        raise ValueError('parent_identity_mismatch')
    original_files = {str((parent_path.resolve().parent / manifest[role]['path']).resolve()): manifest[role]['sha256'] for role in ROLES}
    invalid = set()
    for predicate, domain, range_kind in ((OW.hasAttribute, None, 'FindingAttribute'), (OW.canHaveValue, 'FindingAttribute', 'AttributeValue')):
        for subject, target in graphs['vocabulary'].subject_objects(predicate):
            if (domain and not knowledge.has_type(str(subject), domain) or not knowledge.has_type(str(target), range_kind)):
                invalid.add((str(subject), str(predicate), str(target)))
    removals = {(row['subject'], row['predicate'], row['object']) for row in plan['remove_edges']}
    if removals != invalid or len(removals) != len(plan['remove_edges']):
        raise ValueError('corrections_must_enumerate_exactly_invalid_endpoint_edges')
    clean = Graph()
    clean += graphs['vocabulary']
    for subject, predicate, target in removals:
        clean.remove((URIRef(subject), URIRef(predicate), URIRef(target)))
    source_relations = relations(knowledge)
    mapping, accepted, declined = reviewed_mapping(knowledge, plan.get('merges', []), source_relations, questions['questions'])
    projected = project_graph(clean, mapping, vocabulary=True)
    working = ClinicalKnowledge(projected)
    projected_questions = question_projection(questions['questions'], mapping)
    nodes = registered_concepts(working, projected_questions, questions['attribute_roles'])
    changed_relations = [Relation.model_validate(remap(row.model_dump(), mapping)) for _, row in source_relations]
    identities = clinical_identities(knowledge, source_relations, mapping)
    expected_clinical = project_graph(graphs['clinical'], identities)
    paths = [ValuePath(observed=str(knowledge._one(subject, OW.observedConcept)),
        expected=str(knowledge._one(subject, OW.expectedConcept)), relation=knowledge._optional(subject, OW.relationKind)).model_dump()
        for subject in graphs['vocabulary'].subjects(RDF.type, OW.ValueMatch)]
    identity = dict(version=plan['version'], parent=parent_pin, plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        implementation={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('maintenance.py', 'compile.py', 'normalize.py', 'models.py')})
    build_id = digest(identity)[:32]
    destination = Path(output) / build_id
    if destination.exists():
        raise ValueError('maintenance_output_must_be_fresh')
    report = compile_bundle(destination, build_id, nodes, [row.model_dump() for row in changed_relations], paths,
        guidelines=knowledge.guidelines.entries,
        schema_path=parent_path.resolve().parent / manifest['schema']['path'], preserve_ids=True,
        question_overrides={key: value for key, value in projected_questions.items() if '|' in key})
    verified = verify(destination / 'manifest.json')
    rebuilt, new_manifest, new_graphs, new_questions = read_parent(destination / 'manifest.json')
    rebuilt.validate_vocabulary_endpoints()
    if set(new_graphs['vocabulary']) != set(projected):
        raise ValueError('unexplained_vocabulary_transition:' + canonical(dict(
            removed=triple_rows(set(projected)-set(new_graphs['vocabulary']))[:5], added=triple_rows(set(new_graphs['vocabulary'])-set(projected))[:5])))
    if set(new_graphs['clinical']) != set(expected_clinical):
        raise ValueError('clinical_graph_projection_mismatch')
    if new_questions != dict(questions=projected_questions, attribute_roles=questions['attribute_roles']):
        raise ValueError('question_or_attribute_role_projection_mismatch')
    before_meanings = {(row.meaning(), row.effect) for row in changed_relations}
    after_meanings = {(row.meaning(), row.effect) for _, row in relations(rebuilt)}
    if before_meanings != after_meanings:
        raise ValueError('clinical_meaning_or_effect_changed')
    if rebuilt.guidelines.entries != knowledge.guidelines.entries:
        raise ValueError('guideline_membership_or_sources_changed')
    for path, checksum in original_files.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != checksum:
            raise ValueError('parent_asset_changed')
    report.update(status='verified', identity=identity, parent_build=manifest['build_id'],
        parent_manifest=manifest, new_manifest=new_manifest, parent_files_preserved=len(original_files),
        coverage=verified, removed_invalid_edges=len(removals), accepted_merges=accepted,
        deferred=[*plan.get('deferred', []), *declined], canonical_mapping=mapping,
        graph_identity_changes={key: value for key, value in identities.items() if key != value},
        relations_before=len(source_relations), relations_after=len(after_meanings),
        exact_duplicate_relations_removed=len(source_relations)-len(after_meanings),
        canonical_relation_semantics_equal=True, exact_clinical_graph_projection_equal=True,
        exact_vocabulary_projection_equal=True, questions_roles_equal=True, guideline_sources_equal=True,
        rdf_changes={role: dict(removed=triple_rows(set(graphs[role])-set(new_graphs[role])),
            added=triple_rows(set(new_graphs[role])-set(graphs[role]))) for role in ('vocabulary', 'clinical')},
        removed_question_keys=sorted(set(questions['questions'])-set(projected_questions)),
        source_history_boundary='Reconstruct runtime meanings only; do not restore disposed extraction responses neutral judgments or source history',
        model_calls=0, installed=False)
    receipt = Path(output) / (build_id + '.correction.json')
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return dict(status=report['status'], parent_build=manifest['build_id'], build_id=build_id,
        manifest=str(destination / 'manifest.json'), receipt=str(receipt), removed_invalid_edges=len(removals),
        merged_nodes=len(mapping), deferred=len(report['deferred']), relations_before=len(source_relations),
        relations_after=len(after_meanings), model_calls=0, installed=False)
