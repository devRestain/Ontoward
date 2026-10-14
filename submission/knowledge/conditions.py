from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, strict=True)


class ExpectedValue(Strict):
    kind: Literal["concept", "concept_set", "quantity", "interval"]
    concept: str | None = None
    concepts: list[str] = Field(default_factory=list)
    selection: Literal["any_of", "all_of"] = "any_of"
    match: Literal["exact", "subsumption"] = "exact"
    value: float | None = None
    operator: Literal["eq", "lt", "le", "gt", "ge"] = "eq"
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    unit: str | None = None
    upper_unit: str | None = None

    @model_validator(mode="after")
    def validate_value(self):
        if self.kind == "concept":
            if not self.concept or self.concepts:
                raise ValueError("Concept expectation requires one identifier")
        elif self.kind == "concept_set":
            if not self.concepts or self.concept or len(set(self.concepts)) != len(self.concepts):
                raise ValueError("Concept set requires distinct identifiers")
        elif self.kind == "quantity":
            if self.value is None or not self.unit or self.lower is not None or self.upper is not None:
                raise ValueError("Quantity requires a value, unit and operator")
        elif not self.unit or (self.lower is None and self.upper is None) or self.value is not None:
            raise ValueError("Interval requires a unit and at least one bound")
        if self.kind in {"concept", "concept_set"}:
            if any(v is not None for v in (self.value, self.lower, self.upper, self.unit, self.upper_unit)) or self.operator != "eq":
                raise ValueError("Concept values cannot carry numeric conditions")
            if not self.lower_inclusive or not self.upper_inclusive or (self.kind == "concept" and self.selection != "any_of"):
                raise ValueError("Concept expectation contains irrelevant range conditions")
        elif self.concept or self.concepts or self.match != "exact" or self.selection != "any_of":
            raise ValueError("Numeric values cannot carry concept conditions")
        if self.kind != "interval" and self.upper_unit is not None:
            raise ValueError("Only interval upper bounds can use another unit")
        if self.kind == "quantity" and (not self.lower_inclusive or not self.upper_inclusive):
            raise ValueError("Quantity uses its operator rather than interval boundaries")
        if self.kind == "interval" and self.operator != "eq":
            raise ValueError("Interval comparison uses its bounds")
        if self.kind == "interval" and self.lower is not None and self.upper is not None:
            a, b = number(self.lower, self.unit), number(self.upper, self.upper_unit or self.unit)
            if a[0] == b[0] and (a[1] > b[1] or (a[1] == b[1] and not (self.lower_inclusive and self.upper_inclusive))):
                raise ValueError("Interval is empty or reversed")
        return self

    def signature(self):
        data = {"kind": self.kind}
        if self.kind == "concept":
            data.update(concept=self.concept, match=self.match)
        elif self.kind == "concept_set":
            data.update(concepts=sorted(self.concepts), selection=self.selection, match=self.match)
        elif self.kind == "quantity":
            data.update(value=number(self.value, self.unit), operator=self.operator)
        else:
            data.update(lower=number(self.lower, self.unit) if self.lower is not None else None,
                        upper=number(self.upper, self.upper_unit or self.unit) if self.upper is not None else None,
                        lower_inclusive=self.lower_inclusive, upper_inclusive=self.upper_inclusive)
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def normalized(self):
        data = self.model_dump()
        data["concepts"] = sorted(data["concepts"])
        units = {"fixed_time": "s", "calendar_time": "month"}
        if self.kind == "quantity":
            group, value = number(self.value, self.unit)
            data.update(value=value, unit=units.get(group, self.unit))
        elif self.kind == "interval":
            group, _ = number(1, self.unit)
            data["unit"] = units.get(group, self.unit)
            if self.lower is not None:
                data["lower"] = number(self.lower, self.unit)[1]
            if self.upper is not None:
                upper_group, upper = number(self.upper, self.upper_unit or self.unit)
                data.update(upper=upper, upper_unit=units.get(upper_group, self.upper_unit or self.unit))
                if data["upper_unit"] == data["unit"]:
                    data["upper_unit"] = None
        return ExpectedValue.model_validate(data)


class FeatureCondition(Strict):
    id: str
    attribute: str | None = None
    expected: ExpectedValue | None = None
    status: Literal["present", "absent"] | None = None

    @model_validator(mode="after")
    def validate_condition(self):
        if bool(self.attribute) != bool(self.expected) or (not self.attribute and self.status is None):
            raise ValueError("Feature requires an attribute expectation or presence condition")
        return self

    def signature(self):
        return (self.attribute or "", self.expected.signature() if self.expected else "", self.status or "")


