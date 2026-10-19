from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .state.models import CaseFact, Model, ObservedNumber, RecordCategory


class EmpathySignal(Model):
    quote: str = Field(min_length=1)
    intent: Literal['new_distress', 'renewed_request', 'repeat', 'acknowledgement']
    emotion: Literal['fear', 'anxiety', 'pain', 'frustration', 'sadness', 'other'] = 'other'


class PatientContextFact(Model):
    key: Literal['age', 'sex', 'reporter']
    value: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1)
    subject: Literal['patient', 'family'] = 'patient'
    subject_member: str | None = None
    measurement: ObservedNumber | None = None
    correction: bool = False

    @model_validator(mode='after')
    def demographic_scope(self):
        if self.subject=='patient' and self.subject_member is not None:
            raise ValueError('Patient demographics cannot name a family member')
        if self.measurement and (self.key!='age' or self.measurement.unit not in {'year','month','week','day'}
                or self.measurement.upper_unit not in {None,'year','month','week','day'}
                or any(v is not None and v<0 for v in (self.measurement.value,self.measurement.lower,self.measurement.upper))):
            raise ValueError('Age requires a nonnegative reported age unit')
        return self


class ContextStatement(Model):
    quote: str = Field(min_length=1)
    input_segment: Literal['opening', 'vital_signs'] | None = None
    role: Literal['clinical', 'nonclinical', 'question', 'emotion', 'conditional', 'uncertain', 'unknown', 'not_applicable']
    focus: Literal['target', 'attribute'] = 'target'
    assertion: Literal['present', 'absent', 'uncertain', 'unknown'] = 'unknown'
    target_terms: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=8)
    attribute_terms: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=4)
    value_terms: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=4)
    subject: Literal['patient', 'family'] = 'patient'
    subject_member: str | None = Field(default=None,
        pattern=r'^(mother|father|brother|sister|son|daughter|grandmother|grandfather|spouse|sibling|relative|other)(_[0-9]+)?$')
    reported_by: Literal['patient', 'mother', 'father', 'family', 'caregiver', 'unknown'] = 'patient'
    time_context: Literal['current', 'past', 'unspecified'] = 'unspecified'
    observation_id: str | None = None
    episode_id: str | None = None
    anchor: int | None = Field(default=None, ge=0)
    record_category: RecordCategory | None = None
    primary_concern: bool = False
    correction_id: str | None = None
    polarity_scope: Literal['general', 'qualified'] = 'general'
    assertion_scope: Literal['specific', 'domain'] = 'specific'
    measurement: ObservedNumber | None = None
    note_value: str | None = Field(default=None, max_length=240, pattern=r'^[^\r\n]*$')

    @field_validator('note_value')
    @classmethod
    def normalized_content(cls, value):
        if value and (not re.search('[A-Za-z]', value) or re.search('[가-힣]', value)
                or value.startswith(('urn:', 'http://', 'https://'))):
            raise ValueError('Normalized content requires English clinical text')
        return value


class ContextInput(Model):
    statements: list[ContextStatement] = Field(default_factory=list)
    patient_context: list[PatientContextFact] = Field(default_factory=list, max_length=8)
    empathy: EmpathySignal | None = None


@dataclass
class InputResult:
    facts: list[CaseFact] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    empathy: EmpathySignal | None = None
    preferred: str | None = None
