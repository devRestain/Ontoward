from pydantic import BaseModel


class FeatureContribution(BaseModel):
    baseline_association: str
    refined_association: str
    changed_feature_ids: list[str]
    delta_score: float
    kind: str
    policy_version: str


def feature_contributions(knowledge, association_id):
    child = knowledge._profile_cache[association_id]
    signatures = {p.id:p for p in knowledge.get_disease_patterns(child.disease_id)
        if p.target==child.target and p.applicability==child.applicability}
    parents = knowledge._refinement_parents.get(child.id,set()) & signatures.keys()
    result = []
    for parent_id in sorted(parents):
        parent = signatures[parent_id]
        previous = {f.signature() for f in knowledge.get_pattern_features(parent_id)}
        changed = [f.id for f in knowledge.get_pattern_features(child.id) if f.signature() not in previous]
        result.append(FeatureContribution(baseline_association=parent.association_id,
            refined_association=child.association_id,changed_feature_ids=changed,delta_score=child.score-parent.score,
            kind='atomic' if len(changed)==1 else 'joint',policy_version=knowledge.policy.version))
    return sorted(result,key=lambda c:c.baseline_association)
