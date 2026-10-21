from __future__ import annotations

import json
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
    approximate: bool = False

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
            if self.approximate:
                raise ValueError("Only numeric values can be approximate")
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
        if self.approximate:
            data["approximate"] = True
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


class TargetScope(Strict):
    subject: Literal["patient", "family"]
    subject_member: str | None
    time_context: Literal["current", "past", "unspecified", "any"]

    @model_validator(mode="after")
    def member(self):
        if self.subject == "patient" and self.subject_member is not None:
            raise ValueError("Only a family scope can name a member")
        return self


class Applicability(TargetScope):
    concept_id: str
    status: Literal["present", "absent"]


class AssociationProfile(Strict):
    id: str
    association_id: str
    disease_id: str
    target: str
    applicability: list[Applicability] = Field(default_factory=list)
    target_scope: TargetScope
    effect: Literal["support", "strong_support", "against", "strong_against"]


class AttributeRole(Strict):
    order: int = Field(ge=0)
    category: Literal["onset", "duration", "course", "quality", "aggravating_factor", "relieving_factor", "associated_symptoms", "measurement", "other"]
    clarification: str | None = None


class QuestionTemplate(Strict):
    text: str
    answer_type: Literal["presence", "category", "quantity", "duration", "free_text"] = "free_text"
    affirmative: bool = False
    interviewable: bool = True
    reason: str | None = None
    units: list[str] = Field(default_factory=list)
    time_context: Literal["current", "past", "unspecified"] = "unspecified"
    collect_via: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def validate_contract(self):
        if len(set(self.collect_via)) != len(self.collect_via) or any(not value.strip() for value in self.collect_via):
            raise ValueError("Collection components must be distinct nonempty attribute identifiers")
        if len(set(self.units)) != len(self.units) or any(not unit.strip() for unit in self.units):
            raise ValueError("Question numeric units must be distinct nonempty source formats")
        if self.units and self.answer_type not in {"quantity", "duration"}:
            raise ValueError("Numeric units require a numeric question")
        if self.affirmative and self.answer_type != "presence":
            raise ValueError("Only a presence question can map affirmative replies")
        if not self.interviewable and not self.reason:
            raise ValueError("Blocked questions require an explicit reason")
        return self


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