class Applicability(Strict):
    concept_id: str
    status: Literal["present", "absent"] = "present"
    subject: Literal["patient", "family"] = "patient"
    time_context: Literal["current", "past", "unspecified"] = "current"


class AssociationProfile(Strict):
    id: str
    association_id: str
    disease_id: str
    target: str
    applicability: list[Applicability] = Field(default_factory=list)
    predictiveness: str | None = None
    typicality: str | None = None
    strong_predictor: bool | None = None
    relation_basis: Literal["bodhi_present_in", "due_to", "associated_with", "subtype_intersection"]
    derivation_scope: Literal["exact", "descendant"] = "exact"
    source_refs: list[str] = Field(min_length=1)
    score: float
    weight_basis: str


class FeatureContribution(Strict):
    baseline_association: str
    refined_association: str
    changed_feature_ids: list[str]
    delta_score: float
    kind: Literal["atomic", "joint"]
    policy_version: str


class ScoringPolicy(Strict):
    version: str = Field(min_length=1)
    labels: dict[str, float]
    relations: dict[str, float]
    generalized: float

    @model_validator(mode="after")
    def validate_policy(self):
        labels = ("zero", "rare", "low", "medium", "high", "very_high")
        if set(self.labels) != set(labels) or set(self.relations) != {"due_to", "associated_with", "subtype_intersection"}:
            raise ValueError("Scoring policy must define every supported label and relation")
        scores = [self.labels[label] for label in labels]
        if scores != sorted(scores) or any(v < 0 for v in [*scores, *self.relations.values(), self.generalized]):
            raise ValueError("Support weights must be nonnegative and labels ordered")
        return self

    @classmethod
    def load_default(cls):
        return cls.model_validate_json(Path(__file__).with_name("scoring_policy.json").read_text(encoding="utf-8"))

    def weight(self, predictiveness, relation_basis, derivation_scope):
        if relation_basis not in {"bodhi_present_in", *self.relations} or derivation_scope not in {"exact", "descendant"}:
            raise ValueError("Unknown association source basis or scope")
        if predictiveness is not None:
            if predictiveness not in self.labels:
                raise ValueError("Unknown directional likelihood label")
            return self.labels[predictiveness], "bodhi_ordinal"
        if relation_basis == "bodhi_present_in":
            raise ValueError("BODHI association requires its directional likelihood")
        if derivation_scope == "descendant":
            return self.generalized, "snomed_generalized"
        return self.relations[relation_basis], "snomed_relation"


def number(value, unit):
    fixed = {"s": 1, "min": 60, "h": 3600, "day": 86400, "week": 604800}
    calendar = {"month": 1, "year": 12}
    if unit in fixed:
        return "fixed_time", value * fixed[unit]
    if unit in calendar:
        return "calendar_time", value * calendar[unit]
    return unit, value


def bounds(value):
    if value.kind == "quantity":
        point = number(value.value, value.unit)
        return {"eq": (point, point, True, True), "lt": (None, point, False, False),
                "le": (None, point, False, True), "gt": (point, None, False, False),
                "ge": (point, None, True, False)}[value.operator]
    return (number(value.lower, value.unit) if value.lower is not None else None,
            number(value.upper, value.upper_unit or value.unit) if value.upper is not None else None,
            value.lower_inclusive, value.upper_inclusive)


def numeric_match(expected, observation):
    if observation.kind not in {"quantity", "interval"}:
        return "unknown"
    el, eu, eli, eui = bounds(expected)
    ol, ou, oli, oui = bounds(observation)
    groups = {b[0] for b in (el, eu, ol, ou) if b is not None}
    if len(groups) != 1:
        return "unknown"
    inside_lower = el is None or (ol is not None and (ol[1] > el[1] or (ol[1] == el[1] and (eli or not oli))))
    inside_upper = eu is None or (ou is not None and (ou[1] < eu[1] or (ou[1] == eu[1] and (eui or not oui))))
    if inside_lower and inside_upper:
        return "matched"
    if (el is not None and ou is not None and (ou[1] < el[1] or (ou[1] == el[1] and not (eli and oui)))) or (
        eu is not None and ol is not None and (ol[1] > eu[1] or (ol[1] == eu[1] and not (eui and oli)))
    ):
        return "contradicted"
    return "unknown"
