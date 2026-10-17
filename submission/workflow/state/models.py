from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from nova_sdk import RECORD_FIELDS
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from knowledge.conditions import ExpectedValue, FeatureContribution

from ..rules.limits import LIMITS, SESSION_ORDER, SessionName
SOAPField = Literal[
    "S.cc", "S.hpi", "S.pmh", "S.fh", "S.sh", "S.ros", "O.exam", "O.tests",
    "A.evidence", "A.differential", "P.tests", "P.treatment", "P.disposition", "P.follow_up", "P.education",
]
PlanField = Literal["tests", "treatment", "disposition", "follow_up", "education"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RecordDetail(Model):
    quote: str = Field(min_length=1, max_length=160)
    english: str = Field(min_length=1, max_length=160, pattern=r"^[^\r\n]+$")


RecordCategory = Literal["onset", "duration", "course", "quality", "aggravating_factor", "relieving_factor",
    "associated_symptoms", "previous_care", "presentation", "medical_history", "medication", "allergy",
    "surgery", "family_history", "smoking", "alcohol", "occupation", "patient_context", "recurrence",
    "measurement", "social_history", "developmental_history", "review_of_systems", "other"]


class RecordQuantity(Model):
    name: str = Field(min_length=1, max_length=60)
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=30)
    when: str = Field(default="unspecified", min_length=1, max_length=80)
    approximate: bool = False


class PatientContextFact(Model):
    key: Literal["age", "sex", "reporter"]
    value: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=160)


class PatientContextEntry(Model):
    value: str
    quote: str
    source_refs: list[str]


class SpeechSpan(Model):
    quote: str = Field(min_length=1)
    role: Literal["clinical", "nonclinical", "emotion", "request", "conditional"]
    field: SOAPField = "S.hpi"


class ClinicalValue(Model):
    kind: Literal["symptom", "finding", "context", "attribute", "text", "plan", "education"]
    text: str
    status: Literal["present", "absent", "uncertain", "unknown"] = "unknown"
    mapping_status: Literal["exact", "broader", "ambiguous", "unmapped"] = "exact"
    primary_concern: bool = False
    not_applicable: bool = False
    concept_ids: list[str] = Field(default_factory=list)
    observation_id: str | None = None
    episode_id: str | None = None
    attribute_id: str | None = None
    values: list[str] = Field(default_factory=list)
    measurement: ExpectedValue | None = None
    subject: Literal["patient", "family"] = "patient"
    subject_member: str | None = None
    reported_by: str | None = None
    time_context: Literal["current", "past", "unspecified"] = "unspecified"
    record_category: RecordCategory | None = None
    record_details: list[RecordDetail] = Field(default_factory=list, max_length=8)
    quantities: list[RecordQuantity] = Field(default_factory=list, max_length=8)
    evidence_use: Literal["reasoning", "record_only"] = "reasoning"

    @model_validator(mode="after")
    def validate_measurement(self):
        if self.measurement is not None and (self.kind != "attribute" or not self.attribute_id or self.values
                or self.measurement.kind not in {"quantity", "interval"}
                or (self.measurement.kind == "quantity" and self.measurement.operator != "eq")):
            raise ValueError("Observed measurement requires a numeric attribute value")
        return self


class RecordItem(Model):
    id: str
    scope: SessionName
    status: Literal["unasked", "done"] = "unasked"
    value: ClinicalValue | None = None
    source_refs: list[str] = Field(default_factory=list)
    context_refs: list[str] = Field(default_factory=list)
    acquisition: Literal["initial", "SAY", "EXAM"] | None = None
    resolves: list[str] = Field(default_factory=list)


class FixedDiagnosis(Model):
    kind: Literal["disease", "symptom"]
    disease_id: str | None = None
    name: str
    evidence_ids: list[str] = Field(default_factory=list)
    certainty: Literal["working"] = "working"
    unresolved: list[str] = Field(default_factory=list)


class ChiefAnchor(Model):
    record_id: str
    target_id: str
    observation_id: str
    episode_id: str
    time_context: Literal["current", "past", "unspecified"] = "unspecified"


