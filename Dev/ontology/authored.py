from __future__ import annotations

from datetime import date
import json
import unicodedata
from typing import Literal as TypeLiteral

from pydantic import BaseModel, ConfigDict, Field, model_validator
from rdflib import Literal, RDF, SKOS, URIRef

from submission.knowledge.conditions import Applicability, ExpectedValue, QuestionTemplate
from .v5 import OW, digest


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    author: str = Field(min_length=1)
    date: str
    assertion: str = Field(min_length=1)
    references: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source(self):
        date.fromisoformat(self.date)
        if not self.author.strip() or not self.assertion.strip():
            raise ValueError("Authored records require an author and an explicit assertion")
        return self


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    attribute: str | None = None
    expected: ExpectedValue | None = None
    status: TypeLiteral["present", "absent"] | None = None

    @model_validator(mode="after")
    def validate_feature(self):
        if bool(self.attribute) != bool(self.expected) or (not self.attribute and self.status is None):
            raise ValueError("Authored features require a complete typed condition")
        return self


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    type: TypeLiteral["concept", "alias", "attribute", "association", "examination"]
    source: Source
    id: str | None = None
    kind: TypeLiteral["Symptom", "ContextFactor", "ExamFinding"] | None = None
    label: str | None = None
    korean: str | None = None
    snomed_id: str | None = None
    mapping_relation: TypeLiteral["exact", "broader", "narrower", "unmapped"] = "unmapped"
    context_type: str | None = None
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    question: QuestionTemplate | None = None
    target: str | None = None
    attribute: str | None = None
    values: list[dict[str, str]] = Field(default_factory=list)
    disease: str | None = None
    features: list[Feature] = Field(default_factory=list)
    applicability: list[Applicability] = Field(default_factory=list)
    support: float | None = Field(default=None, ge=0, le=4)
    method: str | None = None
    request: str | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        fields = {
            "concept": {"id", "kind", "label", "korean", "snomed_id", "mapping_relation", "context_type", "aliases", "question"},
            "alias": {"target", "aliases"},
            "attribute": {"target", "attribute", "label", "korean", "question", "values"},
            "association": {"disease", "target", "features", "applicability", "support"},
            "examination": {"target", "method", "label", "request"},
        }
        if self.model_fields_set - fields[self.type] - {"type", "source"}:
            raise ValueError("Authored record contains fields that its type cannot express")
        for text in (self.label, self.korean, self.request):
            if text is not None and (not text.strip() or text != unicodedata.normalize("NFC", text)):
                raise ValueError("Authored labels and requests require nonempty NFC text")
        if self.question and self.question.interviewable and not 1 <= len(self.question.text) <= 30:
            raise ValueError("Prepared questions require 1 to 30 codepoints")
        if self.type == "alias" and not self.aliases:
            raise ValueError("An alias record requires aliases")
        return self


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate authored JSON key: " + key)
        result[key] = value
    return result


def read_entries(path):
    entries = []
    for line, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if text.strip():
            value = json.loads(text, object_pairs_hook=strict_object)
            entries.append((line, Entry.model_validate(value)))
    return entries


def aliases(builder, uri, values, reference):
    if set(values) - {"en", "ko"}:
        raise ValueError("Aliases require an explicit supported language")
    entry = builder.registry[uri]
    for language, names in values.items():
        for name in names:
            if not name.strip() or name != unicodedata.normalize("NFC", name):
                raise ValueError("An alias requires nonempty NFC text")
            builder.vocabulary.add((URIRef(uri), SKOS.altLabel, Literal(name, lang=language)))
            sources = entry.setdefault("alias_sources", {}).setdefault(language + ":" + name, [])
            if reference not in sources:
                sources.append(reference)


