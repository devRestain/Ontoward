from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..rules.limits import LIMITS, SESSION_ORDER, SessionName

RecordCategory = Literal['onset', 'duration', 'course', 'quality', 'aggravating_factor', 'relieving_factor',
    'associated_symptoms', 'previous_care', 'presentation', 'medical_history', 'medication', 'allergy',
    'surgery', 'family_history', 'smoking', 'alcohol', 'occupation', 'patient_context', 'recurrence',
    'measurement', 'social_history', 'developmental_history', 'review_of_systems', 'objective_observation', 'other']
PlanField = Literal['tests', 'treatment', 'disposition', 'follow_up', 'education']
Status = Literal['present', 'absent', 'uncertain', 'unknown']


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


class ObservedNumber(Model):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    kind: Literal['quantity', 'interval']
    value: float | None = None
    unit: str = Field(min_length=1)
    lower: float | None = None
    upper: float | None = None
    upper_unit: str | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    approximate: bool = False

    @property
    def operator(self):
        return 'eq'

    @model_validator(mode='before')
    @classmethod
    def numbers(cls, raw):
        if isinstance(raw, dict):
            if any(type(raw[k]) not in {int, float} for k in ('value', 'lower', 'upper') if raw.get(k) is not None):
                raise ValueError('Observation requires JSON numbers')
            if raw.get('operator', 'eq') != 'eq':
                raise ValueError('An observation cannot invent a comparison')
            raw = {k: v for k, v in raw.items() if k != 'operator'}
        return raw

    @model_validator(mode='after')
    def bounds(self):
        from knowledge.conditions import number
        if self.kind == 'quantity':
            if self.value is None or any(v is not None for v in (self.lower, self.upper, self.upper_unit)):
                raise ValueError('Quantity requires only a value and unit')
        elif self.value is not None or self.lower is None and self.upper is None:
            raise ValueError('Interval requires at least one bound')
        if self.kind == 'interval' and self.lower is not None and self.upper is not None:
            a, b = number(self.lower, self.unit), number(self.upper, self.upper_unit or self.unit)
            if a[0] == b[0] and (a[1] > b[1] or a[1] == b[1] and not (self.lower_inclusive and self.upper_inclusive)):
                raise ValueError('Observation interval is empty or reversed')
        return self

    def signature(self):
        from knowledge.conditions import bounds
        return bounds(self)


