import hashlib
import json
from dataclasses import dataclass

from knowledge.conditions import numeric_match
from knowledge.graph import ClinicalKnowledge

from .state.models import AssociationMatch, ChiefAnchor, Hypothesis, PatternMatch, ScoreContribution, WorkflowState
from .state.evidence import EvidenceIndex


def fingerprint(items):
    values = [(item.id, item.value.model_dump(exclude={"text", "record_category", "record_details"}))
              for item in sorted(items, key=lambda i: i.id)]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ClinicalReasoner:
    def __init__(self, knowledge: ClinicalKnowledge):
        self.knowledge = knowledge

    def retrieve_candidates(self, state):
        state.differential.initialized = True
        self.refresh_hypotheses(state)

    @staticmethod
    def anchor(case):
        chief = case.chief(confirmed=True)
        if chief is None or len(chief.value.concept_ids) != 1:
            return None
        return ChiefAnchor(record_id=chief.id, target_id=chief.value.concept_ids[0],
            observation_id=chief.value.observation_id or chief.id, episode_id=chief.value.episode_id or chief.id,
            time_context=chief.value.time_context)

    def refresh_hypotheses(self, state, *, force=False):
        if state.case.fixed_diagnosis or not state.differential.initialized:
            return
        state.case.select_primary()
        evidence, chief = EvidenceIndex.from_case(state.case), self.anchor(state.case)
        signature = evidence.fingerprint + (chief.model_dump_json() if chief else "")
        differential = state.differential
        if not force and signature == differential.last_fingerprint:
            return
        if signature != differential.last_fingerprint and differential.last_scored_revision == differential.clinical_revision:
            differential.clinical_revision += 1
        snapshot = self.evaluate(evidence, chief, previous=None if force else differential.pattern_matches)
        differential.hypotheses = list(snapshot.hypotheses)
        differential.pattern_matches = snapshot.pattern_matches
        differential.association_matches = list(snapshot.association_matches)
        differential.pattern_evaluations += snapshot.evaluations
        differential.refreshes += 1
        differential.last_fingerprint = signature
        differential.last_scored_revision = differential.clinical_revision

    def evaluate_delta(self, snapshot, evidence_patch):
        changed = [item for _, item in evidence_patch]
        replaced = {item.id for item in changed}
        changed += [item for _, item in snapshot.evidence.raw if item.id in replaced]
        affected = set()
        for item in changed:
            value = item.value
            if value is None:
                continue
            for target in value.concept_ids:
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
                           if item.value.status == "present" for c in item.value.concept_ids}
        chiefs = {(chief_anchor.observation_id, chief_anchor.episode_id, chief_anchor.target_id,
                   chief_anchor.time_context)} if chief_anchor else set()
        chief_episodes = {episode for _, episode, _, _ in chiefs}
        context_index = {}
        for item in contexts:
            for concept in item.value.concept_ids:
                key = (concept, item.value.subject, item.value.time_context)
                context_index.setdefault(key, []).append(item)
        applicability_cache = {}
        for (observation, episode, timing), group in groups.items():
            targets = {c for item in group["base"] for c in item.value.concept_ids}
            group_signature = fingerprint(group["base"] + group["attributes"])
            for target in sorted(targets):
                bases = [item for item in group["base"] if target in item.value.concept_ids]
                if any(item.value.status in {"present", "uncertain"} for item in bases):
                    diseases.update(p.disease_id for p in self.knowledge.get_patterns_by_target(target))
                statuses = {item.value.status for item in bases}
                status = next(iter(statuses)) if len(statuses) == 1 and all(len(item.value.concept_ids) == 1 for item in bases) else "uncertain"
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
                            matched=[fid for fid, check, _ in checks if check == "matched"],
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
            contributions, covered, incomparable = {}, set(), []
            chief_contribution = None
            for (observation, episode, target, timing), matches in complete.items():
                maximal = [item for item in matches if not any(
                    self.knowledge.pattern_refines(other[0].id, item[0].id) for other in matches)]
                if len(maximal) > 1:
                    incomparable.append(sorted(p.association_id for p, _, _ in maximal))
                for profile, result, context_refs in sorted(maximal, key=lambda item: (-item[0].score, item[0].association_id)):
                    is_chief = (observation, episode, target, timing) in chiefs
                    if is_chief and profile.score > 0:
                        covered.add((observation, episode, target))
                    if is_chief or target not in contributions or profile.score > contributions[target].score:
                        matched_ids = {p.association_id for p, _, _ in matches}
                        contribution = ScoreContribution(
                            association_id=profile.association_id, pattern_id=profile.id, target_id=target,
                            score=profile.score, evidence_ids=sorted(set(result.evidence_ids) | set(context_refs)),
                            weight_basis=profile.weight_basis, policy_version=self.knowledge.policy.version,
                            feature_deltas=[c for c in self.knowledge.get_feature_contributions(profile.association_id)
                                            if c.baseline_association in matched_ids])
                        if is_chief:
                            if chief_contribution is None or contribution.score > chief_contribution.score:
                                chief_contribution = contribution
                        elif not chief_anchor or target != chief_anchor.target_id:
                            contributions[target] = contribution
            penalties, negative_refs = {}, set()
            for profile, result, applies, _, bases in rows:
                features = self.knowledge.get_pattern_features(profile.id)
                if (applies != "matched" or result.status != "contradicted" or profile.target in present_targets
                        or result.episode_id not in chief_episodes or not all(f.status == "present" and not f.expected for f in features)
                        or not bases or not all(i.value.status == "absent" and i.value.time_context == "current"
                                               and i.value.polarity_scope == "general" for i in bases)):
                    continue
                penalty = policy.absence_penalties.get(profile.typicality, 0)
                if penalty:
                    penalties[profile.target] = max(penalties.get(profile.target, 0), min(policy.per_target_cap, penalty))
                    negative_refs.update(i.id for i in bases)
            supporting = {item["id"]: item["type"] for item in self.knowledge.get_supporting_context(disease)}
            context_refs = [item.id for item in contexts if item.value.status == "present" and any(
                concept in supporting and (supporting[concept] == "family_history") == (item.value.subject == "family")
                for concept in item.value.concept_ids)]
            context_bonus = int(bool(context_refs))
            selected = list(contributions.values())
            auxiliary = sum(c.score for c in selected)
            chief_score = chief_contribution.score if chief_contribution else 0
            if chief_contribution:
                selected.append(chief_contribution)
            hypotheses.append(Hypothesis(disease_id=disease,
                pattern_ids=sorted({p.id for p, *_ in rows}), association_ids=sorted({p.association_id for p, *_ in rows}),
                feature_ids=sorted({f.id for p, *_ in rows for f in self.knowledge.get_pattern_features(p.id)}),
                evidence_score=chief_score + min(policy.supporting_cap, auxiliary), chief_score=chief_score,
                supporting_raw=auxiliary, supporting_score=min(policy.supporting_cap, auxiliary),
                context_bonus=context_bonus, contributions=selected,
                contradiction_penalty=min(policy.total_cap, sum(penalties.values())),
                contradiction_ids=sorted(negative_refs), chief_coverage=len(covered) / len(chiefs) if chiefs else 0,
                unresolved_conditions=sorted({fid for _, result, _, _, _ in rows for fid in result.unresolved}
                    | {condition.concept_id for p, _, applies, _, _ in rows if applies == "unknown" for condition in p.applicability}),
                contradicted_conditions=sorted({fid for _, result, _, _, _ in rows for fid in result.contradicted}
                    | {condition.concept_id for p, _, applies, _, _ in rows if applies == "contradicted" for condition in p.applicability}),
                potential_patterns=sorted({p.id for p, r, a, _, _ in rows if r.status == "incomplete" or a == "unknown"}),
                incomparable_matches=incomparable,
                evidence_ids=sorted({ref for c in selected if c.score > 0 for ref in c.evidence_ids} | set(context_refs))))
        hypotheses.sort(key=lambda h: (-h.score, -h.chief_score, len(h.contradicted_conditions), h.disease_id))
        return ReasoningSnapshot(evidence_index, chief_anchor, policy, tuple(hypotheses), evaluated,
                                 tuple(associations), evaluations)

    @staticmethod
    def _applicability(conditions, index):
        refs, unknown = [], False
        for condition in conditions:
            records = index.get((condition.concept_id, condition.subject, condition.time_context), [])
            statuses = {item.value.status for item in records}
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
            records = [item for item in attributes if item.value.attribute_id == feature.attribute
                       and item.value.concept_ids == [target]]
            expected = feature.expected
            if expected.kind in {"quantity", "interval"}:
                outcomes = [(numeric_match(expected, item.value.measurement), item.id) for item in records
                            if item.value.status == "present" and item.value.measurement]
                states = {result for result, _ in outcomes}
                result = next(iter(states)) if len(states) == 1 else "unknown"
                refs.extend(ref for result, ref in outcomes if result == "matched")
            else:
                concepts = [expected.concept] if expected.kind == "concept" else expected.concepts
                outcomes = []
                for concept in concepts:
                    matching = [item for item in records if any(self.knowledge.value_matches(v, concept,
                                hierarchy=expected.match == "subsumption") for v in item.value.values)]
                    states = {item.value.status for item in matching}
                    outcomes.append("matched" if states == {"present"} else "contradicted" if states == {"absent"} else "unknown")
                    refs.extend(item.id for item in matching if item.value.status == "present")
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
    def supported_hypotheses(state):
        return [h for h in state.differential.hypotheses if h.evidence_score > 0 and h.score > 0 and h.chief_coverage == 1]

    def select_diagnosis(self, state):
        fixed = state.case.fixed_diagnosis
        if fixed:
            state.case.diagnosis_kind, state.case.diagnosis = fixed.kind, fixed.name
            state.case.diagnosis_evidence = list(fixed.evidence_ids)
            state.differential.selected_id = fixed.disease_id
            return
        state.differential.initialized = True
        self.refresh_hypotheses(state)
        if state.interaction.termination:
            return
        supported = self.supported_hypotheses(state)
        if not supported:
            state.differential.selected_id = None
            chief = state.case.chief(confirmed=True)
            if chief is None:
                state.case.diagnosis = None
                state.case.diagnosis_kind = None
                state.case.diagnosis_evidence = []
                state.stop("failed", "no_supported_diagnosis")
                return
            concepts = chief.value.concept_ids
            state.case.diagnosis = self.knowledge.label(concepts[0], language="en")
            state.case.diagnosis_kind = "symptom"
            state.case.diagnosis_evidence = [chief.id]
            return
        chosen = supported[0]
        state.differential.selected_id = chosen.disease_id
        state.case.diagnosis = self.knowledge.label(chosen.disease_id, language="en")
        state.case.diagnosis_kind = "disease"
        state.case.diagnosis_evidence = sorted(set(chosen.evidence_ids + chosen.contradiction_ids))


@dataclass(frozen=True)
class ReasoningSnapshot:
    evidence: EvidenceIndex
    chief: ChiefAnchor | None
    policy: object
    hypotheses: tuple[Hypothesis, ...]
    pattern_matches: dict[str, PatternMatch]
    association_matches: tuple[AssociationMatch, ...]
    evaluations: int
