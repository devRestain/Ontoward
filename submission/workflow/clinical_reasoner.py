import hashlib
import json
from dataclasses import dataclass, field

from knowledge.conditions import numeric_match

from .state.models import Diagnosis
from .state.evidence import EvidenceIndex


@dataclass(frozen=True)
class Hypothesis:
    disease_id: str
    evidence_score: float = 0
    chief_score: float = 0
    context_bonus: int = 0
    contradiction_penalty: float = 0
    chief_coverage: float = 0
    evidence_ids: list = field(default_factory=list)
    contradiction_ids: list = field(default_factory=list)
    unresolved_conditions: list = field(default_factory=list)
    contradicted_conditions: list = field(default_factory=list)

    @property
    def score(self):
        return self.evidence_score + self.context_bonus - self.contradiction_penalty


@dataclass(frozen=True)
class PatternMatch:
    pattern_id: str
    observation_id: str
    episode_id: str
    time_context: str
    fingerprint: str
    status: str
    contradicted: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)


@dataclass(frozen=True)
class AssociationMatch:
    association_id: str
    pattern_key: str
    applicability: str
    evidence_ids: list


@dataclass(frozen=True)
class _Contribution:
    score: float
    evidence_ids: list


def fingerprint(items):
    return hashlib.sha256(json.dumps([i.signature() for i in sorted(items, key=lambda i:i.id)],
                                    sort_keys=True).encode()).hexdigest()