class GraphBinding(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    kind: Literal['symptom', 'finding', 'context', 'attribute']
    target: str
    attribute: str | None = None
    values: tuple[str, ...] = ()
    method: Literal['exact', 'broader'] = 'exact'

    @model_validator(mode='after')
    def terms(self):
        if any(v and v.startswith(('urn:', 'http://', 'https://')) for v in (self.target, self.attribute, *self.values)):
            raise ValueError('Patient bindings require clinical terms, not RDF identifiers')
        if self.kind != 'attribute' and (self.attribute or self.values):
            raise ValueError('Target assertions cannot carry attribute values')
        return self


class CaseFact(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str
    graph_binding: GraphBinding | None = None
    value: str = ''
    measurement: ObservedNumber | None = None
    category: RecordCategory | None = None
    context_key: Literal['age', 'sex', 'reporter'] | None = None
    status: Status = 'present'
    subject: Literal['patient', 'family'] = 'patient'
    subject_member: str | None = None
    reported_by: str = 'patient'
    time_context: Literal['current', 'past', 'unspecified'] = 'unspecified'
    observation_id: str | None = None
    episode_id: str | None = None
    acquisition: Literal['initial', 'SAY', 'EXAM'] | None = None
    source_ref: str
    turn: int = 0
    polarity_scope: Literal['general', 'qualified'] = 'general'
    resolves: tuple[str, ...] = ()

    @model_validator(mode='after')
    def atomic(self):
        if self.kind == 'attribute':
            if not self.attribute or bool(self.values) == bool(self.measurement):
                raise ValueError('Attribute requires categorical values or an observed number')
        if not self.graph_binding and (not self.category or not self.value and self.measurement is None):
            raise ValueError('An unbound fact requires a category and normalized content')
        return self

    @property
    def kind(self):
        return self.graph_binding.kind if self.graph_binding else 'note'

    @property
    def target(self):
        return self.graph_binding.target if self.graph_binding else ''

    @property
    def attribute(self):
        return self.graph_binding.attribute if self.graph_binding else None

    @property
    def values(self):
        return self.graph_binding.values if self.graph_binding else ()

    @property
    def binding(self):
        return self.graph_binding.method if self.graph_binding else None

    def key(self):
        return (self.subject, self.subject_member, self.observation_id, self.episode_id,
                self.target, self.attribute, self.time_context, self.polarity_scope,
                self.acquisition if self.kind == 'finding' or self.kind == 'attribute' and self.acquisition == 'EXAM'
                else 'patient_report')


class GraphRef(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    kind: Literal['association', 'feature', 'context', 'symptom']
    id: str
    association_id: str | None = None


class EvidenceRef(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    graph_ref: GraphRef
    fact_ids: tuple[str, ...]


class UnresolvedRef(EvidenceRef):
    scope: tuple[str, ...] = ()
    reason: str = 'unasked'


class DifferentialEntry(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    kind: Literal['disease', 'symptom']
    name: str
    supports: tuple[EvidenceRef, ...] = ()
    against: tuple[EvidenceRef, ...] = ()
    unresolved: tuple[UnresolvedRef, ...] = ()


class Assessment(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    differential: tuple[DifferentialEntry, ...] = ()
    based_on_case_revision: int
    based_on_chief_fact_id: str | None
    based_on_response: str = 'entry'
    frozen: bool = False
    limitations: tuple[str, ...] = ()


class SourceReference(Model):
    document_id: str
    start_byte: int = Field(ge=0)
    end_byte: int = Field(gt=0)


class PlanSentence(Model):
    id: str
    field: PlanField
    text: str = Field(min_length=1)
    basis: Literal['guideline', 'model_knowledge', 'mixed']
    references: tuple[SourceReference, ...] = ()
    priority: Literal['safety', 'routine'] = 'routine'


class CaseState(Model):
    facts: dict[str, CaseFact] = Field(default_factory=dict)
    chief_fact_id: str | None = None
    assessment: Assessment | None = None
    plan: list[PlanSentence] = Field(default_factory=list)
    revision: int = 0

    def primary(self):
        if not self.assessment or not self.assessment.frozen or not self.assessment.differential:
            raise ValueError('A frozen assessment with a primary diagnosis is required')
        return self.assessment.differential[0]

    def fixed_diagnosis(self):
        primary = self.primary()
        return dict(kind=primary.kind, name=primary.name, certainty='working',
            evidence_ids=sorted({i for ref in (*primary.supports, *primary.against) for i in ref.fact_ids}),
            unresolved=list(self.assessment.limitations))

    def active_facts(self):
        suppressed = {ref for f in self.facts.values() if f.status in {'present', 'absent'} for ref in f.resolves
                      if ref in self.facts and self.facts[ref].status in {'unknown', 'uncertain'}}
        return tuple(f for f in self.facts.values() if f.id not in suppressed)

    def current_facts(self):
        facts = self.active_facts()
        groups = {}
        for fact in facts:
            key = fact.key()
            if fact.kind != 'context' and not (fact.observation_id and fact.episode_id):
                key += (fact.id,)
            groups.setdefault(key, []).append(fact)
        conflicts = set()
        for group in groups.values():
            definite = [f for f in group if f.status in {'present', 'absent'}]
            positive = {v for f in definite if f.status == 'present' for v in f.values}
            negative = {v for f in definite if f.status == 'absent' for v in f.values}
            numeric = {str(f.measurement.signature()) for f in definite if f.measurement and f.status == 'present'}
            if (len({f.status for f in definite}) > 1 and not any(f.values for f in definite)
                    or len(numeric) > 1 or positive & negative):
                conflicts.update(f.id for f in group)
        return tuple(f.model_copy(update={'status': 'uncertain'}) if f.id in conflicts else f
                     for f in facts)

    def chief_candidates(self, *, confirmed=False):
        return [f for f in self.current_facts() if f.kind == 'symptom' and f.subject == 'patient'
                and f.time_context != 'past' and f.status in ({'present'} if confirmed else {'present', 'uncertain'})
                and (f.category == 'presentation' or f.id == self.chief_fact_id)]

    def chief(self, *, confirmed=False):
        candidates = self.chief_candidates(confirmed=confirmed)
        return next((f for f in candidates if f.id == self.chief_fact_id),
                    candidates[0] if len(candidates) == 1 else None)

    def select_primary(self, preferred=None):
        if self.assessment and self.assessment.frozen:
            raise ValueError('Clinical information is frozen')
        current = {f.id: f for f in self.chief_candidates()}
        if preferred in current:
            self.chief_fact_id = preferred
        elif self.chief_fact_id not in current:
            self.chief_fact_id = next(iter(current)) if len(current) == 1 else None
        return self.chief()

    def apply(self, facts=(), *, preferred=None):
        if self.assessment and self.assessment.frozen:
            if facts or preferred is not None:
                raise ValueError('Clinical information is frozen')
            return
        changed = any(self.facts.get(f.id) != f for f in facts)
        self.facts.update((f.id, f) for f in facts)
        before = self.chief_fact_id
        self.select_primary(preferred)
        if changed or before != self.chief_fact_id:
            self.revision += 1


class Question(Model):
    item_id: str
    kind: Literal['SAY', 'EXAM'] = 'SAY'
    purpose: Literal['chief', 'intake', 'history', 'hpi', 'open_inquiry', 'ros', 'clarification', 'context', 'feature', 'education']
    text: str
    order: int = 0
    priority: int = 0
    target: str | None = None
    attribute: str | None = None
    observation_id: str | None = None
    episode_id: str | None = None
    subject: Literal['patient', 'family'] = 'patient'
    subject_member: str | None = None
    time_context: Literal['current', 'past', 'unspecified'] = 'unspecified'
    affirmative_presence: bool = False
    answer_type: Literal['presence', 'category', 'quantity', 'duration', 'free_text'] = 'free_text'
    primary_choice: bool = False
    plan_sentence_id: str | None = None
    category: RecordCategory | None = None
    coverage: bool = False
    clarifies_id: str | None = None

    def semantic_key(self):
        return (self.kind, self.target or '', self.attribute or '', self.subject, self.subject_member or '', self.time_context,
                self.observation_id or '', self.episode_id or '')


class Answer(Model):
    question_id: str
    source_ref: str
    scope: SessionName
    purpose: str
    key: tuple[str, ...] = ()
    outcome: Literal['mapped', 'recorded', 'unknown', 'nonclinical', 'not_applicable', 'unsupported', 'conflict', 'delivered', 'undelivered']
    fact_ids: tuple[str, ...] = ()
    category: RecordCategory | None = None
    turn: int | None = None
    coverage: bool = False
    plan_sentence_id: str | None = None
    reason: str | None = None


class InterviewState(Model):
    current: SessionName = 'Initiation'
    status: Literal['uninitialized', 'collecting', 'needs_preparation'] = 'uninitialized'
    queue: list[Question] = Field(default_factory=list)
    answers: list[Answer] = Field(default_factory=list)
    collection: dict[str, str] = Field(default_factory=dict)
    education_status: Literal['not_started', 'complete', 'partial', 'failed', 'disabled'] = 'not_started'
    education_reason: str | None = None


class Usage(Model):
    actions: int = 0


class SessionContext(Model):
    session_id: str
    deadline: datetime
    turns_remaining: int = Field(ge=0, le=LIMITS.turns)
    finalizing: bool = False
    reserve_seconds: int = LIMITS.finalization_seconds
    usage: dict[SessionName, Usage] = Field(default_factory=lambda: {s: Usage() for s in SESSION_ORDER})
    allowed_actions: list[str] = Field(default_factory=lambda: ['SAY', 'EXAM', 'DIAGNOSE'])
    doctor_calls: int = 0
    doctor_successes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    call_limit: int = LIMITS.model_calls
    input_token_limit: int = LIMITS.input_tokens
    output_token_limit: int = LIMITS.output_tokens
    models_available: bool = True
    budget_sync_required: bool = False
    clarifications: int = Field(default=0, ge=0, le=LIMITS.clarifications)
    termination: Literal['submitted', 'failed', 'unknown', 'expired', 'closed'] | None = None
    reason: str | None = None
    receipt: dict[str, object] | None = None


class TurnContext(Model):
    kind: Literal['initial', 'action', 'submission']
    question_id: str | None = None
    request_id: str | None = None
    stage: Literal['selected', 'ready', 'received'] = 'received'
    response: dict[str, object] | None = None
    payload: dict[str, object] | None = None
    repairs: int = Field(default=0, ge=0, le=LIMITS.submission_repairs)
    error: str | None = None


class WorkflowState(Model):
    case: CaseState = Field(default_factory=CaseState)
    interview: InterviewState = Field(default_factory=InterviewState)
    session: SessionContext
    turn: TurnContext | None = None

    def question(self):
        return next((q for q in self.interview.queue if self.turn and q.item_id == self.turn.question_id), None)

    def stop(self, outcome, reason):
        self.session.termination, self.session.reason = outcome, reason
        self.turn = None