class CaseState(Model):
    S: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["S"]})
    O: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["O"]})
    A: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["A"]})
    P: dict[str, dict[str, RecordItem]] = Field(default_factory=lambda: {key: {} for key in RECORD_FIELDS["P"]})
    diagnosis: str | None = None
    diagnosis_kind: Literal["disease", "symptom"] | None = None
    diagnosis_evidence: list[str] = Field(default_factory=list)
    fixed_diagnosis: FixedDiagnosis | None = None
    primary_chief: ChiefAnchor | None = None
    patient_context: dict[str, PatientContextEntry] = Field(default_factory=dict)
    _locations: dict[str, tuple[str, str]] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def validate_sections(self):
        ids = []
        for section, fields in RECORD_FIELDS.items():
            if set(getattr(self, section)) != set(fields):
                raise ValueError(f"Invalid SOAP section: {section}")
            for records in getattr(self, section).values():
                for key, item in records.items():
                    if key != item.id:
                        raise ValueError("Record key must match its ID")
                    ids.append(key)
        if len(ids) != len(set(ids)):
            raise ValueError("Record IDs must be unique")
        self._locations = {item.id: tuple(field.split(".")) for field, item in self.entries()}
        return self

    def entries(self):
        for section, fields in RECORD_FIELDS.items():
            for field in fields:
                for item in getattr(self, section)[field].values():
                    yield f"{section}.{field}", item

    def get(self, item_id: str) -> RecordItem | None:
        location = self._locations.get(item_id)
        return getattr(self, location[0])[location[1]].get(item_id) if location else None

    def put(self, field: SOAPField, item: RecordItem) -> None:
        self.remove({item.id})
        section, name = field.split(".")
        getattr(self, section)[name][item.id] = item
        self._locations[item.id] = (section, name)

    def remove(self, ids: set[str]) -> None:
        for item_id in ids:
            location = self._locations.pop(item_id, None)
            if location:
                getattr(self, location[0])[location[1]].pop(item_id, None)

    def unasked(self, scope: SessionName) -> list[RecordItem]:
        return [item for _, item in self.entries() if item.scope == scope and item.status == "unasked"]

    @staticmethod
    def evidence_key(value, target=None):
        return (value.subject, value.subject_member, value.observation_id, value.episode_id,
                target if target is not None else tuple(sorted(value.concept_ids)),
                value.attribute_id, value.time_context)

    def current_entries(self):
        entries = list(self.entries())
        groups = {}
        for field, item in entries:
            value = item.value
            if (item.status != "done" or not item.source_refs or value is None
                    or value.kind not in {"symptom", "finding", "attribute", "context"}):
                continue
            for target in value.concept_ids:
                key = (*self.evidence_key(value, target), item.acquisition if field.startswith("O.") else "patient_report")
                # Missing occurrence IDs never join independent symptom episodes.
                if value.kind != "context" and (not value.observation_id or not value.episode_id):
                    key += (item.id,)
                groups.setdefault(key, []).append(item)
        conflicts, superseded = set(), set()
        for items in groups.values():
            resolved_ids = {ident for item in items if item.value.status in {"present", "absent"}
                            for ident in item.resolves}
            superseded.update(i.id for i in items if i.id in resolved_ids and i.value.status in {"unknown", "uncertain"})
            items = [i for i in items if i.id not in superseded]
            definite = [i for i in items if i.value.status in {"present", "absent"} and len(i.value.concept_ids) == 1
                        and i.value.mapping_status in {"exact", "broader"}]
            statuses = {i.value.status for i in definite}
            numeric = {i.value.measurement.signature() for i in definite if i.value.measurement
                       and i.value.status == "present"}
            categorical = any(i.value.kind == "attribute" and i.value.values for i in definite)
            positive = {v for i in definite if i.value.status == "present" for v in i.value.values}
            negative = {v for i in definite if i.value.status == "absent" for v in i.value.values}
            if (len(statuses) > 1 and not categorical) or len(numeric) > 1 or positive & negative:
                conflicts.update(i.id for i in items)
        for field, item in entries:
            if item.id in superseded:
                continue
            if item.id in conflicts or (item.value and item.value.mapping_status in {"ambiguous", "unmapped"}
                                       and item.value.kind in {"symptom", "finding", "attribute", "context"}):
                item = item.model_copy(deep=True)
                item.value.status = "uncertain"
            yield field, item

    def chief_complaints(self, *, confirmed=False) -> list[RecordItem]:
        statuses = {"present"} if confirmed else {"present", "uncertain"}
        return [item for field, item in self.current_entries() if field == "S.cc" and item.status == "done" and item.source_refs
                and item.value and item.value.kind == "symptom" and item.value.subject == "patient"
                and item.value.time_context != "past" and item.value.status in statuses]

    def chief(self, *, confirmed=False):
        candidates = self.chief_complaints(confirmed=confirmed)
        if self.primary_chief:
            matching = [i for i in candidates if i.value.concept_ids == [self.primary_chief.target_id]
                        and i.value.observation_id == self.primary_chief.observation_id
                        and i.value.episode_id == self.primary_chief.episode_id
                        and i.value.time_context == self.primary_chief.time_context]
            return next((i for i in matching if i.id == self.primary_chief.record_id),
                        matching[0] if len(matching) == 1 else None)
        priority = [i for i in candidates if i.value.primary_concern]
        return priority[0] if len(priority) == 1 else candidates[0] if len(candidates) == 1 else None

    def select_primary(self):
        selected = self.chief(confirmed=True) or self.chief()
        if selected is None and self.primary_chief:
            self.primary_chief = None
            selected = self.chief()
        if selected is None or len(selected.value.concept_ids) != 1:
            return None
        value = selected.value
        self.primary_chief = ChiefAnchor(record_id=selected.id, target_id=value.concept_ids[0],
            observation_id=value.observation_id or selected.id, episode_id=value.episode_id or selected.id,
            time_context=value.time_context)
        for item in self.chief_complaints():
            if item.id != selected.id:
                self.put("S.ros", item)
        return self.primary_chief


