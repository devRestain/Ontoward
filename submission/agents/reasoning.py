from knowledge.graph import ClinicalKnowledge

from .state import Hypothesis, WorkflowState


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


class ReasoningAgent:
    def __init__(self, knowledge: ClinicalKnowledge):
        self.knowledge = knowledge

    def retrieve_candidates(self, state: WorkflowState) -> None:
        state.differential.initialized = True
        self.refresh_hypotheses(state)

    def refresh_hypotheses(self, state: WorkflowState, *, score_context=False) -> None:
        if not state.differential.initialized:
            return
        groups = observation_groups(state)
        diseases = set()
        for group in groups.values():
            for item in group["base"]:
                if item.value.status in {"present", "uncertain"}:
                    for concept in item.value.concept_ids:
                        diseases.update(disease for disease, _ in self.knowledge.get_patterns_by_target(concept))
        score_context = score_context or state.session.current in {"DifferentialDiagnosis", "Education"}
        hypotheses = []
        for disease in sorted(diseases):
            contributions = {}
            patterns = self.knowledge.get_disease_patterns(disease)
            for pattern in patterns:
                target = pattern["target"]
                features = self.knowledge.get_pattern_features(pattern["id"])
                for identity, group in groups.items():
                    bases = [item for item in group["base"] if target in item.value.concept_ids]
                    if not bases:
                        continue
                    statuses = {item.value.status for item in bases}
                    status = next(iter(statuses)) if len(statuses) == 1 else "uncertain"
                    # Ambiguous concept alternatives provide recall, not independent score contributions.
                    confirmed = all(len(item.value.concept_ids) == 1 for item in bases)
                    for feature in features:
                        result, refs = self._match(feature, target, status, confirmed, bases, group["attributes"])
                        if result == "unknown":
                            continue
                        role = feature["role"]
                        characteristic = role == "characteristic" or pattern["characteristic"]
                        amount = (-1 if role == "opposing" else (2 if characteristic else 1)) if result == "matched" else (-1 if role != "opposing" else 0)
                        key = (*identity, target, feature["attribute"], feature["value"]) if feature["attribute"] else (*identity, target, "presence")
                        self._add(contributions, key, amount, refs)
                    if status == "present" and confirmed and not any(not feature["attribute"] for feature in features):
                        amount = 2 if pattern["characteristic"] and not features else 1
                        self._add(contributions, (*identity, target, "presence"), amount, [item.id for item in bases])
            context_bonus = None
            context_refs = []
            if score_context:
                contexts = {item["id"]: item["type"] for item in self.knowledge.get_supporting_context(disease)}
                context_refs = [item.id for _, item in state.case.entries() if
                    item.status == "done" and item.source_refs and item.value and item.value.kind == "context"
                    and item.value.status == "present" and any(
                        concept in contexts and (contexts[concept] == "family_history") == (item.value.subject == "family")
                        for concept in item.value.concept_ids)
                ]
                context_bonus = int(bool(context_refs))
            hypotheses.append(Hypothesis(
                disease_id=disease, pattern_ids=[pattern["id"] for pattern in patterns],
                feature_ids=sorted({feature["id"] for pattern in patterns for feature in self.knowledge.get_pattern_features(pattern["id"])}),
                evidence_score=sum(amount for amount, _ in contributions.values()), context_bonus=context_bonus,
                evidence_ids=sorted({ref for amount, refs in contributions.values() if amount > 0 for ref in refs} | set(context_refs)),
                opposing_ids=sorted({ref for amount, refs in contributions.values() if amount < 0 for ref in refs}),
            ))
        state.differential.hypotheses = sorted(hypotheses, key=lambda item: (-item.score, item.disease_id))

    @staticmethod
    def _add(contributions, key, amount, refs):
        previous, previous_refs = contributions.get(key, (amount, []))
        amount = 0 if previous * amount < 0 else (max(previous, amount) if amount >= 0 else min(previous, amount))
        contributions[key] = (amount, list(set(previous_refs) | set(refs)))

    @staticmethod
    def _match(feature, target, status, confirmed, bases, attributes):
        checks, refs = [], []
        if not confirmed:
            return "unknown", []
        if feature["status"]:
            checks.append("unknown" if status not in {"present", "absent"} else
                          ("matched" if status == feature["status"] else "contradicted"))
            refs.extend(item.id for item in bases)
        if feature["attribute"]:
            compatible = [item for item in attributes if item.value.attribute_id == feature["attribute"]
                          and target in item.value.concept_ids and feature["value"] in item.value.values]
            statuses = {item.value.status for item in compatible}
            check = "matched" if statuses == {"present"} else ("contradicted" if statuses == {"absent"} else "unknown")
            checks.append(check)
            refs.extend(item.id for item in compatible)
        if not checks or "unknown" in checks:
            return "unknown", []
        return ("contradicted" if "contradicted" in checks else "matched"), refs

    def select_diagnosis(self, state: WorkflowState) -> None:
        state.differential.initialized = True
        self.refresh_hypotheses(state, score_context=True)
        if state.interaction.termination:
            return
        if not state.differential.hypotheses:
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
        selected = state.differential.hypotheses[0].disease_id
        state.differential.selected_id = selected
        state.case.diagnosis = self.knowledge.label(selected)
        state.case.diagnosis_kind = "disease"
        state.case.diagnosis_evidence = list(state.differential.hypotheses[0].evidence_ids)
