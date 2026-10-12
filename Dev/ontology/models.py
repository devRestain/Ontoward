from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .vocabulary import ATTRIBUTES, load_vocabulary


VOCABULARY = load_vocabulary()


def term_enum(kind):
    return Enum(kind + "Term", {f"T{index:03}": term for index, term in
                                enumerate(VOCABULARY["terms"][kind], 1)}, type=str)


DiseaseTerm = term_enum("Disease")
SymptomTerm = term_enum("Symptom")
ExamFindingTerm = term_enum("ExamFinding")
AttributeValueTerm = term_enum("AttributeValue")
ContextFactorTerm = term_enum("ContextFactor")
TestTerm = term_enum("Test")
ExamMethodTerm = term_enum("ExamMethod")
FindingAttribute = Enum("FindingAttribute", {name: name for name in ATTRIBUTES}, type=str)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceSpan(StrictModel):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end_line < self.start_line or not self.quote.strip():
            raise ValueError("Require an ordered nonblank source span")
        return self


class SymptomTarget(StrictModel):
    kind: Literal["symptom"]
    term: SymptomTerm


class ExamFindingTarget(StrictModel):
    kind: Literal["exam_finding"]
    term: ExamFindingTerm


class Qualification(StrictModel):
    attribute: FindingAttribute
    value: AttributeValueTerm


class ClinicalFeatureCandidate(StrictModel):
    qualification: Qualification | None
    expected_status: Literal["present", "absent"] | None
    evidence: list[SourceSpan] = Field(min_length=1)

    @model_validator(mode="after")
    def nonempty_condition(self):
        if self.qualification is None and self.expected_status is None:
            raise ValueError("Require a qualification or explicit expected status")
        return self


class ClinicalPatternCandidate(StrictModel):
    disease: DiseaseTerm
    target: SymptomTarget | ExamFindingTarget
    features: list[ClinicalFeatureCandidate]
    evidence: list[SourceSpan] = Field(min_length=1)


class SupportingContextCandidate(StrictModel):
    disease: DiseaseTerm
    context_factor: ContextFactorTerm
    evidence: list[SourceSpan] = Field(min_length=1)


class FindingMethodCandidate(StrictModel):
    finding: ExamFindingTerm
    method: ExamMethodTerm
    evidence: list[SourceSpan] = Field(min_length=1)


class PlannedTestCandidate(StrictModel):
    disease: DiseaseTerm
    test: TestTerm
    evidence: list[SourceSpan] = Field(min_length=1)


class ExtractionResult(StrictModel):
    patterns: list[ClinicalPatternCandidate]
    supporting_contexts: list[SupportingContextCandidate]
    finding_methods: list[FindingMethodCandidate]
    planned_tests: list[PlannedTestCandidate]
