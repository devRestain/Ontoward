import hashlib
import itertools
import json
import math
from dataclasses import dataclass

from knowledge.conditions import ExpectedValue

from ..state.models import ClinicalValue, RecordItem


def question_key(spec):
    return json.dumps([spec[k] for k in ("kind", "target_id", "attribute_id", "subject", "time_context",
                                        "observation_id", "episode_id")], separators=(",", ":"))


def eligible(hypothesis):
    return bool(hypothesis and hypothesis.chief_coverage == 1 and hypothesis.evidence_score > 0 and hypothesis.score > 0)


def decision_value(base, outcomes, candidates, policy):
    before = {h.disease_id: h for h in base.hypotheses}
    unique = {}
    for snapshot in outcomes:
        row = {h.disease_id: h for h in snapshot.hypotheses}
        key = tuple((d, row[d].score if d in row else 0, eligible(row.get(d))) for d in candidates)
        unique[key] = row
    rows = list(unique.values())
    if not rows:
        return 0.0, 0.0

    def relation(row, left, right):
        a, b = row.get(left), row.get(right)
        if eligible(a) and eligible(b):
            return max(-1.0, min(1.0, (a.score - b.score) / policy.score_scale))
        return float(eligible(a)) - float(eligible(b))

    weighted, weights = 0.0, 0.0
    for left, right in itertools.combinations(candidates, 2):
        a, b = before.get(left), before.get(right)
        weight = 1 / (1 + abs(a.score - b.score) / policy.score_scale) if eligible(a) and eligible(b) else 1
        values = [relation(row, left, right) for row in rows]
        pairs = list(itertools.combinations(values, 2))
        weighted += weight * (sum(abs(a - b) / 2 for a, b in pairs) / len(pairs) if pairs else 0)
        weights += weight
    changes = sum(eligible(row.get(d)) != eligible(before.get(d)) for row in rows for d in candidates)
    return weighted / weights if weights else 0.0, changes / max(1, len(rows) * len(candidates))


def answer_patch(spec, *, status="present", values=(), measurement=None, suffix=""):
    key = question_key(spec)
    ident = "simulation:" + hashlib.sha256(key.encode()).hexdigest()[:24] + suffix
    kind = "attribute" if spec["attribute_id"] else "context" if spec["field"] in {"S.pmh", "S.fh", "S.sh"} else (
        "finding" if spec["kind"] == "EXAM" else "symptom")
    value = ClinicalValue(kind=kind, text="Hypothetical answer", status=status, concept_ids=[spec["target_id"]],
        attribute_id=spec["attribute_id"], values=list(values), measurement=measurement,
        observation_id=spec["observation_id"] or ident, episode_id=spec["episode_id"] or ident,
        subject=spec["subject"], time_context=spec["time_context"])
    return (spec["field"], RecordItem(id=ident, scope="DifferentialDiagnosis", status="done", value=value,
                                    source_refs=[ident], acquisition=spec["kind"]))


def answer_regions(spec, knowledge, reasoner, pattern_ids, limit):
    if not spec["attribute_id"]:
        return [(answer_patch(spec, status=status),) for status in ("present", "absent")], True
    predicates = list({f.signature(): f for p in pattern_ids for f in knowledge.get_pattern_features(p)
                       if f.attribute == spec["attribute_id"]}.values())
    numeric, categorical = {}, set()
    for f in predicates:
        expected = f.expected
        if expected.kind in {"quantity", "interval"}:
            normalized = expected.normalized()
            for unit, value in ((normalized.unit, normalized.value), (normalized.unit, normalized.lower),
                                (normalized.upper_unit or normalized.unit, normalized.upper)):
                if value is not None:
                    numeric.setdefault(unit, set()).add(value)
        else:
            categorical.update([expected.concept] if expected.kind == "concept" else expected.concepts)
    regions = {}

    def add(patch):
        records = [item for _, item in patch]
        signature = tuple(reasoner._match(f, spec["target_id"], "present", [], records)[0] for f in predicates)
        regions.setdefault(signature, patch)

    for unit, cutpoints in sorted(numeric.items()):
        cuts = sorted(cutpoints)
        points = [math.nextafter(cuts[0], -math.inf), math.nextafter(cuts[-1], math.inf), *cuts]
        points += [(a + b) / 2 for a, b in zip(cuts, cuts[1:])]
        for value in points:
            if math.isfinite(value):
                add((answer_patch(spec, measurement=ExpectedValue(kind="quantity", value=float(value), unit=unit)),))
        for lower, upper in itertools.combinations(sorted(set(points)), 2):
            add((answer_patch(spec, measurement=ExpectedValue(kind="interval", lower=float(lower),
                                                           upper=float(upper), unit=unit)),))
    # A partial categorical report is open-world: unmentioned values stay unknown.
    values = sorted(categorical)
    if values:
        atoms = {}
        for value in sorted(set(values) | set(knowledge.get_attribute_values(spec["attribute_id"]))):
            signature = tuple(knowledge.value_matches(value, concept, hierarchy=f.expected.match == "subsumption")
                for f in predicates if f.expected.kind in {"concept", "concept_set"}
                for concept in ([f.expected.concept] if f.expected.kind == "concept" else f.expected.concepts))
            atoms.setdefault(signature, value)
        values = sorted(atoms.values())
        for index, assignment in enumerate(itertools.product((0, 1, -1), repeat=len(values))):
            if index >= limit:
                return list(regions.values()), False
            positive = [v for v, flag in zip(values, assignment) if flag == 1]
            negative = [v for v, flag in zip(values, assignment) if flag == -1]
            patch = []
            if positive:
                patch.append(answer_patch(spec, values=positive))
            if negative:
                patch.append(answer_patch(spec, status="absent", values=negative, suffix=":negative"))
            if patch:
                add(tuple(patch))
    return list(regions.values()), True


