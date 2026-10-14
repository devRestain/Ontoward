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


class DiseaseConcept(StrictModel):
    kind: Literal["Disease"]
    term: DiseaseTerm


class SymptomConcept(StrictModel):
    kind: Literal["Symptom"]
    term: SymptomTerm


class ExamFindingConcept(StrictModel):
    kind: Literal["ExamFinding"]
    term: ExamFindingTerm


class AttributeValueConcept(StrictModel):
    kind: Literal["AttributeValue"]
    term: AttributeValueTerm


class ContextFactorConcept(StrictModel):
    kind: Literal["ContextFactor"]
    term: ContextFactorTerm


class TestConcept(StrictModel):
    kind: Literal["Test"]
    term: TestTerm


class ExamMethodConcept(StrictModel):
    kind: Literal["ExamMethod"]
    term: ExamMethodTerm


Concept = (DiseaseConcept | SymptomConcept | ExamFindingConcept | AttributeValueConcept
           | ContextFactorConcept | TestConcept | ExamMethodConcept)


class AtomicClaim(StrictModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    statement: str = Field(min_length=1)
    relation_type: Literal["patterns", "supporting_contexts", "finding_methods", "planned_tests"]
    source_basis: Literal["direct", "differential"]
    concepts: list[Concept] = Field(min_length=2)
    evidence: list[SourceSpan] = Field(min_length=1)

    @model_validator(mode="after")
    def typed_relation(self):
        kinds = [item.kind for item in self.concepts]
        pairs = [(item.kind, item.term.value) for item in self.concepts]
        if len(set(pairs)) != len(pairs) or not self.statement.strip():
            raise ValueError("Require unique concepts and a nonblank statement")
        if self.relation_type == "patterns":
            valid = (kinds.count("Disease") == 1
                     and kinds.count("Symptom") + kinds.count("ExamFinding") == 1
                     and set(kinds) <= {"Disease", "Symptom", "ExamFinding", "AttributeValue"})
        else:
            required = {
                "supporting_contexts": {"Disease", "ContextFactor"},
                "finding_methods": {"ExamFinding", "ExamMethod"},
                "planned_tests": {"Disease", "Test"},
            }[self.relation_type]
            valid = len(kinds) == 2 and set(kinds) == required
        if not valid or (self.source_basis == "differential"
                         and (self.relation_type != "patterns" or len(kinds) != 2)):
            raise ValueError("Require the concept types belonging to one relation")
        return self


class AtomicResult(StrictModel):
    claims: list[AtomicClaim]

    @model_validator(mode="after")
    def unique_claims(self):
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("Duplicate claim_id")
        return self


class CandidateLink(StrictModel):
    candidate: str = Field(pattern=r"^/(patterns|supporting_contexts|finding_methods|planned_tests)/[0-9]+$")
    claim_ids: list[str] = Field(min_length=1)


class ExcludedClaim(StrictModel):
    claim_id: str
    reason: str = Field(min_length=1)


class ConversionResult(StrictModel):
    candidates: ExtractionResult
    links: list[CandidateLink]
    excluded_claims: list[ExcludedClaim]


class GroupContext(StrictModel):
    source_term: str = Field(min_length=1)
    member_diseases: list[DiseaseTerm] = Field(min_length=2)
    evidence: list[SourceSpan] = Field(min_length=1)

    @model_validator(mode="after")
    def defined_group(self):
        if not self.source_term.strip() or len(set(self.member_diseases)) != len(self.member_diseases):
            raise ValueError("Require a nonblank source group and unique approved members")
        return self


class SourceSelection(StrictModel):
    document: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    source_kind: Literal["textbook", "guideline"]
    topic_diseases: list[DiseaseTerm] = Field(min_length=1)
    group_context: GroupContext | None
    topic_evidence: list[SourceSpan] = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1)
    population: str = Field(min_length=1)
    edition: str | None
    conversion_quality: Literal["acceptable"]
    quality_notes: str = Field(min_length=1)
    license_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def reviewed_selection(self):
        if self.end_line < self.start_line or any(not getattr(self, key).strip() for key in
                ("reviewer", "selection_reason", "population", "quality_notes", "license_notes")):
            raise ValueError("Require an ordered range and nonblank source review")
        if len(set(self.topic_diseases)) != len(self.topic_diseases):
            raise ValueError("Require unique reviewed disease topics")
        if self.group_context and not set(self.group_context.member_diseases) <= set(self.topic_diseases):
            raise ValueError("Group members must be reviewed disease topics")
        return self


class ReviewDecision(StrictModel):
    candidate: str = Field(pattern=r"^/(patterns|supporting_contexts|finding_methods|planned_tests)/[0-9]+$")
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1)


class ClinicalReview(StrictModel):
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    decisions: list[ReviewDecision]
