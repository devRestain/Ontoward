from knowledge.graph import ClinicalKnowledge
from nova_sdk import RECORD_FIELDS, NovaError

from .clinical_reasoner import ClinicalReasoner
from .rules.action import failure_outcome
from .rules.limits import LIMITS
from .rules.submission import validate_payload
from .state.models import ClinicalValue, RecordItem, WorkflowState


class SubmissionWriter:
    def __init__(self, client, knowledge: ClinicalKnowledge, config, executor, nova_session, interactions, new_request_id):
        self.client = client
        self.knowledge = knowledge
        self.config = config
        self.executor = executor
        self.nova_session = nova_session
        self.interactions = interactions
        self.new_request_id = new_request_id

    def _describe_record(self, item, episodes=None) -> str:
        value = item.value
        if value is None:
            return ""
        texts = self.config.texts
        status = texts.status_labels[value.status]
        if value.kind == "education":
            return texts.education_format.format(text=value.text)
        if value.kind == "plan":
            return texts.plan_format.format(text=value.text)
        labels = [self.knowledge.label(concept) for concept in [*value.concept_ids,
                  *([value.attribute_id] if value.attribute_id else []), *value.values]]
        labels = [label for label in labels if not label.startswith("urn:")]
        if value.measurement:
            measured = value.measurement
            unit = texts.unit_labels.get(measured.unit, measured.unit)
            if measured.kind == "quantity":
                labels.append(texts.measurement_format.format(operator=texts.operator_labels[measured.operator],
                              value=f"{measured.value:g}", unit=unit))
            else:
                upper_unit = texts.unit_labels.get(measured.upper_unit, measured.upper_unit) if measured.upper_unit else unit
                labels.append(texts.interval_format.format(lower_bound="[" if measured.lower_inclusive else "(",
                              upper_bound="]" if measured.upper_inclusive else ")",
                              lower=f"{measured.lower:g} {unit}" if measured.lower is not None else "−∞",
                              upper=f"{measured.upper:g} {upper_unit}" if measured.upper is not None else "∞"))
        if value.kind in {"symptom", "finding", "context", "attribute"} or value.concept_ids or value.attribute_id:
            episode = ""
            if value.episode_id:
                episodes = episodes if episodes is not None else {}
                key = (value.subject, value.episode_id)
                number = episodes.setdefault(key, len(episodes) + 1)
                episode = texts.episode_format.format(number=number)
            labels.append(texts.clinical_context_format.format(subject=texts.subject_labels[value.subject],
                          time=texts.time_labels[value.time_context], episode=episode))
        if labels:
            return texts.finding_format.format(labels=texts.label_separator.join(labels), status=status, text=value.text)
        return value.text if value.status == "present" else texts.unlinked_format.format(text=value.text, status=status)

    def build_soap(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        if state.interaction.pending:
            state.stop("unknown", "pending_action_at_finalization")
            return
        evidence = [state.case.get(item_id) for item_id in state.case.diagnosis_evidence]
        evidence = [item for item in evidence if item and item.source_refs and item.value
                    and item.value.status in {"present", "absent"}]
        texts = self.config.texts
        episodes = {}
        for _, item in state.case.entries():
            if item.value and item.value.episode_id:
                episodes.setdefault((item.value.subject, item.value.episode_id), len(episodes) + 1)
        evidence_text = texts.record_separator.join(self._describe_record(item, episodes) for item in evidence)
        if state.case.diagnosis_kind == "symptom":
            evidence_text = texts.record_separator.join(filter(None, (evidence_text, texts.symptom_assessment)))
        alternatives = [self.knowledge.label(item.disease_id) for item in ClinicalReasoner.supported_hypotheses(state)
                        if item.disease_id != state.differential.selected_id]
        summaries = {"evidence": evidence_text, "differential": texts.record_separator.join(alternatives[:LIMITS.differential_display])}
        for field, text in summaries.items():
            state.case.put(f"A.{field}", RecordItem(id=f"assessment:{field}", scope="Education", status="done",
                value=ClinicalValue(kind="text", text=text, status="present"),
                source_refs=sorted({ref for item in evidence for ref in item.source_refs}) if field == "evidence" else []))
        note = {section: {field: "" for field in fields} for section, fields in RECORD_FIELDS.items()}
        for field, item in state.case.entries():
            section, name = field.split(".")
            if item.status == "done" and item.value and (section in {"A", "P"} or item.source_refs):
                text = self._describe_record(item, episodes)
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
        try:
            validate_payload(state)
        except (KeyError, TypeError, ValueError) as error:
            state.interaction.submission_error = str(error)
            if state.interaction.submission_repairs or str(error) in {"doctor_call_required", "diagnosis_not_allowed"}:
                state.stop("failed", str(error))

    def submit_diagnosis(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        entry = None
        try:
            self.nova_session.refresh_snapshot(state, self.client, final=True)
            if state.interaction.termination:
                return
            self.validate_submission(state)
            if state.interaction.termination or state.interaction.submission_error:
                return
            interaction = state.interaction
            interaction.submission_request_id = interaction.submission_request_id or self.new_request_id()
            request = {**interaction.submission_payload, "request_id": interaction.submission_request_id}
            entry = self.interactions.record_submission_attempt(state, request)
            result = self.executor.execute(state, self.client, self.client.diagnose, request, entry.attempts, final=True)
            entry.response = result
            interaction.submission_result = result
        except NovaError as error:
            if entry:
                entry.response = {"error": error.code}
            if error.code == "INVALID_RECORD_FIELDS" and state.interaction.submission_repairs < LIMITS.submission_repairs:
                state.interaction.submission_error = error.code
            else:
                state.stop(failure_outcome(error), error.code)
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

    def begin_repair(self, state: WorkflowState) -> None:
        if state.interaction.submission_repairs >= LIMITS.submission_repairs:
            raise ValueError("Submission repair limit reached")
        state.interaction.submission_repairs += 1
        state.interaction.submission_request_id = None
        state.interaction.submission_result = None
        state.interaction.submission_error = None