class ClinicalReasoner:
    def __init__(self, knowledge, audit=None):
        self.knowledge = knowledge
        self.audit = audit
        self._key = None
        self._snapshot = None

    def anchor(self, case, evidence=None):
        chief = case.chief(confirmed=True)
        evidence = evidence or EvidenceIndex.from_case(case, self.knowledge)
        return next((r for r in evidence.entries if chief and r.id == chief.id), None)

    def refresh_hypotheses(self, state, *, force=False):
        key = (state.case.revision, state.case.chief_fact_id)
        if not force and self._key == key and self._snapshot is not None:
            return self._snapshot
        evidence = EvidenceIndex.from_case(state.case, self.knowledge)
        previous = self._snapshot.pattern_matches if self._snapshot and not force else None
        self._snapshot = self.evaluate(evidence, self.anchor(state.case, evidence), previous=previous)
        self._key = key
        return self._snapshot

    def clear(self):
        self._key, self._snapshot = None, None

    def evaluate_delta(self, snapshot, evidence_patch):
        changed = [item for item in evidence_patch]
        replaced = {item.id for item in changed}
        changed += [item for item in snapshot.evidence.raw if item.id in replaced]
        affected = set()
        for item in changed:
            value = item
            for target in (value.target,):
                if value.kind == "context":
                    affected.update(p.disease_id for p in self.knowledge.associations_by_context.get(
                        (target, value.subject, value.time_context), []))
                    affected.update(self.knowledge.diseases_by_supporting_context.get((target, value.subject), set()))
                else:
                    affected.update(p.disease_id for p in self.knowledge.get_patterns_by_target(target))
        evidence = snapshot.evidence.patch(evidence_patch)
        return self.evaluate(evidence, snapshot.chief, snapshot.policy, previous=snapshot.pattern_matches,
                             prior=snapshot, affected=affected)

    def evaluate(self, evidence_index, chief_anchor, policy=None, *, previous=None, prior=None, affected=None):
        policy = policy or self.knowledge.reasoning
        groups, contexts = evidence_index.groups, evidence_index.contexts
        previous = previous or {}
        prior_associations = {(a.association_id, a.pattern_key): a for a in prior.association_matches} if prior else {}
        evaluations = 0
        evaluated, associations, by_disease, diseases = {}, [], {}, set()
        present_targets = {c for group in groups.values() for item in group["base"]
                           if item.status == "present" for c in (item.target,)}
        chiefs = {(chief_anchor.observation_id, chief_anchor.episode_id, chief_anchor.target,
                   chief_anchor.time_context)} if chief_anchor else set()
        chief_episodes = {episode for _, episode, _, _ in chiefs}
        context_index = {}
        for item in contexts:
            for concept in (item.target,):
                key = (concept, item.subject, item.time_context)
                context_index.setdefault(key, []).append(item)
        applicability_cache = {}
        for (observation, episode, timing), group in groups.items():
            targets = {c for item in group["base"] for c in (item.target,)}
            group_signature = fingerprint(group["base"] + group["attributes"])
            for target in sorted(targets):
                bases = [item for item in group["base"] if target in (item.target,)]
                if any(item.status in {"present", "uncertain"} for item in bases):
                    diseases.update(p.disease_id for p in self.knowledge.get_patterns_by_target(target))
                statuses = {item.status for item in bases}
                status = next(iter(statuses)) if len(statuses) == 1 and all(len((item.target,)) == 1 for item in bases) else "uncertain"
                for pattern in self.knowledge.get_target_patterns(target):
                    key = json.dumps([pattern, observation, episode, timing], separators=(",", ":"))
                    result = previous.get(key)
                    features = self.knowledge.get_pattern_features(pattern)
                    if result is None or result.fingerprint != group_signature:
                        checks = [(feature.id, *self._match(feature, target, status, bases, group["attributes"])) for feature in features]
                        contradicted = [fid for fid, check, _ in checks if check == "contradicted"]
                        unresolved = [fid for fid, check, _ in checks if check == "unknown"]
                        result = PatternMatch(pattern_id=pattern, observation_id=observation, episode_id=episode,
                            time_context=timing, fingerprint=group_signature,
                            status="contradicted" if contradicted else "incomplete" if unresolved else "matched",
                            contradicted=contradicted, unresolved=unresolved,
                            evidence_ids=sorted({ref for _, _, refs in checks for ref in refs} | {i.id for i in bases}))
                        evaluations += 1
                    evaluated[key] = result
                    for profile in self.knowledge.get_pattern_associations(pattern):
                        if affected is not None and profile.disease_id not in affected:
                            unchanged = prior_associations.get((profile.association_id, key))
                            if unchanged is not None:
                                associations.append(unchanged)
                                continue
                        if profile.association_id not in applicability_cache:
                            applicability_cache[profile.association_id] = self._applicability(profile.applicability, context_index)
                        applies, refs = applicability_cache[profile.association_id]
                        associations.append(AssociationMatch(association_id=profile.association_id, pattern_key=key,
                                                            applicability=applies, evidence_ids=refs))
                        by_disease.setdefault(profile.disease_id, []).append((profile, result, applies, refs, bases))
        hypotheses = [h for h in prior.hypotheses if h.disease_id in diseases and h.disease_id not in affected] if prior else []
        for disease in sorted(diseases if affected is None else diseases & affected):
            rows = by_disease.get(disease, [])
            complete = {}
            for profile, result, applies, refs, _ in rows:
                if result.status == "matched" and applies == "matched":
                    key = (result.observation_id, result.episode_id, profile.target, result.time_context)
                    complete.setdefault(key, []).append((profile, result, refs))
            contributions, covered = {}, set()
            chief_contribution = None
            for (observation, episode, target, timing), matches in complete.items():
                maximal = [item for item in matches if not any(
                    self.knowledge.pattern_refines(other[0].id, item[0].id) for other in matches)]
                for profile, result, context_refs in sorted(maximal, key=lambda item: (-item[0].score, item[0].association_id)):
                    is_chief = (observation, episode, target, timing) in chiefs
                    if is_chief and profile.score > 0:
                        covered.add((observation, episode, target))
                    if is_chief or target not in contributions or profile.score > contributions[target].score:
                        contribution = _Contribution(score=profile.score,
                            evidence_ids=sorted(set(result.evidence_ids) | set(context_refs)))
                        if is_chief:
                            if chief_contribution is None or contribution.score > chief_contribution.score:
                                chief_contribution = contribution
                        elif not chief_anchor or target != chief_anchor.target:
                            contributions[target] = contribution
            penalties, negative_refs = {}, set()
            for profile, result, applies, _, bases in rows:
                features = self.knowledge.get_pattern_features(profile.id)
                if (applies != "matched" or result.status != "contradicted" or profile.target in present_targets
                        or result.episode_id not in chief_episodes or not all(f.status == "present" and not f.expected for f in features)
                        or not bases or not all(i.status == "absent" and i.time_context == "current"
                                               and i.polarity_scope == "general" for i in bases)):
                    continue
                penalty = policy.absence_penalties.get(profile.typicality, 0)
                if penalty:
                    penalties[profile.target] = max(penalties.get(profile.target, 0), min(policy.per_target_cap, penalty))
                    negative_refs.update(i.id for i in bases)
            supporting = {item["id"]: item["type"] for item in self.knowledge.get_supporting_context(disease)}
            context_refs = [item.id for item in contexts if item.status == "present" and any(
                concept in supporting and (supporting[concept] == "family_history") == (item.subject == "family")
                for concept in (item.target,))]
            context_bonus = int(bool(context_refs))
            selected = list(contributions.values())
            auxiliary = sum(c.score for c in selected)
            chief_score = chief_contribution.score if chief_contribution else 0
            if chief_contribution:
                selected.append(chief_contribution)
            hypotheses.append(Hypothesis(disease_id=disease,
                evidence_score=chief_score + min(policy.supporting_cap, auxiliary), chief_score=chief_score,
                context_bonus=context_bonus,
                contradiction_penalty=min(policy.total_cap, sum(penalties.values())),
                contradiction_ids=sorted(negative_refs), chief_coverage=len(covered) / len(chiefs) if chiefs else 0,
                unresolved_conditions=sorted({fid for _, result, _, _, _ in rows for fid in result.unresolved}
                    | {condition.concept_id for p, _, applies, _, _ in rows if applies == "unknown" for condition in p.applicability}),
                contradicted_conditions=sorted({fid for _, result, _, _, _ in rows for fid in result.contradicted}
                    | {condition.concept_id for p, _, applies, _, _ in rows if applies == "contradicted" for condition in p.applicability}),
                evidence_ids=sorted({ref for c in selected if c.score > 0 for ref in c.evidence_ids} | set(context_refs))))
        hypotheses.sort(key=lambda h: (-h.score, -h.chief_score, len(h.contradicted_conditions), h.disease_id))
        return ReasoningSnapshot(evidence_index, chief_anchor, policy, tuple(hypotheses), evaluated,
                                 tuple(associations), evaluations)

    @staticmethod
    def _applicability(conditions, index):
        refs, unknown = [], False
        for condition in conditions:
            records = index.get((condition.concept_id, condition.subject, condition.time_context), [])
            statuses = {item.status for item in records}
            if len(statuses) == 1 and statuses <= {"present", "absent"} and statuses != {condition.status}:
                return "contradicted", [i.id for i in records]
            if statuses != {condition.status}:
                unknown = True
            refs.extend(i.id for i in records)
        return ("unknown" if unknown else "matched"), refs

    def _match(self, feature, target, status, bases, attributes):
        checks, refs = [], []
        if feature.status:
            checks.append("unknown" if status not in {"present", "absent"} else
                          "matched" if status == feature.status else "contradicted")
            refs.extend(item.id for item in bases)
        if feature.expected:
            records = [item for item in attributes if item.attribute == feature.attribute
                       and (item.target,) == (target,)]
            expected = feature.expected
            if expected.kind in {"quantity", "interval"}:
                outcomes = [(numeric_match(expected, item.measurement), item.id) for item in records
                            if item.status == "present" and item.measurement]
                states = {result for result, _ in outcomes}
                result = next(iter(states)) if len(states) == 1 else "unknown"
                refs.extend(ref for result, ref in outcomes if result == "matched")
            else:
                concepts = [expected.concept] if expected.kind == "concept" else expected.concepts
                outcomes = []
                for concept in concepts:
                    matching = [item for item in records if any(self.knowledge.value_matches(v, concept,
                                hierarchy=expected.match == "subsumption") for v in item.values)]
                    states = {item.status for item in matching}
                    outcomes.append("matched" if states == {"present"} else "contradicted" if states == {"absent"} else "unknown")
                    refs.extend(item.id for item in matching if item.status == "present")
                if expected.kind == "concept_set" and expected.selection == "any_of":
                    result = "matched" if "matched" in outcomes else "contradicted" if set(outcomes) == {"contradicted"} else "unknown"
                else:
                    result = "matched" if set(outcomes) == {"matched"} else "contradicted" if "contradicted" in outcomes else "unknown"
            checks.append(result)
        if "contradicted" in checks:
            return "contradicted", refs
        if not checks or "unknown" in checks:
            return "unknown", []
        return "matched", refs


    @staticmethod
    def supported_hypotheses(snapshot):
        return [h for h in snapshot.hypotheses if h.evidence_score > 0 and h.score > 0 and h.chief_coverage == 1]

    def select_diagnosis(self, state):
        if state.case.diagnosis:
            return
        supported = self.supported_hypotheses(self.refresh_hypotheses(state))
        if supported:
            selected = supported[0]
            state.case.diagnosis = Diagnosis(kind='disease', name=self.knowledge.term(selected.disease_id),
                evidence_ids=tuple(sorted(set(selected.evidence_ids + selected.contradiction_ids))))
        else:
            chief = state.case.chief(confirmed=True)
            if chief is None:
                state.stop('failed', 'no_supported_diagnosis')
            else:
                state.case.diagnosis = Diagnosis(kind='symptom', name=chief.target, evidence_ids=(chief.id,))


@dataclass(frozen=True)
class ReasoningSnapshot:
    evidence: EvidenceIndex
    chief: object
    policy: object
    hypotheses: tuple
    pattern_matches: dict
    association_matches: tuple
    evaluations: int