class Usage(Model):
    actions: int = 0
    empathy_actions: int = 0
    calls: int = 0


class SessionContext(Model):
    session_id: str
    deadline: datetime
    turns_remaining: int = Field(ge=0, le=LIMITS.turns)
    current: SessionName = "Initiation"
    initialized: bool = False
    questions_prepared: bool = False
    finalizing: bool = False
    reserve_seconds: int = LIMITS.finalization_seconds
    usage: dict[SessionName, Usage] = Field(default_factory=lambda: {scope: Usage() for scope in SESSION_ORDER})
    allowed_actions: list[str] = Field(default_factory=lambda: ["SAY", "EXAM", "DIAGNOSE"])
    doctor_calls: int = 0
    doctor_successes: int = 0
    gateway_successes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    call_limit: int = LIMITS.model_calls
    input_token_limit: int = LIMITS.input_tokens
    output_token_limit: int = LIMITS.output_tokens
    models_available: bool = True
    clarifications: int = Field(default=0, ge=0, le=LIMITS.clarifications)

class ScoreContribution(Model):
    association_id: str
    pattern_id: str
    target_id: str
    score: float = Field(ge=0, allow_inf_nan=False)
    evidence_ids: list[str]
    weight_basis: str
    policy_version: str
    feature_deltas: list[FeatureContribution] = Field(default_factory=list)


class Hypothesis(Model):
    disease_id: str
    pattern_ids: list[str] = Field(default_factory=list)
    feature_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    association_ids: list[str] = Field(default_factory=list)
    contributions: list[ScoreContribution] = Field(default_factory=list)
    evidence_score: float = Field(default=0, allow_inf_nan=False)
    chief_score: float = Field(default=0, ge=0, allow_inf_nan=False)
    supporting_raw: float = Field(default=0, ge=0, allow_inf_nan=False)
    supporting_score: float = Field(default=0, ge=0, allow_inf_nan=False)
    context_bonus: int | None = None
    contradiction_penalty: float = Field(default=0, ge=0, allow_inf_nan=False)
    contradiction_ids: list[str] = Field(default_factory=list)
    chief_coverage: float = Field(default=0, ge=0, le=1)
    unresolved_conditions: list[str] = Field(default_factory=list)
    contradicted_conditions: list[str] = Field(default_factory=list)
    potential_patterns: list[str] = Field(default_factory=list)
    incomparable_matches: list[list[str]] = Field(default_factory=list)

    @property
    def score(self) -> float:
        return self.evidence_score + (self.context_bonus or 0) - self.contradiction_penalty

    @property
    def fit_score(self) -> float:
        return self.score


class PatternMatch(Model):
    pattern_id: str
    observation_id: str
    episode_id: str
    time_context: Literal["current", "past", "unspecified"] = "unspecified"
    fingerprint: str
    status: Literal["matched", "contradicted", "incomplete"]
    matched: list[str] = Field(default_factory=list)
    contradicted: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class AssociationMatch(Model):
    association_id: str
    pattern_key: str
    applicability: Literal["matched", "contradicted", "unknown"]
    evidence_ids: list[str] = Field(default_factory=list)


