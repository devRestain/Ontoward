from knowledge.conditions import numeric_match
from knowledge.graph import ClinicalKnowledge

from .state.models import Hypothesis, ScoreContribution, WorkflowState


def observation_groups(state: WorkflowState):
    groups = {}
    for _, item in state.case.entries():
        value = item.value
        if item.status != "done" or not item.source_refs or value is None or value.kind not in {"symptom", "finding", "attribute"}:
            continue
        if value.subject != "patient" or value.time_context == "past":
            continue
        key = (value.observation_id or item.id, value.episode_id or item.id)
        group = groups.setdefault(key, {"base": [], "attributes": []})
        group["attributes" if value.kind == "attribute" else "base"].append(item)
    return groups


class ClinicalReasoner:
    def __init__(self, knowledge: ClinicalKnowledge):
        self.knowledge = knowledge

    def retrieve_candidates(self, state: WorkflowState) -> None:
        state.differential.initialized = True
        self.refresh_hypotheses(state)

    def refresh_hypotheses(self, state: WorkflowState, *, score_context=False) -> None:
        if not state.differential.initialized:
            return
        groups = observation_groups(state)
        diseases = {profile.disease_id for group in groups.values() for item in group["base"]
                    if item.value.status in {"present", "uncertain"} for concept in item.value.concept_ids
                    for profile in self.knowledge.get_patterns_by_target(concept)}
        score_context = score_context or state.session.current in {"DifferentialDiagnosis", "Education"}
        hypotheses = []
        for disease in sorted(diseases):
            patterns = self.knowledge.get_disease_patterns(disease)
            contributions = {}
            for group in groups.values():
                matches = []
                for profile in patterns:
                    bases = [item for item in group["base"] if profile.target in item.value.concept_ids]
                    if not bases or not all(len(item.value.concept_ids) == 1 for item in bases):
                        continue
                    statuses = {item.value.status for item in bases}
                    status = next(iter(statuses)) if len(statuses) == 1 else "uncertain"
                    features = self.knowledge.get_pattern_features(profile.id)
                    checks = [self._match(f, profile.target, status, bases, group["attributes"]) for f in features]
                    applies, context_refs = self._applies(profile.applicability, state)
                    if not applies or not checks or any(result != "matched" for result, _ in checks):
                        continue
                    refs = sorted({ref for _, ids in checks for ref in ids} | set(context_refs) | {item.id for item in bases})
                    matches.append((profile, refs, features))
                # Refinement replaces its ancestor even when its source score is lower.
                maximal = [item for item in matches if not any(
                    other[0].applicability == item[0].applicability
                    and self.knowledge.pattern_refines(other[0].id, item[0].id) for other in matches)]
                for profile, refs, features in sorted(maximal, key=lambda item: (-item[0].score, item[0].association_id)):
                    if profile.target not in contributions or profile.score > contributions[profile.target].score:
                        matched_ids = {p.association_id for p, _, _ in matches}
                        contributions[profile.target] = ScoreContribution(
                            association_id=profile.association_id, pattern_id=profile.id, target_id=profile.target,
                            score=profile.score, evidence_ids=refs, weight_basis=profile.weight_basis,
                            policy_version=self.knowledge.policy.version,
                            feature_deltas=[c for c in self.knowledge.get_feature_contributions(profile.association_id)
                                            if c.baseline_association in matched_ids])
            context_bonus, context_refs = None, []
            if score_context:
                contexts = {item["id"]: item["type"] for item in self.knowledge.get_supporting_context(disease)}
                context_refs = [item.id for _, item in state.case.entries() if
                    item.status == "done" and item.source_refs and item.value and item.value.kind == "context"
                    and item.value.status == "present" and any(
                        concept in contexts and (contexts[concept] == "family_history") == (item.value.subject == "family")
                        for concept in item.value.concept_ids)]
                context_bonus = int(bool(context_refs))
            selected = list(contributions.values())
            hypotheses.append(Hypothesis(
                disease_id=disease, pattern_ids=sorted({p.id for p in patterns}),
                association_ids=sorted({p.association_id for p in patterns}),
                feature_ids=sorted({f.id for p in patterns for f in self.knowledge.get_pattern_features(p.id)}),
                evidence_score=sum(c.score for c in selected), context_bonus=context_bonus, contributions=selected,
                evidence_ids=sorted({ref for c in selected if c.score > 0 for ref in c.evidence_ids} | set(context_refs))))
        state.differential.hypotheses = sorted(hypotheses, key=lambda item: (-item.score, item.disease_id))

    @staticmethod
    def _applies(conditions, state):
        refs = []
        for condition in conditions:
            records = [item for _, item in state.case.entries() if item.status == "done" and item.source_refs
                       and item.value and item.value.kind == "context" and condition.concept_id in item.value.concept_ids
                       and item.value.subject == condition.subject and item.value.time_context == condition.time_context]
            if {item.value.status for item in records} != {condition.status}:
                return False, []
            refs.extend(item.id for item in records)
        return True, refs

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
        if not checks or "unknown" in checks:
            return "unknown", []
        return ("contradicted" if "contradicted" in checks else "matched"), refs

    def select_diagnosis(self, state: WorkflowState) -> None:
        state.differential.initialized = True
        self.refresh_hypotheses(state, score_context=True)
        if state.interaction.termination:
            return
        supported = [h for h in state.differential.hypotheses if h.evidence_score > 0]
        if not supported:
            state.differential.selected_id = None
            chiefs = state.case.chief_complaints(confirmed=True)
            if not chiefs:
                state.case.diagnosis = None
                state.case.diagnosis_kind = None
                state.case.diagnosis_evidence = []
                state.stop("failed", "no_supported_diagnosis")
                return
            chief = chiefs[0]
            concepts = chief.value.concept_ids
            state.case.diagnosis = self.knowledge.label(concepts[0]) if len(concepts) == 1 else chief.value.text
            state.case.diagnosis_kind = "symptom"
            state.case.diagnosis_evidence = [chief.id]
            return
        selected = supported[0].disease_id
        state.differential.selected_id = selected
        state.case.diagnosis = self.knowledge.label(selected)
        state.case.diagnosis_kind = "disease"
        state.case.diagnosis_evidence = list(supported[0].evidence_ids)
