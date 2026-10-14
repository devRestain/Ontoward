import json

from nova_sdk import RECORD_FIELDS

from .limits import LIMITS


def validate_payload(state):
    payload = state.interaction.submission_payload
    if not payload or set(payload) != {"note", "diagnosis"}:
        raise ValueError("invalid_submission_payload")
    note, diagnosis = payload["note"], payload["diagnosis"]
    if not isinstance(note, dict) or set(note) != set(RECORD_FIELDS):
        raise ValueError("invalid_soap_fields")
    for section, fields in RECORD_FIELDS.items():
        if not isinstance(note[section], dict) or set(note[section]) != set(fields) or not all(isinstance(v, str) for v in note[section].values()):
            raise ValueError("invalid_soap_fields")
    if note["O"]["tests"] or not any(text.strip() for fields in note.values() for text in fields.values()):
        raise ValueError("invalid_soap_content")
    if not isinstance(diagnosis, str) or not diagnosis.strip() or len(diagnosis.encode("utf-8")) > LIMITS.diagnosis_bytes:
        raise ValueError("invalid_diagnosis")
    if len(json.dumps(note, ensure_ascii=False).encode("utf-8")) > LIMITS.record_bytes:
        raise ValueError("record_too_large")
    if state.session.doctor_successes < 1:
        raise ValueError("doctor_call_required")
    if "DIAGNOSE" not in state.session.allowed_actions:
        raise ValueError("diagnosis_not_allowed")
