from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]
OW = "urn:ontoward:"
KINDS = ("Disease", "Symptom", "ExamFinding", "AttributeValue", "ContextFactor", "Test", "ExamMethod")
ATTRIBUTES = ("Location", "Laterality", "Quality", "Onset", "Course", "EpisodeDuration",
              "Frequency", "Timing", "Severity", "Trigger", "AggravatingFactor", "RelievingFactor", "Radiation")
Kind = Literal["Disease", "Symptom", "ExamFinding", "AttributeValue", "ContextFactor", "Test", "ExamMethod"]
ContextType = Literal["past_medical_history", "surgical_history", "medication_history", "allergy_history",
                      "family_history", "social_history", "occupational_history", "psychosocial_history",
                      "screening_history", "demographic"]
Attribute = Literal["Location", "Laterality", "Quality", "Onset", "Course", "EpisodeDuration",
                    "Frequency", "Timing", "Severity", "Trigger", "AggravatingFactor", "RelievingFactor", "Radiation"]


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False,
                                                          separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(workspace_path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = workspace_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def workspace_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Preparation paths must stay inside the project workspace")
    return path


def concept_uri(sctid):
    return OW + "SnomedCT" + sctid


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Strict):
    kind: Literal["description", "relationship", "concrete"]
    id: str
    quote: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)


class Qualification(Strict):
    attribute: Attribute
    value_id: str
    evidence: list[Evidence] = Field(min_length=1)


class VocabularyEntry(Strict):
    sctid: str = Field(pattern=r"^[0-9]+$")
    uri: str
    kind: Kind
    label: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    attributes: list[Attribute] = Field(default_factory=list)
    value_attributes: list[Attribute] = Field(default_factory=list)
    context_type: ContextType | None = None
    methods: list[str] = Field(default_factory=list)
    exam_request_text: str | None = None
    review_status: Literal["candidate", "selected"] = "candidate"
    evidence: list[Evidence] = Field(min_length=1)
    basis: str = Field(min_length=1)


class VocabularyDecision(Strict):
    packet_id: str
    decision: Literal["map", "decompose", "exclude"]
    sctid: str | None = None
    kind: Kind | None = None
    target_id: str | None = None
    qualifications: list[Qualification] = Field(default_factory=list)
    attributes: list[Attribute] = Field(default_factory=list)
    value_attributes: list[Attribute] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class VocabularyResponse(Strict):
    decisions: list[VocabularyDecision]


class Feature(Strict):
    attribute: Attribute | None = None
    value_id: str | None = None
    expected_status: Literal["present", "absent"] | None = None
    evidence: list[Evidence] = Field(min_length=1)

    @model_validator(mode="after")
    def condition(self):
        if bool(self.attribute) != bool(self.value_id) or (not self.attribute and not self.expected_status):
            raise ValueError("Require a categorical pair or an explicit expected status")
        return self


class ProjectionDecision(Strict):
    packet_id: str
    decision: Literal["accept", "exclude", "unresolved"]
    features: list[Feature] = Field(default_factory=list)
    profile: Literal["compatible", "distinct", "unresolved"] = "compatible"
    profile_evidence: list[Evidence] = Field(default_factory=list)
    unrepresentable: list[Evidence] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class ProjectionResponse(Strict):
    decisions: list[ProjectionDecision]


class Review(Strict):
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    accepted_sctids: list[str]
    excluded_sctids: list[str]
    accepted_decompositions: list[str] = Field(default_factory=list)
    metadata: dict[str, dict] = Field(default_factory=dict)


def schemas():
    return {"vocabulary-response": VocabularyResponse.model_json_schema(),
            "projection-response": ProjectionResponse.model_json_schema(),
            "vocabulary-entry": VocabularyEntry.model_json_schema(), "review": Review.model_json_schema()}