def apply(builder, entries, questions, *, source_name, terminology=None):
    retained, attributes, provenance = set(), set(), []

    def require(uri, *kinds):
        if not uri or not uri.startswith("urn:ontoward:") or not any(
                (URIRef(uri), RDF.type, OW[kind]) in builder.vocabulary for kind in kinds):
            raise ValueError("Authored endpoint has no compatible admitted role: " + str(uri))

    for line, record in entries:
        raw = record.model_dump(exclude_none=True)
        reference = "authored:" + digest([source_name, line, raw])
        provenance.append({"source_ref": reference, "file": source_name, "line": line, **raw})
        uri = record.id or record.target
        if record.type == "concept":
            if not uri or not uri.startswith("urn:ontoward:") or not record.kind or not record.label:
                raise ValueError("Authored concepts require a local identifier, role and English label")
            if record.snomed_id and (record.mapping_relation == "unmapped" or terminology is None
                                      or not terminology.active(record.snomed_id)):
                raise ValueError("An authored SCTID requires an explicit active source mapping")
            builder.concept(uri, record.kind, record.label, korean=record.korean,
                snomed_id=record.snomed_id if record.mapping_relation == "exact" else None, source_refs=[reference])
            builder.registry[uri].update(source_role="authored_judgment", author_source=record.source.model_dump(),
                                         mapping_relation=record.mapping_relation, referenced_snomed_id=record.snomed_id)
            if record.kind == "ContextFactor":
                if not record.context_type:
                    raise ValueError("Authored history requires a context type")
                builder.vocabulary.set((URIRef(uri), OW.contextType, Literal(record.context_type)))
            if record.question:
                questions[uri] = record.question.model_dump()
            aliases(builder, uri, record.aliases, reference)
            retained.add(uri)
        elif record.type == "alias":
            require(uri, "Symptom", "ExamFinding", "ContextFactor", "FindingAttribute", "AttributeValue")
            aliases(builder, uri, record.aliases, reference)
        elif record.type == "attribute":
            require(record.target, "Symptom", "ExamFinding")
            if not record.attribute or not record.attribute.startswith("urn:ontoward:") or not record.label or not record.question:
                raise ValueError("Authored attributes require an identifier, label and question contract")
            builder.concept(record.attribute, "FindingAttribute", record.label, korean=record.korean, source_refs=[reference])
            builder.vocabulary.add((URIRef(record.target), OW.hasAttribute, URIRef(record.attribute)))
            for value in record.values:
                if set(value) - {"id", "label", "korean"} or not value.get("id", "").startswith("urn:ontoward:") or not value.get("label"):
                    raise ValueError("Authored values require local identifiers and canonical labels")
                builder.concept(value["id"], "AttributeValue", value["label"], korean=value.get("korean"), source_refs=[reference])
                builder.vocabulary.add((URIRef(record.attribute), OW.canHaveValue, URIRef(value["id"])))
            questions[record.target + "|" + record.attribute] = record.question.model_dump()
            attributes.add((record.target, record.attribute))
            retained.add(record.target)
        elif record.type == "association":
            require(record.disease, "Disease")
            require(record.target, "Symptom", "ExamFinding")
            for feature in record.features:
                if feature.attribute:
                    require(feature.attribute, "FindingAttribute")
                    if (URIRef(record.target), OW.hasAttribute, URIRef(feature.attribute)) not in builder.vocabulary:
                        raise ValueError("Authored scoring cannot invent an attribute binding")
                    expected = feature.expected
                    values = [expected.concept] if expected.kind == "concept" else expected.concepts
                    if any((URIRef(feature.attribute), OW.canHaveValue, URIRef(value)) not in builder.vocabulary for value in values):
                        raise ValueError("Authored scoring cannot invent an allowed value")
                    if expected.kind in {"quantity", "interval"}:
                        template = questions.get(record.target + "|" + feature.attribute) or questions.get(feature.attribute)
                        template = QuestionTemplate.model_validate(template) if template else None
                        units = set(template.units) if template else set()
                        if template and template.answer_type == "duration":
                            units.update({"s", "min", "h", "day", "week", "month", "year"})
                        if expected.unit not in units or expected.upper_unit not in {None, *units}:
                            raise ValueError("Authored scoring requires an explicitly registered numeric format")
            for condition in record.applicability:
                require(condition.concept_id, "ContextFactor")
            pattern = builder.pattern(record.target, [f.model_dump(exclude_none=True) for f in record.features])
            builder.association(record.disease, pattern, source_ref=reference, relation_basis="authored_association",
                predictiveness=None if record.support is None else str(record.support),
                applicability=[item.model_dump() for item in record.applicability], raw=raw)
        else:
            require(record.target, "ExamFinding")
            if not record.method or not record.method.startswith("urn:ontoward:") or not record.label or not record.request:
                raise ValueError("Authored examinations require a named method and explicit request")
            builder.concept(record.method, "ExamMethod", record.label, source_refs=[reference])
            builder.vocabulary.add((URIRef(record.target), OW.detectedBy, URIRef(record.method)))
            builder.vocabulary.set((URIRef(record.method), OW.examRequestText, Literal(record.request)))
            retained.add(record.target)
    return retained, attributes, provenance
