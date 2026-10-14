import json
from uuid import uuid4

from knowledge.graph import ClinicalKnowledge
from nova_sdk import RECORD_FIELDS, NovaError

from .session import SessionController, sdk_failure
from .state import ClinicalValue, InteractionEntry, RecordItem, WorkflowState
from .transport import request_with_recovery


class SubmissionAgent:
    def __init__(self, client, knowledge: ClinicalKnowledge, config):
        self.client = client
        self.knowledge = knowledge
        self.config = config

    def _describe(self, item) -> str:
        value = item.value
        if value is None:
            return ""
        labels = [self.knowledge.label(concept) for concept in value.concept_ids]
        if value.attribute_id:
            labels.append(self.knowledge.label(value.attribute_id))
        texts = self.config.texts
        status = texts.status_labels[value.status]
        if value.kind == "education":
            return texts.education_format.format(text=value.text)
        if value.kind == "plan":
            return texts.plan_format.format(text=value.text)
        if labels:
            return texts.finding_format.format(labels=texts.label_separator.join(labels), status=status, text=value.text)
        return value.text if value.status == "present" else texts.unlinked_format.format(text=value.text, status=status)

    def render_soap(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        if state.interaction.pending:
            state.stop("unknown", "pending_action_at_finalization")
            return
        evidence = [state.case.get(item_id) for item_id in state.case.diagnosis_evidence]
        evidence = [item for item in evidence if item and item.source_refs and item.value]
        texts = self.config.texts
        evidence_text = texts.record_separator.join(self._describe(item) for item in evidence)
        if state.case.diagnosis_kind == "symptom":
            evidence_text = texts.record_separator.join(filter(None, (evidence_text, texts.symptom_assessment)))
        summaries = {"evidence": evidence_text, "differential": texts.record_separator.join(
            self.knowledge.label(item.disease_id) for item in state.differential.hypotheses[1:])}
        for field, text in summaries.items():
            state.case.put(f"A.{field}", RecordItem(id=f"assessment:{field}", scope="Education", status="done",
                value=ClinicalValue(kind="text", text=text, status="present"),
                source_refs=sorted({ref for item in evidence for ref in item.source_refs}) if field == "evidence" else []))
        note = {section: {field: "" for field in fields} for section, fields in RECORD_FIELDS.items()}
        for field, item in state.case.entries():
            section, name = field.split(".")
            if item.status == "done" and item.value and (section in {"A", "P"} or item.source_refs):
                text = self._describe(item)
                if text:
                    if field == "O.exam":
                        turns = sorted({entry.turn for entry in state.interaction.history if entry.id in item.source_refs
                                        and entry.kind == "EXAM" and entry.delivered and entry.turn is not None})
                        if turns:
                            text = texts.exam_turn_format.format(text=text, turn=", ".join(map(str, turns)))
                        elif "initial" in item.source_refs:
                            text = texts.initial_exam_format.format(text=text)
                    note[section][name] += (texts.record_separator if note[section][name] else "") + text
        note["O"]["tests"] = ""
        state.interaction.submission_payload = {"note": note, "diagnosis": state.case.diagnosis}

    def validate_submission(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        state.interaction.submission_error = None
        payload = state.interaction.submission_payload
        try:
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
            if not isinstance(diagnosis, str) or not diagnosis.strip() or len(diagnosis.encode("utf-8")) > 500:
                raise ValueError("invalid_diagnosis")
            if len(json.dumps(note, ensure_ascii=False).encode("utf-8")) > 100000:
                raise ValueError("record_too_large")
            if state.session.doctor_successes < 1:
                raise ValueError("doctor_call_required")
            if "DIAGNOSE" not in state.session.allowed_actions:
                raise ValueError("diagnosis_not_allowed")
        except (KeyError, TypeError, ValueError) as error:
            state.interaction.submission_error = str(error)
            if state.interaction.submission_repairs or str(error) in {"doctor_call_required", "diagnosis_not_allowed"}:
                state.stop("failed", str(error))

    def submit_diagnosis(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        entry = None
        try:
            SessionController().refresh(state, self.client, final=True)
            if state.interaction.termination:
                return
            self.validate_submission(state)
            if state.interaction.termination or state.interaction.submission_error:
                return
            interaction = state.interaction
            interaction.submission_request_id = interaction.submission_request_id or str(uuid4())
            request = {**interaction.submission_payload, "request_id": interaction.submission_request_id}
            entry = InteractionEntry(id=interaction.submission_request_id, kind="DIAGNOSE", request=request)
            interaction.history.append(entry)
            result = request_with_recovery(state, self.client, self.client.diagnose, request, entry.attempts, final=True)
            entry.response = result
            interaction.submission_result = result
        except NovaError as error:
            if entry:
                entry.response = {"error": error.code}
            if error.code == "INVALID_RECORD_FIELDS" and state.interaction.submission_repairs == 0:
                state.interaction.submission_error = error.code
            else:
                sdk_failure(state, error)
        except (TypeError, ValueError):
            state.stop("unknown", "invalid_submission_response")

    def confirm_submission(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        result = state.interaction.submission_result
        if isinstance(result, dict) and result.get("status") == "completed":
            state.interaction.termination = "submitted"
        else:
            state.stop("unknown", "unconfirmed_submission")
