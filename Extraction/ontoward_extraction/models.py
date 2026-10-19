import hashlib
import json
import unicodedata
import re
from typing import Literal

from pydantic import Field, model_validator
from knowledge.conditions import Strict, ExpectedValue, TargetScope, Applicability, QuestionTemplate, AttributeRole

CONTRACT = 'v5-enum-1'
KINDS = ('Disease', 'Symptom', 'ExamFinding', 'ContextFactor', 'Test', 'ExamMethod', 'BodySystem', 'FindingAttribute', 'AttributeValue')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identifier(kind, value):
    return 'urn:ontoward:' + kind + digest(value)[:24]


class Concept(Strict):
    id: str
    kind: Literal['Disease', 'Symptom', 'ExamFinding', 'ContextFactor', 'Test', 'ExamMethod', 'BodySystem', 'FindingAttribute', 'AttributeValue']
    name: str = Field(min_length=1)
    korean: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    context_type: str | None = None
    exam_method: str | None = None
    exam_text: str | None = None
    question: QuestionTemplate | None = None
    attribute_role: AttributeRole | None = None

    @model_validator(mode='after')
    def labels(self):
        if not self.id.strip() or not self.name.strip() or re.search('[가-힣]',self.name) or self.name.startswith(('urn:','http:','https:')):
            raise ValueError('Require a nonempty identifier and normalized English canonical name')
        if not self.korean.strip() or self.korean.startswith(('urn:','http:','https:')) or unicodedata.normalize('NFC',self.korean)!=self.korean:
            raise ValueError('Require a nonempty NFC Korean display label')
        return self


class Condition(Strict):
    status: Literal['present', 'absent'] | None = None
    attribute: str | None = None
    expected: ExpectedValue | None = None

    @model_validator(mode='after')
    def pair(self):
        if bool(self.attribute) != bool(self.expected) or not self.attribute and self.status is None:
            raise ValueError('Require presence or a paired attribute expectation')
        return self


class Relation(Strict):
    disease_id: str
    target_id: str
    target_scope: TargetScope
    applicability: list[Applicability] = Field(default_factory=list)
    features: list[Condition] = Field(min_length=1)
    effect: Literal['support', 'strong_support', 'against', 'strong_against', 'neutral']

    def meaning(self):
        value = self.model_dump()
        value.pop('effect')
        value['features'] = sorted([dict(status=f.status,attribute=f.attribute,expected=f.expected.signature() if f.expected else None) for f in self.features], key=canonical)
        value['applicability'] = sorted(value['applicability'], key=canonical)
        return digest(value)


class ValuePath(Strict):
    observed: str
    expected: str
    relation: Literal['is_a', 'regional_part', 'approved_region']


class Result(Strict):
    job_id: str
    concepts: list[Concept] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    value_matches: list[ValuePath] = Field(default_factory=list)


class Batch(Strict):
    results: list[Result]


def response_schema():
    schema = Batch.model_json_schema()

    def strict(value):
        if isinstance(value, dict):
            value.pop('default', None)
            if value.get('type') == 'object':
                value['additionalProperties'] = False
                value['required'] = list(value.get('properties', {}))
            for item in value.values():
                strict(item)
        elif isinstance(value, list):
            for item in value:
                strict(item)
    strict(schema)
    return schema
