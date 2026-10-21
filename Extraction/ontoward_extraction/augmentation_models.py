"""Bounded augmentation contracts. Models never supply parent preconditions."""
from typing import Annotated, Literal

from pydantic import Field, model_validator
from knowledge.conditions import AttributeRole, QuestionTemplate, Strict
from .models import Concept, Relation, ValuePath


class RequiredConcept(Strict):
    name: str
    kind: Literal['ContextFactor', 'FindingAttribute', 'AttributeValue']


class Cluster(Strict):
    id: str
    target_ids: list[str] = Field(min_length=1)
    reference_ids: list[str] = Field(default_factory=list)
    coverage_focus: list[str] = Field(min_length=1)
    required_candidates: list[str] = Field(min_length=1)
    required_concepts: list[RequiredConcept] = Field(default_factory=list)
    instructions: list[str] = Field(min_length=1)


class Limits(Strict):
    max_new_diseases: int = Field(default=6, ge=1, le=12)
    max_new_concepts: int = Field(default=48, ge=1, le=96)
    max_new_relations: int = Field(default=60, ge=1, le=120)
    max_questions: int = Field(default=48, ge=1, le=96)


class Seed(Strict):
    version: Literal['augmentation-seed-1']
    clusters: list[Cluster] = Field(min_length=1, max_length=4)
    limits: Limits = Field(default_factory=Limits)
    replace_association_ids: list[str] = Field(default_factory=list)
    extend_ids: list[str] = Field(default_factory=list)
    question_keys: list[str] = Field(default_factory=list)
    role_ids: list[str] = Field(default_factory=list)


class AddConcept(Strict):
    op: Literal['add_concept'] = 'add_concept'
    concept: Concept


class ExtendConcept(Strict):
    op: Literal['extend_concept'] = 'extend_concept'
    id: str
    before_hash: str
    aliases: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)


class AddRelation(Strict):
    op: Literal['add_relation'] = 'add_relation'
    relation: Relation


class ReplaceRelation(Strict):
    op: Literal['replace_relation'] = 'replace_relation'
    association_id: str
    before_hash: str
    relation: Relation


class RoleChange(Strict):
    attribute_id: str
    before_hash: str | None
    value: AttributeRole


class SetQuestion(Strict):
    op: Literal['set_question'] = 'set_question'
    key: str
    before_hash: str | None
    question: QuestionTemplate
    role: RoleChange | None = None


Operation = Annotated[AddConcept | ExtendConcept | AddRelation | ReplaceRelation | SetQuestion,
                      Field(discriminator='op')]


class Delta(Strict):
    version: Literal['augmentation-delta-1'] = 'augmentation-delta-1'
    operations: list[Operation] = Field(default_factory=list)
    value_matches: list[ValuePath] = Field(default_factory=list)


class ConceptTask(Strict):
    ref: str = Field(pattern=r'^new:[A-Za-z][A-Za-z0-9_:-]*$')
    kind: Literal['Disease', 'Symptom', 'ContextFactor', 'FindingAttribute', 'AttributeValue']
    name: str = Field(min_length=1)
    owner_ref: str | None = None
    reuse_id: str | None = None
    instruction: str = Field(min_length=1)

    @model_validator(mode='after')
    def owner(self):
        if (self.kind == 'AttributeValue') != (self.owner_ref is not None):
            raise ValueError('attribute_value_requires_exact_owner_only')
        return self


class ExtensionTask(Strict):
    id: str
    aliases: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)


class RelationTask(Strict):
    disease_ref: str
    target_ref: str
    replace_association_id: str | None = None
    instruction: str = Field(min_length=1)


class Discovery(Strict):
    job_id: str
    concepts: list[ConceptTask]
    extensions: list[ExtensionTask]
    relations: list[RelationTask]


class ConceptReply(Strict):
    job_id: str
    concept: Concept


class RelationReply(Strict):
    job_id: str
    relation: Relation
    rationale: str = Field(min_length=1)
    evidence_kind: Literal['supplied_knowledge', 'model_medical_knowledge']


class QuestionReply(Strict):
    job_id: str
    question: QuestionTemplate
    attribute_role: AttributeRole | None


class DiscoveryBatch(Strict):
    results: list[Discovery]


class ConceptBatch(Strict):
    results: list[ConceptReply]


class RelationBatch(Strict):
    results: list[RelationReply]


class QuestionBatch(Strict):
    results: list[QuestionReply]


REPLIES = {'augment_discover': (Discovery, DiscoveryBatch),
           'augment_concepts': (ConceptReply, ConceptBatch),
           'augment_relations': (RelationReply, RelationBatch),
           'augment_review': (RelationReply, RelationBatch),
           'augment_questions': (QuestionReply, QuestionBatch)}


def response_schema(phase, job_ids=()):
    schema = REPLIES[phase][1].model_json_schema()

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
    if job_ids:
        schema['$defs'][REPLIES[phase][0].__name__]['properties']['job_id']['enum'] = list(job_ids)
        schema['properties']['results'].update(minItems=len(job_ids), maxItems=len(job_ids))
    return schema