@dataclass
class QuestionPath:
    specs: tuple
    profile: object | None
    disease_id: str
    pattern_id: str | None
    evidence_ids: tuple


class QuestionEvaluation:
    def __init__(self, reasoner, snapshot, candidates):
        self.reasoner, self.base, self.candidates = reasoner, snapshot, tuple(candidates)
        self.policy = snapshot.policy
        self.used, self.limited = 0, False
        self.cache = {}

    def simulate(self, snapshot, patch):
        key = (snapshot.evidence.fingerprint, tuple((field, item.value.model_dump_json()) for field, item in patch))
        if key in self.cache:
            return self.cache[key]
        if self.used >= self.policy.simulation_limit:
            self.limited = True
            return None
        self.used += 1
        result = self.reasoner.evaluate_delta(snapshot, patch)
        self.cache[key] = result
        return result

    def path_alive(self, path, snapshot):
        if path.profile is None:
            return True
        index = {}
        for item in snapshot.evidence.contexts:
            for concept in item.value.concept_ids:
                index.setdefault((concept, item.value.subject, item.value.time_context), []).append(item)
        if self.reasoner._applicability(path.profile.applicability, index)[0] == "contradicted":
            return False
        return not any(m.status == "contradicted" and m.pattern_id == path.pattern_id
                       and m.observation_id == path.specs[-1]["observation_id"]
                       and m.episode_id == path.specs[-1]["episode_id"]
                       and m.time_context == path.specs[-1]["time_context"] for m in snapshot.pattern_matches.values())

    def assess(self, specs, paths):
        patterns = {p.pattern_id for p in paths if p.pattern_id}
        one_step, assessments = {}, {}
        direct_limit = self.policy.simulation_limit
        impact = {key: {p.disease_id for p in paths if question_key(p.specs[0]) == key} for key in specs}
        lengths = {key: min(len(p.specs) for p in paths if question_key(p.specs[0]) == key) for key in specs}
        for key in sorted(specs, key=lambda k: (lengths[k], -len(impact[k]), k)):
            spec = specs[key]
            relevant = {p for p in patterns if p in self.reasoner.knowledge.patterns_by_input.get(
                (spec["target_id"], spec["attribute_id"]), set())}
            outcomes, complete = answer_regions(spec, self.reasoner.knowledge, self.reasoner, relevant,
                                               self.policy.simulation_limit)
            after = []
            if self.used + len(outcomes) > direct_limit:
                complete = False
            if complete:
                for patch in outcomes:
                    result = self.simulate(self.base, patch)
                    if result is None:
                        complete = False
                        break
                    after.append((patch, result))
            d, e = decision_value(self.base, [s for _, s in after], self.candidates, self.policy) if complete else (0, 0)
            value = d + self.policy.eligibility_weight * e
            one_step[key] = (after, complete)
            assessments[key] = {"policy_version": self.policy.version, "complete": complete,
                "direct_value": value if complete else None, "discrimination": d if complete else None,
                "eligibility": e if complete else None, "utility": value if complete else None,
                "plan_value": 0.0, "cost": 1, "paths": [],
                "outcomes": [{"answer": [i.value.model_dump(exclude={"text", "record_details"}) for _, i in patch],
                              "scores": {h.disease_id: {"score": h.score, "chief_score": h.chief_score,
                                         "supporting_score": h.supporting_score, "context_bonus": h.context_bonus,
                                         "penalty": h.contradiction_penalty, "eligible": eligible(h),
                                         "contributions": [c.model_dump() for c in h.contributions],
                                         "contradiction_ids": h.contradiction_ids,
                                         "incomparable_matches": h.incomparable_matches}
                                         for h in result.hypotheses if h.disease_id in self.candidates}}
                             for patch, result in after], "unknown": "no_clinical_change"}
        for path in sorted(paths, key=lambda p: (len(p.specs), p.disease_id, p.pattern_id or "")):
            keys = [question_key(spec) for spec in path.specs]
            root = keys[0]
            assessment = assessments[root]
            assessment["paths"].append({"disease_id": path.disease_id, "pattern_id": path.pattern_id,
                "association_id": path.profile.association_id if path.profile else None,
                "evidence_ids": list(path.evidence_ids), "remaining": keys,
                "conditions": [f.id for f in self.reasoner.knowledge.get_pattern_features(path.pattern_id)]
                    if path.pattern_id else [],
                "prerequisites": [c.model_dump() for c in path.profile.applicability] if path.profile else []})
            if len(keys) == 1 or len(keys) > self.policy.plan_questions:
                continue
            leaves, branches, frontier, complete = [], {}, [(self.base, 0, None)], True
            while frontier:
                snapshot, index, first = frontier.pop()
                if index == len(keys) or not self.path_alive(path, snapshot):
                    leaves.append(snapshot)
                    if first is not None:
                        branches.setdefault(first.evidence.fingerprint, (first, []))[1].append(snapshot)
                    continue
                spec = path.specs[index]
                # A negative presence answer closes attribute acquisition on that occurrence.
                if spec["attribute_id"] and spec["kind"] == "SAY":
                    records = snapshot.evidence.records(spec["target_id"], observation=spec["observation_id"],
                        episode=spec["episode_id"], subject=spec["subject"], timing=spec["time_context"])
                    if not any(i.value.status == "present" and len(i.value.concept_ids) == 1 for i in records):
                        leaves.append(snapshot)
                        if first is not None:
                            branches.setdefault(first.evidence.fingerprint, (first, []))[1].append(snapshot)
                        continue
                relevant = self.reasoner.knowledge.get_target_patterns(spec["target_id"]) if spec["attribute_id"] else []
                answers, full = answer_regions(spec, self.reasoner.knowledge, self.reasoner, relevant,
                                               self.policy.simulation_limit)
                if not full:
                    complete = False
                    break
                for patch in answers:
                    result = self.simulate(snapshot, patch)
                    if result is None:
                        complete = False
                        break
                    frontier.append((result, index + 1, first or result))
                if not complete:
                    break
            if not complete:
                assessment["plan_incomplete"] = True
                assessment["paths"][-1]["evaluation"] = "incomplete"
                self.limited = True
                continue
            d, e = decision_value(self.base, leaves, self.candidates, self.policy)
            joint = d + self.policy.eligibility_weight * e
            value = self.policy.future_discount ** (len(keys) - 1) * joint / len(keys)
            if len(keys) == 2 and one_step[root][1]:
                followups = []
                for first, follow in branches.values():
                    fd, fe = decision_value(first, follow, self.candidates, self.policy)
                    followups.append(fd + self.policy.eligibility_weight * fe)
                value = max(value, (assessment["direct_value"] + self.policy.future_discount *
                                   sum(followups) / max(1, len(followups))) / 2)
            assessment["plan_value"] = max(assessment["plan_value"], value)
            assessment["utility"] = max(assessment["utility"] or 0, value)
            assessment["complete"] = True
            joint_outcomes = {}
            for leaf in leaves:
                scores = {h.disease_id: {"score": h.score, "eligible": eligible(h)}
                          for h in leaf.hypotheses if h.disease_id in self.candidates}
                signature = json.dumps(scores, sort_keys=True)
                joint_outcomes.setdefault(signature, {"scores": scores, "answers": [
                    item.value.model_dump(exclude={"text", "record_details", "record_category"})
                    for _, item in leaf.evidence.raw if item.id.startswith("simulation:")]})
            assessment["paths"][-1].update(evaluation="complete", joint_value=joint, utility=value,
                                            outcomes=list(joint_outcomes.values()))
        return assessments