class DifferentialState(Model):
    initialized: bool = False
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    selected_id: str | None = None
    clinical_revision: int = 0
    last_scored_revision: int = -1
    last_fingerprint: str = ""
    pattern_matches: dict[str, PatternMatch] = Field(default_factory=dict)
    association_matches: list[AssociationMatch] = Field(default_factory=list)
    pattern_evaluations: int = 0
    refreshes: int = 0
    search_cache: dict[str, list[str]] = Field(default_factory=dict)


class Question(Model):
    item_id: str
    field: SOAPField
    kind: Literal["SAY", "EXAM"] = "SAY"
    purpose: Literal["chief", "greeting", "intake", "history", "hpi", "open_inquiry", "ros", "clarification", "context", "feature", "education", "empathy"]
    text: str
    order: int
    priority: int
    target_id: str | None = None
    attribute_id: str | None = None
    observation_id: str | None = None
    episode_id: str | None = None
    subject: Literal["patient", "family"] = "patient"
    time_context: Literal["current", "past", "unspecified"] = "unspecified"
    affirmative_presence: bool = False
    answer_type: Literal["presence", "category", "quantity", "duration", "free_text"] = "free_text"
    assessment: dict[str, object] = Field(default_factory=dict)
    primary_choice: bool = False
    plan_sentence_id: str | None = None
    record_category: RecordCategory | None = None
    coverage: bool = False
    clarifies_id: str | None = None

    def semantic_key(self):
        import json
        return json.dumps([self.kind, self.target_id, self.attribute_id, self.subject, self.time_context,
                           self.observation_id, self.episode_id], separators=(",", ":"))


class EducationDelivery(Model):
    question: Question
    status: Literal["pending", "delivered", "undelivered"] = "pending"
    reason: str | None = None
    request_id: str | None = None

    @property
    def id(self):
        return self.question.item_id


class QuestionPlan(Model):
    questions: list[Question] = Field(default_factory=list)
    education: list[EducationDelivery] = Field(default_factory=list)
    last_planned_revision: int = -1
    last_planned_scope: str = ""
    ros_targets: list[str] = Field(default_factory=list)
    ros_initialized: bool = False
    blocked_keys: list[str] = Field(default_factory=list)
    chief_attributes: dict[str, str] = Field(default_factory=dict)
    chief_attribute_reasons: dict[str, str] = Field(default_factory=dict)
    chief_anchor_key: str = ""
    chief_processed: int = 0
    chief_acquired: int = 0
    chief_total: int = 0
    revision: int = 0
    last_plan_key: str = ""
    selection_report: dict[str, object] = Field(default_factory=dict)
    intake: dict[str, str] = Field(default_factory=dict)
    history: dict[str, str] = Field(default_factory=dict)
    context_coverage: list[str] = Field(default_factory=list)
    context_exclusions: dict[str, str] = Field(default_factory=dict)
    session_endings: dict[str, str] = Field(default_factory=dict)


class ActionSpec(Model):
    question: Question
    content: str
    request_id: str
    render_source: Literal["prepared", "empathy", "education"] = "prepared"
    empathy_source_id: str | None = None
    ready: bool = False


class InteractionEntry(Model):
    id: str
    kind: Literal["initial", "SAY", "EXAM", "DIAGNOSE"]
    request: dict[str, object] = Field(default_factory=dict)
    response: dict[str, object] = Field(default_factory=dict)
    turn: int | None = None
    delivered: bool = False
    question: Question | None = None
    attempts: list[dict[str, object]] = Field(default_factory=list)


class EmpathySignal(Model):
    quote: str = Field(min_length=1)
    intent: Literal["new_distress", "renewed_request", "repeat", "acknowledgement"]


class EmpathyEvent(EmpathySignal):
    source_id: str
    status: Literal["pending", "attempted", "delivered", "skipped"] = "pending"
    reason: str | None = None
    request_id: str | None = None


class PatientReport(Model):
    source_id: str
    text: str
    covered_spans: list[tuple[int, int]] = Field(default_factory=list)
    uncovered_spans: list[tuple[int, int]] = Field(default_factory=list)
    clinical_spans: list[tuple[int, int, SOAPField]] = Field(default_factory=list)


class SourceReference(Model):
    document_id: str
    quote: str = Field(min_length=1)
    start_byte: int = Field(ge=0)
    end_byte: int = Field(gt=0)


class PlanSentence(Model):
    id: str
    field: PlanField
    text: str = Field(min_length=1)
    basis: Literal["guideline", "model_knowledge", "mixed"]
    references: list[SourceReference] = Field(default_factory=list)
    priority: Literal["safety", "routine"] = "routine"


