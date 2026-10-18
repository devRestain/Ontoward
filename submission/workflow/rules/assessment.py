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
    episode = base.episode_id if base else chief.episode_id if chief else None
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


def applicability(conditions, contexts):
    refs, unknown = set(), False
    for condition in conditions:
        records = [c for c in contexts if (c.target, c.subject, c.time_context) ==
            (condition.concept_id, condition.subject, condition.time_context)]
        states = {c.status for c in records}
        refs.update(c.id for c in records)
        if len(states) == 1 and states <= {'present', 'absent'} and states != {condition.status}:
            return 'contradicted', tuple(sorted(refs))
        unknown |= states != {condition.status}
    return ('unknown' if unknown else 'matched'), tuple(sorted(refs))


def graph_candidates(case, knowledge, interview=None):
    index = EvidenceIndex.from_case(case, knowledge)
    chief = next((e for e in index.entries if e.id == case.chief_fact_id), None)
    routes = {}
    for fact in index.entries:
        if fact.kind == 'context':
            diseases = {p.disease_id for p in knowledge.associations_by_context.get(
                (fact.target, fact.subject, fact.time_context), ())}
            diseases.update(knowledge.diseases_by_supporting_context.get((fact.target, fact.subject), ()))
        elif fact.subject == 'patient' and fact.time_context != 'past':
            diseases = {p.disease_id for p in knowledge.get_patterns_by_target(fact.target)}
        else:
            continue
        for disease in diseases:
            routes.setdefault(disease, set()).add(fact.target)
    candidates, matched_cache, applies_cache = {}, {}, {}
    for disease, paths in sorted(routes.items()):
        supports, against, unresolved, details, whole = [], [], [], [], []
        profiles = knowledge.get_disease_patterns(disease)
        feature_index = {f.id:f for p in profiles for f in knowledge.get_pattern_features(p.id)}
        for profile in profiles:
            features = knowledge.get_pattern_features(profile.id)
            applies, context_refs = applies_cache.setdefault(profile.association_id,
                applicability(profile.applicability, index.contexts))
            groups = [g for g in index.groups.values() if any(b.target == profile.target for b in g['base'])]
            for group in groups or [{'base': [], 'attributes': []}]:
                bases = [b for b in group['base'] if b.target == profile.target]
                attributes = [a for a in group['attributes'] if a.target == profile.target]
                base = bases[0] if bases else None
                checks = []
                for feature in features:
                    cache_key = (feature.id, tuple(b.id for b in bases), tuple(a.id for a in attributes))
                    if cache_key not in matched_cache:
                        matched_cache[cache_key] = match_feature(knowledge, feature, bases, attributes)
                    status, refs = matched_cache[cache_key]
                    key = scope_key(knowledge, profile.target, feature.attribute, base, chief)
                    ref = GraphRef(kind='feature', id=feature.id, association_id=profile.association_id)
                    checks.append((feature, status, refs, key, ref))
                pattern_status = ('contradicted' if any(c[1] == 'contradicted' for c in checks) else
                    'incomplete' if any(c[1] == 'unknown' for c in checks) else 'matched')
                details.append(dict(association=profile.association_id, pattern=profile.id,
                    target=knowledge.term(profile.target), applicability=applies,
                    conditions=[dict(name=knowledge.term(condition.concept_id),**condition.model_dump())
                        for condition in profile.applicability],
                    features=[dict(id=f.id, attribute=knowledge.term(f.attribute) if f.attribute else None,
                        expected=f.expected.model_dump(exclude_none=True) if f.expected else f.status,
                        status=status, fact_ids=refs) for f,status,refs,_,_ in checks]))
                if applies == 'matched' and pattern_status == 'matched':
                    refs = tuple(sorted({i for _,_,ids,_,_ in checks for i in ids} | set(context_refs)))
                    whole.append((profile, (base.subject,base.subject_member,base.observation_id,base.episode_id,base.time_context) if base else (), EvidenceRef(
                        graph_ref=GraphRef(kind='association', id=profile.association_id), fact_ids=refs)))
                else:
                    for _, status, refs, key, ref in checks:
                        if applies == 'matched' and status != 'unknown':
                            (supports if status == 'matched' else against).append(EvidenceRef(graph_ref=ref, fact_ids=refs))
                        elif applies != 'contradicted':
                            unresolved.append(UnresolvedRef(graph_ref=ref, fact_ids=refs, scope=key,
                                reason='applicability_unknown' if applies == 'unknown' else unresolved_reason(interview, key)))
                if applies == 'unknown':
                    for condition in profile.applicability:
                        key = scope_key(knowledge, condition.concept_id, chief=None,
                            subject=condition.subject, timing=condition.time_context)
                        unresolved.append(UnresolvedRef(graph_ref=GraphRef(kind='context', id=condition.concept_id,
                            association_id=profile.association_id), fact_ids=context_refs, scope=key,
                            reason=unresolved_reason(interview, key)))
        for profile, scopes, ref in whole:
            if not any(other.applicability == profile.applicability and other_scopes == scopes
                and knowledge.pattern_refines(other.id, profile.id) for other,other_scopes,_ in whole):
                supports.append(ref)
        for context in knowledge.get_supporting_context(disease):
            subject = 'family' if context['type'] == 'family_history' else 'patient'
            records = [r for r in index.contexts if r.target == context['id'] and r.subject == subject]
            if records and {r.status for r in records} == {'present'}:
                supports.append(EvidenceRef(graph_ref=GraphRef(kind='context', id=context['id']),
                    fact_ids=tuple(sorted(r.id for r in records))))
            elif not records or any(r.status in {'unknown', 'uncertain'} for r in records):
                key = scope_key(knowledge, context['id'], subject=subject, timing='unspecified')
                unresolved.append(UnresolvedRef(graph_ref=GraphRef(kind='context', id=context['id']),
                    fact_ids=tuple(sorted(r.id for r in records)), scope=key, reason=unresolved_reason(interview, key)))
        def unique(refs):
            result, seen = [], set()
            for ref in refs:
                graph = ref.graph_ref
                if graph.kind == 'feature':
                    feature = feature_index[graph.id]
                    meaning = ('feature', str(feature.signature()))
                elif graph.kind == 'association':
                    profile = next(p for p in knowledge.get_disease_patterns(disease) if p.association_id == graph.id)
                    meaning = ('association', profile.id, str(profile.applicability))
                else:
                    meaning = (graph.kind, graph.id, graph.association_id)
                key = (meaning, ref.fact_ids, getattr(ref, 'scope', ()))
                if key not in seen:
                    seen.add(key); result.append(ref)
            return tuple(result)
        candidates[disease] = Candidate(disease, DifferentialEntry(kind='disease', name=knowledge.term(disease),
            supports=unique(supports), against=unique(against), unresolved=unique(unresolved)), paths, details)
    return candidates
