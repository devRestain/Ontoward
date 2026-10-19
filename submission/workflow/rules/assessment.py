from dataclasses import dataclass, field
import hashlib

from knowledge.conditions import numeric_match

from ..state.evidence import EvidenceIndex
from ..state.models import DifferentialEntry, EvidenceRef, GraphRef, UnresolvedRef


@dataclass
class Candidate:
    disease_id: str
    entry: DifferentialEntry
    routes: set = field(default_factory=set)
    details: list = field(default_factory=list)


def scope_key(knowledge, target, attribute=None, base=None, chief=None, *, subject='patient', member=None, timing='current'):
    episode = base.episode_id if base else chief.episode_id if chief and subject == "patient" and timing == "current" and not knowledge.has_type(target, "ContextFactor") else None
    observation = base.observation_id if base else None
    if not observation and subject == 'patient' and not knowledge.has_type(target, 'ContextFactor'):
        observation = 'observation:' + hashlib.sha256(f'{target}:{episode}:current'.encode()).hexdigest()[:24]
    return ('EXAM' if knowledge.has_type(target, 'ExamFinding') else 'SAY', knowledge.term(target),
        knowledge.term(attribute) if attribute else '', base.subject if base else subject,
        (base.subject_member if base else member) or '', base.time_context if base else timing,
        observation or '', episode or '')


def unresolved_reason(interview, key):
    if interview:
        answer = next((a for a in reversed(interview.answers) if a.key == key and a.outcome != 'undelivered'), None)
        if answer:
            return answer.outcome
        return interview.collection.get('|'.join(key), 'unasked')
    return 'unasked'


def match_feature(knowledge, feature, bases, attributes):
    checks, refs = [], set()
    if feature.status:
        states = {b.status for b in bases}
        checks.append('matched' if states == {feature.status} else 'contradicted'
            if len(states) == 1 and states <= {'present', 'absent'} else 'unknown')
        refs.update(b.id for b in bases)
    if feature.expected:
        records = [a for a in attributes if a.attribute == feature.attribute]
        expected = feature.expected
        if expected.kind in {'quantity', 'interval'}:
            outcomes = [(numeric_match(expected, a.measurement), a.id) for a in records
                if a.status == 'present' and a.measurement]
            states = {status for status, _ in outcomes}
            result = next(iter(states)) if len(states) == 1 else 'unknown'
            refs.update(ident for _, ident in outcomes)
        else:
            concepts = [expected.concept] if expected.kind == 'concept' else expected.concepts
            outcomes = []
            for concept in concepts:
                matched = [a for a in records if any(knowledge.value_matches(v, concept,
                    hierarchy=expected.match == 'subsumption') for v in a.values)]
                states = {a.status for a in matched}
                outcomes.append('matched' if states == {'present'} else 'contradicted' if states == {'absent'} else 'unknown')
                refs.update(a.id for a in matched)
            if expected.kind == 'concept_set' and expected.selection == 'any_of':
                result = 'matched' if 'matched' in outcomes else 'contradicted' if set(outcomes) == {'contradicted'} else 'unknown'
            else:
                result = 'contradicted' if 'contradicted' in outcomes else 'matched' if set(outcomes) == {'matched'} else 'unknown'
        checks.append(result)
    status = 'contradicted' if 'contradicted' in checks else 'unknown' if not checks or 'unknown' in checks else 'matched'
    return status, tuple(sorted(refs))


def scope_matches(record, scope, *, status=None):
    if record.subject != scope.subject or scope.subject_member is not None and record.subject_member != scope.subject_member:
        return False
    if scope.subject == 'family' and scope.subject_member is None and status == 'absent' and record.subject_member is not None:
        return False
    return scope.time_context == 'any' or record.time_context == scope.time_context


def scoped_records(records, scope, status=None):
    return [record for record in records if scope_matches(record, scope, status=status)]


def applicability(conditions, contexts):
    refs, unknown = set(), False
    for condition in conditions:
        records = scoped_records([c for c in contexts if c.target == condition.concept_id], condition, condition.status)
        states = {c.status for c in records}
        refs.update(c.id for c in records)
        # A positive family-history rule can be established by one named member.
        if condition.subject == 'family' and condition.subject_member is None and condition.status == 'present':
            if any(c.status == 'present' for c in records):
                continue
            states = {c.status for c in records if c.subject_member is None}
        if len(states) == 1 and states <= {'present', 'absent'} and states != {condition.status}:
            return 'contradicted', tuple(sorted(refs))
        unknown |= states != {condition.status}
    return ('unknown' if unknown else 'matched'), tuple(sorted(refs))


def context_questions(knowledge, disease_ids):
    result = {}
    for disease in disease_ids:
        for profile in knowledge.get_disease_patterns(disease):
            rows = [(profile.target, profile.target_scope)] if knowledge.has_type(profile.target, 'ContextFactor') else []
            rows += [(condition.concept_id, condition) for condition in profile.applicability]
            for target, scope in rows:
                key = (target, scope.model_dump_json())
                result[key] = (target, scope)
    return sorted(result.values(), key=lambda row: (row[0], row[1].time_context == 'any', row[1].subject_member or '', row[1].time_context))