class EducationProgress(Model):
    attempted: bool = False
    status: Literal["not_started", "complete", "partial", "failed", "disabled"] = "not_started"
    repairs: int = Field(default=0, ge=0, le=1)
    sentences: list[PlanSentence] = Field(default_factory=list)
    documents: list[dict[str, object]] = Field(default_factory=list)
    notes: list[dict[str, object]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    rendering_attempted: bool = False
    rendering_errors: dict[str, str] = Field(default_factory=dict)


class InteractionState(Model):
    model_history: list[dict[str, object]] = Field(default_factory=list)
    history: list[InteractionEntry] = Field(default_factory=list)
    incoming: dict[str, object] | None = None
    selected: ActionSpec | None = None
    pending: ActionSpec | None = None
    submission_payload: dict[str, object] | None = None
    submission_request_id: str | None = None
    submission_result: dict[str, object] | None = None
    termination: Literal["submitted", "failed", "unknown", "expired", "closed"] | None = None
    reason: str | None = None
    issues: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_target: Question | None = None
    submission_repairs: int = Field(default=0, ge=0, le=LIMITS.submission_repairs)
    submission_error: str | None = None
    parse_rejections: list[dict[str, object]] = Field(default_factory=list)
    parse_recoveries: list[dict[str, object]] = Field(default_factory=list)
    empathy_events: list[EmpathyEvent] = Field(default_factory=list)
    patient_reports: list[PatientReport] = Field(default_factory=list)
    education: EducationProgress = Field(default_factory=EducationProgress)

    def dialogue(self) -> list[dict[str, object]]:
        turns = []
        for entry in self.history:
            if entry.kind == "initial" and entry.response.get("opening"):
                turns.append({"id": entry.id, "kind": "initial", "patient": entry.response["opening"]})
            elif entry.kind == "SAY" and entry.delivered:
                turns.append({"id": entry.id, "kind": "SAY", "turn": entry.turn,
                              "question_id": entry.question.item_id if entry.question else None,
                              "doctor": entry.request["content"], "patient": entry.response.get("content", "")})
        return turns


class WorkflowState(Model):
    case: CaseState = Field(default_factory=CaseState)
    session: SessionContext
    differential: DifferentialState = Field(default_factory=DifferentialState)
    questions: QuestionPlan = Field(default_factory=QuestionPlan)
    interaction: InteractionState = Field(default_factory=InteractionState)

    def unasked(self, scope=None):
        scope = scope or self.session.current
        return [*self.case.unasked(scope), *([item for item in self.questions.education
            if item.status == "pending"] if scope == "Education" else [])]

    def pending_questions(self):
        clinical = [q for q in self.questions.questions if (item := self.case.get(q.item_id))
                    and item.scope == self.session.current and item.status == "unasked"]
        return clinical + ([item.question for item in self.questions.education if item.status == "pending"]
                           if self.session.current == "Education" else [])

    def stop(self, outcome: Literal["failed", "unknown", "expired", "closed"], reason: str) -> None:
        self.interaction.termination = outcome
        self.interaction.reason = reason


class Fact(Model):
    field: SOAPField
    value: ClinicalValue
    quote: str = Field(min_length=1)
    record_id: str | None = None
    context_refs: list[str] = Field(default_factory=list)
    repair_of: int | None = Field(default=None, ge=0)
    correction: bool = False


LookupTerm = Annotated[str, Field(min_length=1, max_length=80)]


class ParsedInput(Model):
    facts: list[Fact] = Field(default_factory=list)
    needs_context: bool = False
    lookup_terms: list[LookupTerm] = Field(default_factory=list, max_length=8)
    clinical_content: bool = True
    empathy: EmpathySignal | None = None
    patient_context: list[PatientContextFact] = Field(default_factory=list, max_length=3)
    spans: list[SpeechSpan] = Field(default_factory=list)


class ParseResult(Model):
    accepted_facts: list[Fact] = Field(default_factory=list)
    rejected_facts: list[dict[str, object]] = Field(default_factory=list)
    unresolved_links: list[int] = Field(default_factory=list)
    needs_context: bool = False
    context_limited: bool = False
    lookup_terms: list[LookupTerm] = Field(default_factory=list, max_length=8)
    clinical_content: bool = True
    empathy: EmpathySignal | None = None
    binding_unresolved: bool = False
    recovery_history: list[dict[str, object]] = Field(default_factory=list)
    patient_context: list[PatientContextFact] = Field(default_factory=list)
    spans: list[SpeechSpan] = Field(default_factory=list)
    truncated: bool = False
    valid_output: bool = False
