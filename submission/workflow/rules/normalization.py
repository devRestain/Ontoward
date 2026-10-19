import json

from ..state.models import ObservedNumber


def strict_json(content):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite_json_number")

    return json.loads(content, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def statement_outcome(statement):
    if statement.role == "not_applicable":
        return "not_applicable"
    if statement.role in {"unknown", "uncertain"} or (
            statement.role == "clinical" and statement.assertion not in {"present", "absent"}):
        return "unknown"
    if statement.role != "clinical":
        return "nonclinical"
    return None


def concept_rank(knowledge, terms, kinds):
    ranked = []
    ranked.extend(term for term in terms if term.startswith(("urn:", "http://", "https://"))
                  and any(knowledge.has_type(term, kind) for kind in kinds))
    for term in terms:
        ranked.extend(c for c in knowledge.resolve_concept(term)
                      if any(knowledge.has_type(c, kind) for kind in kinds))
    for term in terms:
        for kind in kinds:
            ranked.extend(knowledge.search_concepts(term, kind=kind))
    return list(dict.fromkeys(ranked))


def candidate_contracts(knowledge, statement, question, *, expanded=False, complete=False):
    qtarget = next((v for kind in ('Symptom', 'ContextFactor', 'ExamFinding')
                    if question and (v := knowledge.term_id(question.target, kind))), None)
    qattribute = knowledge.term_id(question.attribute, 'FindingAttribute') if question and question.attribute else None
    if statement.assertion_scope == "domain" or statement.record_category == "patient_context":
        return []
    if statement.record_category == "previous_care" and not any(
            knowledge.has_type(target, "ContextFactor") for term in statement.target_terms
            for target in ([term] if term.startswith(("urn:", "http://", "https://")) else knowledge.resolve_concept(term))):
        return []
    exact_attributes = {attribute for term in statement.attribute_terms
        for attribute in ([term] if term.startswith(("urn:", "http://", "https://")) else knowledge.resolve_concept(term))
        if knowledge.has_type(attribute, "FindingAttribute")}
    if (statement.measurement and statement.record_category in {"course", "recurrence", "previous_care"}
            and not exact_attributes and not (question and qattribute)):
        return []
    is_exam = bool(question and question.kind == "EXAM" or statement.input_segment == 'vital_signs')
    history = statement.record_category in {"medical_history", "medication", "allergy", "surgery",
        "family_history", "smoking", "alcohol", "occupation", "social_history", "developmental_history"}
    kinds = ("ExamFinding",) if is_exam else (("ContextFactor", "Symptom") if history else ("Symptom", "ContextFactor"))
    terms = [*statement.target_terms, statement.quote]
    ranked = concept_rank(knowledge, terms, kinds)
    exact_targets = {target for term in statement.target_terms for target in knowledge.resolve_concept(term)
                     if any(knowledge.has_type(target, kind) for kind in ('Symptom', 'ExamFinding', 'ContextFactor'))}
    if exact_targets:
        ranked = [target for target in ranked if target in exact_targets]
    direct = bool(question and qtarget and statement.subject == question.subject
                  and (not statement.target_terms or qtarget in ranked[:8]))
    if direct and any(knowledge.has_type(qtarget, kind) for kind in kinds):
        ranked = [qtarget, *ranked]
    feature = bool(statement.focus == "attribute" or statement.measurement or direct and (
        qattribute or question.category in {"onset", "course", "recurrence", "previous_care"}
        and statement.record_category == question.category))
    attribute_rank = concept_rank(knowledge, statement.attribute_terms, ("FindingAttribute",)) if feature else []
    value_rank = concept_rank(knowledge, [*statement.value_terms, statement.quote], ("AttributeValue",)) if feature else []
    result = []
    for target in dict.fromkeys(ranked):
        contract = knowledge.questions.get(target)
        if contract and not contract.interviewable:
            aliases = next(iter(knowledge.concepts([target])), {}).get("aliases", [])
            if not any(knowledge.normalize_alias(name) in knowledge.normalize_alias(statement.quote)
                       for name in [knowledge.label(target), *aliases] if name):
                continue
        if knowledge.has_type(target, "ContextFactor"):
            family = knowledge.get_context_type(target) == "family_history"
            if family != (statement.subject == "family"):
                continue
        attrs = []
        if feature:
            allowed = knowledge.get_symptom_attributes(target)
            matched = [a for a in attribute_rank if a in allowed]
            if direct and qattribute:
                matched.insert(0, qattribute)
            if statement.measurement:
                matched = [a for a in matched if statement.measurement.unit in knowledge.numeric_units(target, a)]
                if not matched:
                    matched = [a for a in allowed if statement.measurement.unit in knowledge.numeric_units(target, a)]
            if not matched and statement.value_terms:
                values = set(value_rank)
                matched = [a for a in allowed if values & set(knowledge.get_attribute_values(a))]
            for attribute in dict.fromkeys(a for a in matched if a in allowed):
                values = knowledge.get_attribute_values(attribute)
                ordered = [v for v in value_rank if v in values]
                ordered = list(dict.fromkeys([*ordered, *values]))
                attrs.append({"id": knowledge.term(attribute),
                    "values": [{"id": knowledge.term(v)} for v in ordered[:32 if expanded else 8]],
                    "units": knowledge.numeric_units(target, attribute)})
                if len(attrs) >= (4 if expanded else 2):
                    break
            if not attrs:
                continue
        result.append({"id": knowledge.term(target),
                       "kind": next(k for k in kinds if knowledge.has_type(target, k)), "attributes": attrs})
        if len(result) >= (32 if expanded else 8):
            break
    return result


def measurement_value(measured):
    keys = {"kind", "value", "unit", "operator", "approximate"} if measured.kind == "quantity" else {
        "kind", "lower", "upper", "unit", "upper_unit", "lower_inclusive", "upper_inclusive", "approximate"}
    value = {key: value for key, value in measured.model_dump(exclude_none=True).items() if key in keys}
    if measured.kind == 'quantity':
        value['operator'] = 'eq'
    return value


def validate_mapping(mapping, statement, contracts):
    if not isinstance(mapping, dict) or len(mapping) > 1:
        raise ValueError("mapping_requires_one_target_dictionary")
    if not mapping:
        return []
    if statement_outcome(statement):
        raise ValueError("nonasserted_statement_cannot_create_fact")
    target, value = next(iter(mapping.items()))
    contract = next((c for c in contracts if c["id"] == target), None)
    if contract is None:
        raise ValueError("target_outside_supplied_database")
    sign = "(+)" if statement.assertion == "present" else "(-)"
    if not contract["attributes"]:
        if value != sign:
            raise ValueError("assertion_changed")
        return [(target, None, [], None, statement.assertion)]
    if not isinstance(value, dict) or not value:
        raise ValueError("feature_requires_attribute_dictionary")
    decoded = []
    for attribute, selected in value.items():
        spec = next((a for a in contract["attributes"] if a["id"] == attribute), None)
        if spec is None:
            raise ValueError("attribute_outside_target_contract")
        allowed = {v["id"] for v in spec["values"]}
        if isinstance(selected, str):
            if selected not in allowed or statement.assertion != "present":
                raise ValueError("invalid_or_negated_categorical_value")
            decoded.append((target, attribute, [selected], None, "present"))
        elif isinstance(selected, dict) and selected.get("kind") in {"quantity", "interval"}:
            keys = {"kind", "value", "unit", "operator", "approximate"} if selected["kind"] == "quantity" else {
                "kind", "lower", "upper", "unit", "upper_unit", "lower_inclusive", "upper_inclusive", "approximate"}
            if (set(selected) - keys or not spec["units"] or any(
                    type(selected[k]) not in {int, float} for k in ("value", "lower", "upper")
                    if k in selected and selected[k] is not None)):
                raise ValueError("invalid_numeric_format")
            required = {"kind", "value", "unit", "operator"} if selected["kind"] == "quantity" else {"kind", "unit"}
            if not required <= set(selected):
                raise ValueError("missing_numeric_fields")
            measurement = ObservedNumber.model_validate(selected)
            if (measurement.unit not in spec["units"] or measurement.upper_unit not in {None, *spec["units"]}
                    or measurement.kind == "quantity" and measurement.operator != "eq"
                    or statement.measurement is None or measurement_value(measurement) != measurement_value(statement.measurement)
                    or statement.assertion != "present"):
                raise ValueError("unreported_or_unregistered_numeric_value")
            decoded.append((target, attribute, [], measurement, "present"))
        elif isinstance(selected, dict) and selected and set(selected) <= allowed:
            if any(v != sign for v in selected.values()):
                raise ValueError("feature_assertion_changed")
            decoded.append((target, attribute, list(selected), None, statement.assertion))
        else:
            raise ValueError("value_outside_attribute_contract")
    return decoded


def force_mapping(statement, contracts):
    if statement_outcome(statement):
        return {}
    sign = "(+)" if statement.assertion == "present" else "(-)"
    for target in contracts:
        if not target["attributes"]:
            return {target["id"]: sign}
        for attribute in target["attributes"]:
            if statement.measurement:
                measured = measurement_value(statement.measurement)
                result = {target["id"]: {attribute["id"]: measured}}
                try:
                    validate_mapping(result, statement, [target])
                    return result
                except ValueError:
                    continue
            if attribute["values"]:
                selected = attribute["values"][0]["id"]
                return {target["id"]: {attribute["id"]: selected if sign == "(+)" else {selected: sign}}}
    return {}


def exact_mapping(knowledge, statement, contracts, question):
    if statement_outcome(statement) or not contracts:
        return None
    terms = statement.target_terms
    exact = {knowledge.term(ident) for term in terms for ident in knowledge.resolve_concept(term)
             if any(knowledge.has_type(ident, kind) for kind in ('Symptom', 'ExamFinding', 'ContextFactor'))}
    if question and question.target and statement.subject == question.subject and not terms:
        exact.add(question.target)
    targets = [c for c in contracts if c['id'] in exact]
    if len(targets) != 1:
        return None
    target = targets[0]
    sign = '(+)' if statement.assertion == 'present' else '(-)'
    if not target['attributes']:
        return {target['id']: sign}
    attributes = {knowledge.term(ident) for term in statement.attribute_terms for ident in knowledge.resolve_concept(term)
                  if knowledge.has_type(ident, 'FindingAttribute')}
    if question and question.attribute and not statement.attribute_terms:
        attributes.add(question.attribute)
    choices = [a for a in target['attributes'] if a['id'] in attributes]
    if len(choices) != 1:
        return None
    attribute = choices[0]
    if statement.measurement:
        mapping = {target['id']: {attribute['id']: measurement_value(statement.measurement)}}
    else:
        aid = knowledge.term_id(attribute['id'], 'FindingAttribute')
        allowed = set(knowledge.get_attribute_values(aid))
        selected = {knowledge.term(ident) for term in statement.value_terms for ident in knowledge.resolve_concept(term)
                    if ident in allowed}
        if not selected:
            return None
        values = sorted(selected)
        value = values[0] if len(values) == 1 and sign == '(+)' else dict.fromkeys(values, sign)
        mapping = {target['id']: {attribute['id']: value}}
    try:
        validate_mapping(mapping, statement, [target])
        return mapping
    except ValueError:
        return None