def graph_candidates(case, knowledge, interview=None):
    index = EvidenceIndex.from_case(case, knowledge)
    chief = next((e for e in index.entries if e.id == case.chief_fact_id), None)
    prior = {knowledge.term_id(entry.name, 'Disease') for entry in case.assessment.differential} if case.assessment else set()
    routes = {}
    for fact in index.entries:
        profiles = knowledge.get_patterns_by_target(fact.target)
        profiles += knowledge.associations_by_context.get(fact.target, [])
        for profile in profiles:
            positive = profile.effect in {'support', 'strong_support'}
            if not positive and profile.disease_id not in prior:
                continue
            target_path = fact.target == profile.target and scope_matches(fact, profile.target_scope)
            context_path = any(c.concept_id == fact.target and scope_matches(fact, c) for c in profile.applicability)
            if target_path or context_path:
                routes.setdefault(profile.disease_id, set()).add(fact.target)
    candidates = {}
    for disease, paths in sorted(routes.items()):
        supports, against, unresolved, details, whole = [], [], [], [], []
        for profile in knowledge.get_disease_patterns(disease):
            features = knowledge.get_pattern_features(profile.id)
            applies, context_refs = applicability(profile.applicability, index.contexts)
            groups = []
            for group in index.by_target.get(profile.target, ()):
                bases = scoped_records(group['base'], profile.target_scope)
                attributes = scoped_records(group['attributes'], profile.target_scope)
                if bases or attributes:
                    groups.append((bases, attributes))
            for bases, attributes in groups or [([], [])]:
                base = next(iter(bases or attributes), None)
                checks = [(feature, *match_feature(knowledge, feature,
                    scoped_records(bases, profile.target_scope, feature.status), attributes)) for feature in features]
                pattern_status = ('contradicted' if any(status == 'contradicted' for _,status,_ in checks) else
                    'incomplete' if any(status == 'unknown' for _,status,_ in checks) else 'matched')
                detail = dict(association=profile.association_id, pattern=profile.id, target=knowledge.term(profile.target),
                    effect=profile.effect, target_scope=profile.target_scope.model_dump(), applicability=applies,
                    conditions=[dict(name=knowledge.term(c.concept_id), **c.model_dump()) for c in profile.applicability],
                    features=[dict(id=f.id, attribute=knowledge.term(f.attribute) if f.attribute else None, expected_status=f.status,
                        expected=f.expected.model_dump(exclude_none=True) if f.expected else f.status,
                        status=status, fact_ids=refs) for f,status,refs in checks])
                details.append(detail)
                if applies == 'contradicted' or pattern_status == 'contradicted':
                    continue
                if applies == 'matched' and pattern_status == 'matched':
                    refs = tuple(sorted({ident for _,_,ids in checks for ident in ids} | set(context_refs)))
                    scope = (base.subject,base.subject_member,base.observation_id,base.episode_id,base.time_context) if base else ()
                    whole.append((profile, scope, EvidenceRef(graph_ref=GraphRef(kind='association', id=profile.association_id), fact_ids=refs)))
                    continue
                timing = knowledge.execution_time(profile.target, profile.target_scope)
                for feature, status, refs in checks:
                    if status != 'unknown':
                        continue
                    key = scope_key(knowledge, profile.target, feature.attribute, base, chief,
                        subject=profile.target_scope.subject, member=profile.target_scope.subject_member, timing=timing)
                    unresolved.append(UnresolvedRef(graph_ref=GraphRef(kind='feature', id=feature.id,
                        association_id=profile.association_id), fact_ids=refs, scope=key,
                        reason='applicability_unknown' if applies == 'unknown' else unresolved_reason(interview,key)))
                    if feature.attribute and not any(b.status == 'present' for b in bases):
                        presence_key = scope_key(knowledge, profile.target, base=base, chief=chief,
                            subject=profile.target_scope.subject, member=profile.target_scope.subject_member, timing=timing)
                        unresolved.append(UnresolvedRef(graph_ref=GraphRef(kind='association', id=profile.association_id,
                            association_id=profile.association_id), fact_ids=(), scope=presence_key, reason='presence_required'))
                if applies == 'unknown':
                    for condition in profile.applicability:
                        if applicability([condition], index.contexts)[0] != 'unknown':
                            continue
                        key = scope_key(knowledge, condition.concept_id, subject=condition.subject,
                            member=condition.subject_member, timing=knowledge.execution_time(condition.concept_id, condition))
                        unresolved.append(UnresolvedRef(graph_ref=GraphRef(kind='context', id=condition.concept_id,
                            association_id=profile.association_id), fact_ids=context_refs, scope=key,
                            reason='applicability_unknown'))
        refinement_groups = {}
        def refinement_key(profile, observation):
            return (profile.target_scope.model_dump_json(), profile.effect,
                    tuple(c.model_dump_json() for c in profile.applicability), observation)
        for profile, observation, ref in whole:
            refinement_groups.setdefault(refinement_key(profile, observation), []).append(profile)
        for profile, observation, ref in whole:
            if not any(knowledge.pattern_refines(other.id,profile.id)
                       for other in refinement_groups[refinement_key(profile, observation)]):
                (supports if profile.effect in {'support','strong_support'} else against).append(ref)
        def unique(rows):
            return tuple({row.model_dump_json():row for row in rows}.values())
        candidates[disease] = Candidate(disease, DifferentialEntry(kind='disease', name=knowledge.term(disease),
            supports=unique(supports), against=unique(against), unresolved=unique(unresolved)), paths, details)
    return candidates
