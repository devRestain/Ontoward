from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
import unicodedata
from string import Formatter

from pydantic import BaseModel, ConfigDict, Field
from rdflib import Graph, Namespace, RDF, RDFS, SKOS, URIRef
from .guidelines import GuidelineLibrary

from .conditions import Applicability, AssociationProfile, ExpectedValue, FeatureCondition, QuestionTemplate, TargetScope, AttributeRole, numeric_match

OW = Namespace("urn:ontoward:")


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^5\.0$")
    knowledge_contract: str = Field(pattern=r"^v5-enum-1$")
    build_id: str = Field(min_length=1)
    schema_asset: Asset = Field(alias="schema")
    vocabulary: Asset
    clinical: Asset
    questions: Asset
    guidelines: Asset


class ClinicalKnowledge:
    def __init__(self, graph: Graph, questions=None, attribute_roles=None):
        self._graph = graph
        self.questions = questions or {}
        self.attribute_roles = attribute_roles or {}
        self.guidelines = None
        self._feature_cache, self._profile_cache, self._refinement_cache = {}, {}, {}
        self._target_profiles = self._disease_profiles = self._refinement_parents = None
        self._alias_grams, self._gram_weights, self._alias_phrases, self._labels = {}, {}, {}, {}
        self._label_index = self._concept_cache = self._types = None
        self._term_ids, self._value_ids = {}, {}

    @classmethod
    def load(cls, manifest_path: Path) -> ClinicalKnowledge:
        manifest_path = Path(manifest_path).resolve()
        if not manifest_path.is_file():
            raise ValueError("knowledge_bundle_not_installed")
        manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        root = manifest_path.parent

        def read(asset, suffix):
            relative = Path(asset.path)
            path = (root / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or path.suffix != suffix:
                raise ValueError("Knowledge asset must stay inside its manifest bundle")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != asset.sha256:
                raise ValueError(f"Knowledge digest mismatch: {asset.path}")
            return data

        paths=[(root/asset.path).resolve() for asset in (manifest.schema_asset,manifest.vocabulary,manifest.clinical,manifest.questions,manifest.guidelines)]
        if len(set(paths))!=5 or manifest_path in paths:
            raise ValueError('Knowledge bundle requires five distinct assets')
        graph = Graph()
        for asset in (manifest.schema_asset, manifest.vocabulary, manifest.clinical):
            graph.parse(data=read(asset, ".ttl").decode("utf-8"), format="turtle")
        assets = json.loads(read(manifest.questions, ".json"))
        if not isinstance(assets, dict) or set(assets) != {"questions", "attribute_roles"}:
            raise ValueError("Questions require question contracts and attribute roles")
        knowledge = cls(graph,
            {key: QuestionTemplate.model_validate(value) for key, value in assets["questions"].items()},
            {key: AttributeRole.model_validate(value) for key, value in assets["attribute_roles"].items()})
        knowledge.validate_graph()
        knowledge.validate_vocabulary_endpoints()
        knowledge.validate_question_assets()
        knowledge.prepare_terms()
        knowledge.guidelines = GuidelineLibrary.load(read(manifest.guidelines, ".json"), manifest.build_id,
            {str(node) for node in graph.subjects(RDF.type, OW.Disease)})
        return knowledge

    def attribute_category(self, attribute):
        role = self.attribute_roles.get(attribute)
        return role.category if role else None

    def clarification(self, attribute, default):
        role = self.attribute_roles.get(attribute)
        return role.clarification if role and role.clarification else default

    def execution_time(self, target, rule_scope):
        if rule_scope.time_context != "any":
            return rule_scope.time_context
        if target not in self.questions:
            raise ValueError('Any rule requires a concrete question scope')
        return self.questions[target].time_context

    def prepare_terms(self):
        terms, values = {}, {}
        for kind in ('Symptom', 'ExamFinding', 'ContextFactor', 'FindingAttribute', 'Disease'):
            for node in self._graph.subjects(RDF.type, OW[kind]):
                ident = str(node)
                name = self.label(ident, language='en')
                key = (kind, name)
                if name == ident or key in terms and terms[key] != ident:
                    raise ValueError(f'Ambiguous or missing clinical term: {kind}: {name}')
                terms[key] = ident
        for (kind, name), attribute in terms.items():
            if kind != 'FindingAttribute':
                continue
            for ident in self.get_attribute_values(attribute):
                value = self.label(ident, language='en')
                key = (name, value)
                if value == ident or key in values and values[key] != ident:
                    raise ValueError(f'Ambiguous attribute value: {name}: {value}')
                values[key] = ident
        self._term_ids, self._value_ids = terms, values

    def term_id(self, term, kind):
        return self._term_ids.get((kind, term))

    def value_id(self, attribute, value):
        return self._value_ids.get((attribute, value))

    def term(self, ident):
        return self.label(ident, language='en')

    def label(self, concept_id: str, *, language="ko") -> str:
        key = (concept_id, language)
        if key in self._labels:
            return self._labels[key]
        labels = list(self._graph.objects(URIRef(concept_id), RDFS.label))
        value = str(next((label for label in labels if label.language == language),
            next((label for label in labels if label.language is None), next(iter(labels), concept_id))))
        self._labels[key] = value
        return value

    def has_type(self, concept_id: str, kind: str) -> bool:
        if self._types is not None and concept_id in self._types:
            return str(OW[kind]) in self._types.get(concept_id, set())
        return (URIRef(concept_id), RDF.type, OW[kind]) in self._graph

    def resolve_concept(self, text: str) -> list[str]:
        normalized = self.normalize_alias(text)
        if self._label_index is None:
            self._label_index = {}
            self._alias_phrases = {}
            for predicate in (RDFS.label, SKOS.altLabel):
                for subject, label in self._graph.subject_objects(predicate):
                    alias = self.normalize_alias(str(label))
                    self._label_index.setdefault(alias, set()).add(str(subject))
                    phrase = ' '.join(re.findall(r'[a-z0-9]+|[가-힣]+', unicodedata.normalize('NFC', str(label)).casefold()))
                    self._alias_phrases.setdefault(alias, set()).add(phrase)
            self._alias_grams = {}
            for label in self._label_index:
                for gram in self.lexical_grams(label):
                    self._alias_grams.setdefault(gram, set()).add(label)
            count = len(set().union(*self._label_index.values()))
            self._gram_weights = {gram: 1 + math.log((count + 1) / (1 + len(set().union(
                *(self._label_index[label] for label in labels))))) for gram, labels in self._alias_grams.items()}
        return sorted(self._label_index.get(normalized, set()))

    @staticmethod
    def normalize_alias(text):
        return "".join(unicodedata.normalize("NFC", text).casefold().split())

    @staticmethod
    def lexical_grams(text):
        # Retain Korean syllables as well as adjacent characters. Do not strip
        # particles or infer synonyms; corpus frequency downweights common text.
        return {text[i:i + 2] for i in range(len(text) - 1)} | {c for c in text if '가' <= c <= '힣'}

    def concepts(self, ids=None) -> list[dict[str, object]]:
        if self._concept_cache is None:
            self._concept_cache = {str(subject): {"id": str(subject), "label": self.label(str(subject)), "kind": kind,
                "aliases": sorted({str(name) for predicate in (RDFS.label, SKOS.altLabel)
                                   for name in self._graph.objects(subject, predicate)} - {self.label(str(subject))})}
                for kind in ("Symptom", "ExamFinding", "ContextFactor", "AttributeValue", "FindingAttribute")
                for subject in sorted(set(self._graph.subjects(RDF.type, OW[kind])), key=str)}
        selected = self._concept_cache if ids is None else dict.fromkeys(ids)
        return [dict(self._concept_cache[key]) for key in selected if key in self._concept_cache]

    def search_concepts(self, text: str | list[str], *, kind: str | tuple | None = None) -> list[str]:
        self.resolve_concept("")
        terms = [text] if isinstance(text, str) else text
        queries = list(dict.fromkeys(self.normalize_alias(term) for term in terms if term.strip()))
        phrases = {self.normalize_alias(term): ' '.join(re.findall(r'[a-z0-9]+|[가-힣]+',
            unicodedata.normalize('NFC', term).casefold())) for term in terms}
        kinds = (kind,) if isinstance(kind, str) else kind
        scores, exact = {}, set()
        def weight(items):
            return sum(self._gram_weights.get(gram, 1) for gram in items)
        for index, query in enumerate(queries):
            grams = self.lexical_grams(query)
            query_weight = weight(grams)
            labels = set().union(*(self._alias_grams.get(gram, set()) for gram in grams)) if grams else set()
            for label in labels:
                alias_grams = self.lexical_grams(label)
                shared = grams & alias_grams
                similarity = 2 * weight(shared) / max(1, query_weight + weight(alias_grams))
                if min(len(query), len(label)) >= 4 and any(
                        f' {phrases[query]} ' in f' {phrase} ' or f' {phrase} ' in f' {phrases[query]} '
                        for phrase in self._alias_phrases[label]):
                    similarity = max(similarity, 2 * min(len(query), len(label)) / (len(query) + len(label)))
                for subject in self._label_index[label]:
                    if kinds and not any(self.has_type(subject, k) for k in kinds):
                        continue
                    if label == query:
                        exact.add(subject)
                    row = scores.setdefault(subject, [0.] * len(queries))
                    row[index] = max(row[index], similarity)
        # Aggregate each query's best alias match before applying any result cap.
        # These are lexical retrieval values, never clinical evidence scores.
        ranked = [subject for subject, row in scores.items()
                  if subject in exact or max(row) >= .45 or sum(row) >= .6]
        return sorted(ranked, key=lambda subject: (subject not in exact,
            -sum(scores[subject]), -max(scores[subject]), subject))[:64]

    def get_symptom_attributes(self, symptom_id: str) -> list[str]:
        values = {str(value) for value in self._graph.objects(URIRef(symptom_id), OW.hasAttribute)
                  if self.has_type(str(value), 'FindingAttribute')}
        return sorted(values, key=lambda value: (self.attribute_roles[value].order if value in self.attribute_roles else 1000000, value))

    def get_symptom_systems(self, symptom_id: str) -> list[str]:
        return sorted({str(value) for value in self._graph.objects(URIRef(symptom_id), OW.inSystem)
                       if self.has_type(str(value), "BodySystem")})

    def get_system_symptoms(self, system_id: str) -> list[str]:
        return sorted({str(value) for value in self._graph.subjects(OW.inSystem, URIRef(system_id))
                       if self.has_type(str(value), "Symptom")})

    def get_attribute_values(self, attribute_id: str) -> list[str]:
        if not attribute_id or not self.has_type(attribute_id, 'FindingAttribute'):
            return []
        return sorted(str(value) for value in self._graph.objects(URIRef(attribute_id), OW.canHaveValue)
                      if self.has_type(str(value), 'AttributeValue'))

    def validate_vocabulary_endpoints(self):
        violations = []
        for predicate, domain, range_kind in ((OW.hasAttribute, None, 'FindingAttribute'),
                                             (OW.canHaveValue, 'FindingAttribute', 'AttributeValue')):
            for subject, target in self._graph.subject_objects(predicate):
                if (domain and not self.has_type(str(subject), domain)
                        or not self.has_type(str(target), range_kind)):
                    violations.append((str(subject), str(predicate), str(target)))
        if violations:
            raise ValueError('invalid_vocabulary_endpoints:' + json.dumps(
                dict(count=len(violations), examples=sorted(violations)[:5]), sort_keys=True))

    def numeric_units(self, target_id, attribute_id):
        units = set()
        for profile in self.get_patterns_by_target(target_id):
            for feature in self.get_pattern_features(profile.id):
                expected = feature.expected
                if feature.attribute == attribute_id and expected and expected.kind in {"quantity", "interval"}:
                    units.add(expected.unit)
                    if expected.upper_unit:
                        units.add(expected.upper_unit)
        template = self.question_contract(attribute_id, target_id)
        if template:
            units.update(template.units)
        if template and template.answer_type == "duration":
            units.update({"s", "min", "h", "day", "week", "month", "year"})
        return sorted(units)

    def _profile(self, association) -> AssociationProfile:
        association = URIRef(association)
        if str(association) in self._profile_cache:
            return self._profile_cache[str(association)]
        owners = set(self._graph.subjects(OW.hasAssociation, association))
        if len(owners) != 1:
            raise ValueError("Association requires exactly one disease")
        pattern = self._one(association, OW.pattern)
        profile = AssociationProfile(id=str(pattern), association_id=str(association), disease_id=str(next(iter(owners))),
            target=str(self._one(pattern, OW.targets)),
            applicability=[Applicability.model_validate(item) for item in sorted(json.loads(self._optional(association, OW.applicability) or "[]"), key=lambda item: json.dumps(item, sort_keys=True))],
            target_scope=TargetScope.model_validate_json(str(self._one(association, OW.targetScope))),
            effect=str(self._one(association, OW.diagnosticEffect)))
        self._profile_cache[str(association)] = profile
        return profile

    def get_patterns_by_target(self, finding_id: str) -> list[AssociationProfile]:
        if self._target_profiles is not None:
            return list(self._target_profiles.get(finding_id, []))
        return [self._profile(association)
                for pattern in sorted(self._graph.subjects(OW.targets, URIRef(finding_id)), key=str)
                for association in sorted(self._graph.subjects(OW.pattern, pattern), key=str)]

    def get_disease_patterns(self, disease_id: str) -> list[AssociationProfile]:
        if self._disease_profiles is not None:
            return list(self._disease_profiles.get(disease_id, []))
        return [self._profile(association) for association in sorted(self._graph.objects(URIRef(disease_id), OW.hasAssociation), key=str)]

    def get_pattern_features(self, pattern_id: str) -> list[FeatureCondition]:
        if pattern_id in self._feature_cache:
            return list(self._feature_cache[pattern_id])
        features = []
        for feature in sorted(self._graph.objects(URIRef(pattern_id), OW.hasFeature), key=str):
            node = self._one(feature, OW.expected, required=False)
            expected = ExpectedValue.model_validate_json(str(self._one(node, OW.valueJSON))) if node is not None else None
            features.append(FeatureCondition(id=str(feature), attribute=self._optional(feature, OW.onAttribute),
                                              expected=expected, status=self._optional(feature, OW.expectedStatus)))
        self._feature_cache[pattern_id] = features
        return list(features)

    def value_matches(self, observed: str, expected: str, *, hierarchy=False) -> bool:
        if observed == expected:
            return True
        if hierarchy:
            return any(self.has_type(str(path), "ValueMatch") and self._optional(path, OW.expectedConcept) == expected
                       for path in self._graph.subjects(OW.observedConcept, URIRef(observed)))
        return False

    def feature_refines(self, child: FeatureCondition, parent: FeatureCondition) -> bool:
        if child.attribute != parent.attribute or (parent.status is not None and child.status != parent.status):
            return False
        if parent.expected is None:
            return child.expected is None
        a, b = child.expected, parent.expected
        if a is None:
            return False
        if a.signature() == b.signature():
            return True
        if a.kind in {"quantity", "interval"} and b.kind in {"quantity", "interval"}:
            return numeric_match(b, a) == "matched"
        if a.kind in {"concept", "concept_set"} and b.kind in {"concept", "concept_set"}:
            def clauses(value):
                concepts = [value.concept] if value.kind == "concept" else value.concepts
                result = []
                for concept in concepts:
                    allowed = {concept}
                    if value.match == "subsumption":
                        allowed.update(str(self._one(path, OW.observedConcept)) for path in
                            self._graph.subjects(OW.expectedConcept, URIRef(concept)) if self.has_type(str(path), "ValueMatch"))
                    result.append(allowed)
                return result if value.kind == "concept_set" and value.selection == "all_of" else [set().union(*result)]
            return all(any(c <= p for c in clauses(a)) for p in clauses(b))
        return False

    def pattern_refines(self, child_id: str, parent_id: str) -> bool:
        if self._refinement_parents is not None:
            return parent_id in self._refinement_parents.get(child_id, set())
        key = (child_id, parent_id)
        if key in self._refinement_cache:
            return self._refinement_cache[key]
        child, parent = self.get_pattern_features(child_id), self.get_pattern_features(parent_id)
        if self._one(URIRef(child_id), OW.targets) != self._one(URIRef(parent_id), OW.targets):
            return False
        result = (all(any(self.feature_refines(c, p) for c in child) for p in parent)
                  and not all(any(self.feature_refines(p, c) for p in parent) for c in child))
        if result:
            self._refinement_cache[key] = result
        return result

    def _refinement_edges(self, pattern_ids):
        exact, by_attribute, special, features, signatures = {}, {}, {}, {}, {}
        for pattern in pattern_ids:
            features[pattern] = self.get_pattern_features(pattern)
            signatures[pattern] = {f.signature() for f in features[pattern]}
            for feature in features[pattern]:
                signature = feature.signature()
                exact.setdefault(signature, set()).add(pattern)
                by_attribute.setdefault(feature.attribute, []).append((pattern, feature, signature))
                if feature.expected is not None and (feature.expected.kind != "concept" or feature.expected.match != "exact"):
                    special.setdefault(feature.attribute, []).append((pattern, feature, signature))
        for child in pattern_ids:
            supported = {}
            for feature in features[child]:
                attribute, expected, status = feature.signature()
                for parent_status in {None, status}:
                    signature = (attribute, expected, parent_status or "")
                    for parent in exact.get(signature, set()):
                        supported.setdefault(parent, set()).add(signature)
                if feature.expected is None:
                    continue
                complex_child = feature.expected.kind != "concept" or feature.expected.match != "exact"
                pool = by_attribute if complex_child else special
                for parent, condition, signature in pool.get(feature.attribute, []):
                    if condition.expected is None:
                        continue
                    complex_parent = condition.expected.kind != "concept" or condition.expected.match != "exact"
                    if (complex_child or complex_parent) and self.feature_refines(feature, condition):
                        supported.setdefault(parent, set()).add(signature)
            for parent, matched in supported.items():
                if child != parent and signatures[parent] <= matched and self.pattern_refines(child, parent):
                    yield child, parent

    def get_context_type(self, context_id: str) -> str:
        return str(self._one(URIRef(context_id), OW.contextType))

    def get_exam_methods(self, finding_id: str) -> list[dict[str, str]]:
        return [{"id": str(method), "text": str(self._one(method, OW.examRequestText))}
                for method in sorted(self._graph.objects(URIRef(finding_id), OW.detectedBy), key=str)]

    def question(self, key: str, target_id: str | None = None) -> str:
        template = self.question_contract(key, target_id)
        if template is None or not template.interviewable:
            return ""
        return template.text.replace("{symptom}", self.label(target_id)) if target_id else template.text

    def question_contract(self, key, target_id=None):
        base = self.questions.get(target_id)
        if base is not None and not base.interviewable:
            return base
        return self.questions.get(f"{target_id}|{key}", self.questions.get(key))

    def collection_attributes(self, target, attribute=None):
        """Expand one collection dependency level without creating clinical facts."""
        result = []
        for item in [attribute] if attribute else self.get_symptom_attributes(target):
            template = self.question_contract(item, target)
            result.extend(template.collect_via if template and template.collect_via else [item])
        return list(dict.fromkeys(result))

    def validate_question_assets(self):
        for profile in (p for disease in self._graph.subjects(RDF.type,OW.Disease) for p in self.get_disease_patterns(str(disease))):
            self.execution_time(profile.target,profile.target_scope)
            for condition in profile.applicability:
                self.execution_time(condition.concept_id,condition)
        attributes = {str(node) for node in self._graph.subjects(RDF.type, OW.FindingAttribute)}
        if set(self.attribute_roles) != attributes:
            raise ValueError("Every FindingAttribute requires an explicit role")
        for role in self.attribute_roles.values():
            text = role.clarification
            if text is not None and (unicodedata.normalize("NFC", text) != text
                    or not 1 <= len(text) <= 30 or not re.search("[가-힣]", text)):
                raise ValueError("Prepared clarification must contain 1 to 30 NFC Korean codepoints")
        for key, template in self.questions.items():
            if template.collect_via:
                if '|' not in key:
                    raise ValueError("Collection delegation requires a target-attribute override")
                target, attribute = key.split('|', 1)
                allowed = self.get_symptom_attributes(target)
                if (not any(self.has_type(target, kind) for kind in ('Symptom', 'ExamFinding', 'ContextFactor'))
                        or attribute not in allowed or attribute in template.collect_via
                        or any(component not in allowed for component in template.collect_via)):
                    raise ValueError("Collection components must be direct attributes of the same target")
                for component in template.collect_via:
                    atomic = self.question_contract(component, target)
                    if not atomic or not atomic.interviewable or atomic.collect_via:
                        raise ValueError("Collection components require executable atomic questions without nesting")
            for _, field, spec, conversion in Formatter().parse(template.text):
                if field not in {None, "symptom"} or spec or conversion:
                    raise ValueError("Questions allow only the symptom placeholder")
            if "|" in key:
                target, attribute = key.split("|", 1)
                if attribute not in self.get_symptom_attributes(target):
                    raise ValueError("Question override requires an admitted target attribute")
                pairs = [(attribute, target)]
            elif self.has_type(key, "FindingAttribute"):
                pairs = [(key, str(target)) for target in self._graph.subjects(OW.hasAttribute, URIRef(key))]
            elif any(self.has_type(key, kind) for kind in ("Symptom", "ExamFinding", "ContextFactor")):
                pairs = [(key, key)]
            else:
                raise ValueError("Question identifier is not an admitted interview concept")
            for attribute, target in pairs:
                if not template.interviewable or (target in self.questions and not self.questions[target].interviewable):
                    continue
                text = self.question(attribute, target)
                if unicodedata.normalize("NFC", text) != text or not 1 <= len(text) <= 30 or not re.search('[가-힣]',text):
                    raise ValueError("Prepared question must contain 1 to 30 NFC codepoints")

    def _one(self, subject, predicate, required=True):
        values = list(self._graph.objects(subject, predicate))
        if len(values) > 1 or (required and len(values) != 1):
            raise ValueError(f"Invalid cardinality: {subject} {predicate}")
        return values[0] if values else None

    def _optional(self, subject, predicate):
        value = self._one(subject, predicate, required=False)
        return str(value) if value is not None else None

    def validate_graph(self, *, require_action_assets=True) -> None:
        self._feature_cache.clear()
        self._profile_cache.clear()
        self._refinement_cache.clear()
        self._target_profiles = self._disease_profiles = self._label_index = None
        self._refinement_parents = None
        self._labels.clear()
        self._concept_cache = None
        self._types = None
        if self._optional(OW.OntologySchema, OW.schemaVersion) != "5.0":
            raise ValueError("Knowledge graph requires schema version 5.0")
        if any(list(self._graph.subject_objects(predicate)) for predicate in (OW.hasPattern, OW.expectsValue, OW.clinicalRole, OW.importance)):
            raise ValueError("v5.0 rejects v4.2 ownership, values and manual roles")
        forbidden = ("sourceRef", "predictiveness", "typicality", "strongPredictor", "relationBasis", "derivationScope", "score", "hasSupportingContext")
        if any(list(self._graph.subject_objects(OW[name])) for name in forbidden):
            raise ValueError("Withdrawn clinical metadata is not part of v5-enum-1")
        for pattern in self._graph.subjects(RDF.type, OW.ClinicalPattern):
            target = self._one(pattern, OW.targets)
            associations = set(self._graph.subjects(OW.pattern, pattern))
            if not associations or not all((a, RDF.type, OW.DiseasePatternAssociation) in self._graph for a in associations):
                raise ValueError("Pattern requires an association")
            if sum((target, RDF.type, OW[kind]) in self._graph for kind in ("Symptom", "ExamFinding", "ContextFactor")) != 1:
                raise ValueError("Pattern requires one finding target")
            features = self.get_pattern_features(str(pattern))
            if any(not self.has_type(feature.id, "ClinicalFeature") for feature in features):
                raise ValueError("Pattern features must be typed ClinicalFeature")
            if not features or len({f.signature() for f in features}) != len(features):
                raise ValueError("Pattern requires distinct nonempty feature conditions")
            for parent in self._graph.objects(pattern, OW.refinesPattern):
                if not self.pattern_refines(str(pattern), str(parent)):
                    raise ValueError("Refinement must preserve every parent condition")
        for feature in self._graph.subjects(RDF.type, OW.ClinicalFeature):
            owners = set(self._graph.subjects(OW.hasFeature, feature))
            if len(owners) != 1 or list(self._graph.objects(feature, OW.targets)) or not self.has_type(str(next(iter(owners))), "ClinicalPattern"):
                raise ValueError("Feature must inherit its single pattern target")
            condition = next(f for f in self.get_pattern_features(str(next(iter(owners)))) if f.id == str(feature))
            target = self._one(next(iter(owners)), OW.targets)
            if condition.attribute:
                node = self._one(feature, OW.expected)
                if (not self.has_type(str(node), "ExpectedValue")
                        or self._one(node, OW.valueJSON).datatype != RDF.JSON
                        or not self.has_type(condition.attribute, "FindingAttribute")
                        or (target, OW.hasAttribute, URIRef(condition.attribute)) not in self._graph):
                    raise ValueError("Feature expectation and attribute must be admitted")
                values = [condition.expected.concept] if condition.expected.kind == "concept" else condition.expected.concepts
                if any(not self.has_type(v, "AttributeValue") or (URIRef(condition.attribute), OW.canHaveValue, URIRef(v)) not in self._graph for v in values):
                    raise ValueError("Feature concept value is not admitted for its attribute")
        for path in self._graph.subjects(RDF.type, OW.ValueMatch):
            if self._optional(path, OW.relationKind) not in {"is_a", "regional_part", "approved_region"}:
                raise ValueError("Value match must preserve its relation type")
            for predicate in (OW.observedConcept, OW.expectedConcept):
                if not self.has_type(str(self._one(path, predicate)), "AttributeValue"):
                    raise ValueError("Value match endpoints must be admitted values")
        profiles, identities = [], set()
        for association in self._graph.subjects(RDF.type, OW.DiseasePatternAssociation):
            profile = self._profile(association)
            if not self.has_type(profile.disease_id, "Disease") or not self.has_type(profile.id, "ClinicalPattern"):
                raise ValueError("Association endpoints must be admitted")
            if any(not self.has_type(condition.concept_id, "ContextFactor") for condition in profile.applicability):
                raise ValueError("Applicability requires admitted contexts")
            if self.has_type(profile.target, "ContextFactor"):
                if any(feature.attribute for feature in self.get_pattern_features(profile.id)):
                    raise ValueError("Context targets use presence conditions")
                if (self.get_context_type(profile.target) == "family_history") != (profile.target_scope.subject == "family"):
                    raise ValueError("Context target scope differs from its role")
            if any(condition.concept_id == profile.target for condition in profile.applicability):
                raise ValueError("A target cannot duplicate its applicability")
            identity = (profile.disease_id, profile.id, profile.target_scope.model_dump_json(), tuple(c.model_dump_json() for c in profile.applicability))
            if identity in identities:
                raise ValueError("Duplicate disease-pattern-applicability association")
            identities.add(identity)
            profiles.append(profile)
        self._target_profiles, self._disease_profiles = {}, {}
        for profile in sorted(profiles, key=lambda p: (p.id, p.association_id)):
            self._target_profiles.setdefault(profile.target, []).append(profile)
        for profile in sorted(profiles, key=lambda p: p.association_id):
            self._disease_profiles.setdefault(profile.disease_id, []).append(profile)
        targets = {}
        for profile in profiles:
            targets.setdefault(profile.target,set()).add(profile.id)
        parents = {}
        for patterns in targets.values():
            for child,parent in self._refinement_edges(sorted(patterns)):
                parents.setdefault(child,set()).add(parent)
        self._refinement_parents = parents
        context_types = {"past_medical_history", "surgical_history", "medication_history", "allergy_history",
                         "family_history", "social_history", "occupational_history", "psychosocial_history",
                         "screening_history", "demographic"}
        for context in self._graph.subjects(RDF.type, OW.ContextFactor):
            if self._optional(context, OW.contextType) not in context_types:
                raise ValueError("Invalid ContextFactor type")
        for target, system in self._graph.subject_objects(OW.inSystem):
            if not any(self.has_type(str(target), kind) for kind in ("Symptom", "ExamFinding")) or not self.has_type(str(system), "BodySystem"):
                raise ValueError("Interview system requires a finding and BodySystem endpoints")
        for finding in self._graph.subjects(RDF.type, OW.ExamFinding):
            if not require_action_assets:
                continue
            if not self.get_exam_methods(str(finding)):
                raise ValueError("ExamFinding requires a detection method")
            for method in self.get_exam_methods(str(finding)):
                if unicodedata.normalize("NFC", method["text"]) != method["text"] or not 1 <= len(method["text"]) <= 30 or not re.search('[가-힣]',method['text']):
                    raise ValueError("Prepared examination must contain 1 to 30 NFC codepoints")
        self.concepts()
        self.resolve_concept("")
        self._types = {}
        for subject, kind in self._graph.subject_objects(RDF.type):
            self._types.setdefault(str(subject), set()).add(str(kind))
        self.associations_by_context = {}
        for profile in profiles:
            for condition in profile.applicability:
                key = condition.concept_id
                self.associations_by_context.setdefault(key, []).append(profile)
