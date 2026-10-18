"""Explicit protocol doubles, never runtime semantic mapping or quality evidence."""
import json


def context_from_facts(facts, *, patient_context=None, empathy=None):
    statements, anchors = [], {}
    for fact in facts:
        value = fact["value"]
        key = (tuple(value.get("concept_ids", [])), value.get("subject", "patient"), value.get("time_context", "unspecified"))
        status = value.get("status", "unknown")
        row = {"quote": fact["quote"], "role": "clinical" if status in {"present", "absent"} else "unknown",
            "focus": "attribute" if value.get("attribute_id") else "target",
            "assertion": status, "target_terms": value.get("concept_ids", []),
            "attribute_terms": [value["attribute_id"]] if value.get("attribute_id") else [],
            "value_terms": value.get("values", []), "subject": value.get("subject", "patient"),
            "time_context": value.get("time_context", "unspecified"),
            "primary_concern": value.get("primary_concern", False)}
        for field in ("subject_member", "reported_by", "record_category", "measurement", "polarity_scope"):
            if value.get(field) is not None:
                row[field] = value[field]
        if key in anchors:
            row["anchor"] = anchors[key]
        elif not value.get("attribute_id"):
            anchors[key] = len(statements)
        statements.append(row)
    result = {"statements": statements}
    if patient_context:
        result["patient_context"] = patient_context
    if empathy:
        result["empathy"] = empathy
    return result


def mapping_from_contracts(payload):
    result = []
    for statement in payload["statements"]:
        candidates = statement["candidates"]
        target = next((c for c in candidates if c["id"] in statement.get("target_terms", [])), candidates[0] if candidates else None)
        if target is None:
            result.append({})
            continue
        sign = "(+)" if statement["assertion"] == "present" else "(-)"
        if not target["attributes"]:
            result.append({target["id"]: sign})
            continue
        attribute = target["attributes"][0]
        if statement.get("measurement"):
            value = statement["measurement"]
            keys = {"kind", "value", "unit", "operator", "approximate"} if value["kind"] == "quantity" else {
                "kind", "lower", "upper", "unit", "upper_unit", "lower_inclusive", "upper_inclusive", "approximate"}
            value = {k: v for k, v in value.items() if k in keys}
        else:
            values = [v["id"] for v in attribute["values"] if v["id"] in statement.get("value_terms", [])]
            values = values or [v["id"] for v in attribute["values"][:1]]
            if not values:
                result.append({})
                continue
            value = values[0] if len(values) == 1 and sign == "(+)" else {v: sign for v in values}
        result.append({target["id"]: {attribute["id"]: value}})
    return result


def fixture_chat(client, facts, *, empathy=None):
    def chat(messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if payload["task"] == "input_context":
            context = context_from_facts(facts, empathy=empathy)
            by_id = {r["id"]: r for r in payload["records"] if r.get("value")}
            for statement, fact in zip(context["statements"], facts):
                if fact.get("record_id") in by_id:
                    statement["correction_id"] = fact["record_id"]
                    for key in ("observation_id", "episode_id"):
                        if fact["value"].get(key):
                            statement[key] = fact["value"][key]
        else:
            context = mapping_from_contracts(payload)
        return client.completion(json.dumps(context, ensure_ascii=False))
    return chat
