import json
import re

from knowledge.graph import ClinicalKnowledge, OW
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

    def _line(self, category, content):
        content = "; ".join(line.strip() for line in str(content).splitlines() if line.strip())
        return self.config.texts.category_format.format(category=category, content=content)

    def _label(self, concept, *, history=False):
        label = self.knowledge.label(concept, language="en")
        if label == concept:
            return ""
        label = re.sub(r" \((?:finding|disorder|situation|observable entity|body structure)\)$", "", label)
        if history:
            for prefix in self.config.texts.history_prefixes:
                if label.casefold().startswith(prefix.casefold()):
                    label = label[len(prefix):]
                    break
            label = self.config.texts.term_abbreviations.get(label.casefold(), label)
        return label

    def _unit(self, unit, number):
        label = self.config.texts.unit_labels.get(unit, unit)
        return label + "s" if unit in {"day", "week", "month", "year"} and number != 1 else label

    def _measurement(self, measured):
        texts = self.config.texts
        if measured.kind == "quantity":
            if measured.unit.casefold() == "nrs":
                return texts.nrs_format.format(value=f"{measured.value:g}")
            return texts.measurement_format.format(operator=texts.operator_labels[measured.operator],
                value=f"{measured.value:g}", unit=self._unit(measured.unit, measured.value)).strip()
        upper_unit = measured.upper_unit or measured.unit
        if (measured.lower is not None and measured.upper is not None and measured.lower_inclusive
                and measured.upper_inclusive and upper_unit == measured.unit):
            return texts.range_format.format(lower=f"{measured.lower:g}", upper=f"{measured.upper:g}",
                unit=self._unit(measured.unit, measured.upper))
        return texts.interval_format.format(lower_bound="[" if measured.lower_inclusive else "(",
            upper_bound="]" if measured.upper_inclusive else ")",
            lower=f"{measured.lower:g} {self._unit(measured.unit, measured.lower)}" if measured.lower is not None else "−∞",
            upper=f"{measured.upper:g} {self._unit(upper_unit, measured.upper)}" if measured.upper is not None else "∞")

    def _details(self, value):
        parts = [self._label(concept) for concept in value.values]
        if value.measurement:
            parts.append(self._measurement(value.measurement))
        parts.extend(detail.english.strip() for detail in value.record_details)
        return "; ".join(dict.fromkeys(part for part in parts if part))

    def _context(self, value, episodes):
        texts = self.config.texts
        related = [key for key in episodes or {} if key[0] == value.subject and key[1] in value.concept_ids]
        multiple = len({key[2] for key in related}) > 1
        if value.subject == "patient" and value.time_context != "past" and not multiple:
            return ""
        episode = ""
        if multiple and value.episode_id:
            key = next(key for key in related if key[2] == value.episode_id)
            episode = texts.episode_format.format(number=episodes[key])
        return " (" + texts.clinical_context_format.format(subject=texts.subject_labels[value.subject],
            time=texts.time_labels[value.time_context], episode=episode) + ")"

    def _attribute(self, value):
        key = value.attribute_id.removeprefix(str(OW)) if value.attribute_id else ""
        category = (self.config.texts.attribute_labels.get(key) or self._label(value.attribute_id)) if value.attribute_id else None
        return category or self.config.texts.record_labels.get(value.record_category, self.config.texts.soap_labels["hpi"])

    def _attribute_content(self, value):
        texts = self.config.texts
        content = self._details(value)
        if value.status != "present":
            return f"({texts.status_labels[value.status]})" + ("; " + content if content else "")
        if value.attribute_id == str(OW.TimeSinceOnset) and value.measurement:
            content = texts.onset_format.format(duration=content)
        return content or texts.soap_labels["unknown"]

    def _describe_record(self, item, episodes=None) -> str:
        value, texts = item.value, self.config.texts
        if value is None:
            return ""
        if value.kind in {"plan", "education", "text"} and not (value.concept_ids or value.record_category or value.attribute_id):
            return value.text if value.kind in {"plan", "education"} else texts.unlinked_format.format(status=texts.status_labels[value.status])
        labels = "; ".join(filter(None, (self._label(concept) for concept in value.concept_ids)))
        if value.attribute_id:
            description = self._line(self._attribute(value), self._attribute_content(value))
            return (labels + " - " if labels else "") + description + self._context(value, episodes)
        labels = labels or texts.record_labels.get(value.record_category, texts.soap_labels["unmapped"])
        description = texts.finding_format.format(labels=labels, status=texts.status_labels[value.status])
        details = self._details(value)
        return description + ("; " + details if details else "") + self._context(value, episodes)

    @staticmethod
    def _obtained(items):
        return [item for item in items if item and item.status == "done" and item.source_refs and item.value]

    def _chief_text(self, state, episodes):
        texts, lines = self.config.texts, []
        chiefs = state.case.chief_complaints()
        for chief in chiefs:
            value = chief.value
            labels = "; ".join(filter(None, (self._label(concept) for concept in value.concept_ids))) or texts.soap_labels["unmapped"]
            if value.status != "present":
                labels += f" ({texts.status_labels[value.status]})"
            lines.append(self._line(texts.soap_labels["cc"], labels + self._context(value, episodes)))
            attributes = [item.value for item in self._obtained(state.case.S["hpi"].values())
                if item.value.subject == value.subject and item.value.time_context != "past"
                and item.value.observation_id == value.observation_id and item.value.episode_id == value.episode_id
                and (set(item.value.concept_ids) & set(value.concept_ids)
                     or not item.value.concept_ids and item.value.record_category)]
            for attribute in attributes:
                if attribute.attribute_id == str(OW.TimeSinceOnset) or attribute.record_category == "onset":
                    lines.append(self._line(texts.attribute_labels["TimeSinceOnset"], self._attribute_content(attribute)))
            pain = any(str(OW.PainQuality) in self.knowledge.get_symptom_attributes(target)
                or re.search(r"\b(?:pain|headache)\b", self._label(target), re.I) for target in value.concept_ids)
            if pain:
                parts = [self._line(self._attribute(attribute), self._attribute_content(attribute)) for attribute in attributes
                    if attribute.attribute_id in {str(OW.Severity), str(OW.Location), str(OW.Laterality),
                        str(OW.PainQuality), str(OW.Quality), str(OW.EpisodeDuration)}
                    or attribute.record_category in {"quality", "duration"}]
                lines.append(self._line(texts.soap_labels["pain"], "; ".join(parts) or texts.soap_labels["unknown"]))
        return texts.record_separator.join(dict.fromkeys(lines))

    def _vitals(self, value):
        try:
            vitals = json.loads(value.text)
        except (TypeError, ValueError):
            text = self._details(value) or value.text
            for term, label in self.config.texts.vital_labels.items():
                if any("가" <= char <= "힣" for char in term):
                    text = text.replace(term, label)
            return text
        if not isinstance(vitals, dict):
            return value.text
        parts = []
        for key, result in vitals.items():
            if isinstance(result, dict) and "value" in result:
                result = f"{result['value']} {result.get('unit', '')}".strip()
            parts.append(f"{self.config.texts.vital_labels.get(key, key)} {result}")
        return "; ".join(parts)

    def _section_entry(self, field, item, episodes, *, multiple_hpi_targets=False):
        value, texts = item.value, self.config.texts
        if field == "S.hpi" and (value.attribute_id or value.record_category):
            content = self._attribute_content(value)
            if multiple_hpi_targets and value.concept_ids:
                content = "; ".join(filter(None, (self._label(target) for target in value.concept_ids))) + " - " + content
            return self._line(self._attribute(value), content) + self._context(value, episodes)
        if field.startswith("S."):
            category = "; ".join(filter(None, (self._label(concept, history=True) for concept in value.concept_ids)))
            category = category or texts.record_labels.get(value.record_category, texts.soap_labels["unmapped"])
            content = f"({texts.status_labels[value.status]})"
            details = self._details(value)
            return self._line(category, content + ("; " + details if details else "")) + self._context(value, episodes)
        if field == "O.exam":
            if "initial" in item.source_refs:
                return texts.initial_exam_format.format(text=self._line(texts.soap_labels["vitals"], self._vitals(value)))
            content = self._describe_record(item, episodes)
            if not value.record_details and not value.values and not value.measurement:
                content += "; " + value.text
            return self._line(texts.soap_labels["exam"], content)
        if field.startswith("P."):
            return self._line(texts.soap_labels[field.split(".")[1]], value.text)
        return value.text

    def build_soap(self, state: WorkflowState) -> None:
        if state.interaction.termination:
            return
        if state.interaction.pending:
            state.stop("unknown", "pending_action_at_finalization")
            return
        evidence = self._obtained(state.case.get(item_id) for item_id in state.case.diagnosis_evidence)
        evidence = [item for item in evidence if item.value.status in {"present", "absent"}]
        texts = self.config.texts
        episodes = {}
        for item in self._obtained(item for _, item in state.case.entries()):
            if item.value.episode_id:
                for target in item.value.concept_ids:
                    episodes.setdefault((item.value.subject, target, item.value.episode_id), len(episodes) + 1)
        evidence_text = "; ".join(dict.fromkeys(self._describe_record(item, episodes) for item in evidence))
        if state.case.diagnosis_kind == "symptom":
            evidence_text = "; ".join(filter(None, (evidence_text, texts.symptom_assessment)))
        if state.case.diagnosis:
            evidence_text = texts.assessment_format.format(diagnosis=state.case.diagnosis, evidence=evidence_text)
        alternatives = []
        for hypothesis in ClinicalReasoner.supported_hypotheses(state):
            if hypothesis.disease_id == state.differential.selected_id:
                continue
            findings = self._obtained(state.case.get(ident) for ident in hypothesis.evidence_ids + hypothesis.contradiction_ids)
            findings = [item for item in findings if item.value.status in {"present", "absent"}]
            support = texts.label_separator.join(self._describe_record(item, episodes) for item in findings)
            if not support:
                continue
            diagnosis = self._label(hypothesis.disease_id)
            alternatives.append(texts.differential_format.format(diagnosis=diagnosis, evidence=support))
            if len(alternatives) == LIMITS.differential_display:
                break
        summaries = {"evidence": evidence_text, "differential": texts.record_separator.join(alternatives[:LIMITS.differential_display])}
        for field, text in summaries.items():
            state.case.put(f"A.{field}", RecordItem(id=f"assessment:{field}", scope="Education", status="done",
                value=ClinicalValue(kind="text", text=text, status="present"),
                source_refs=sorted({ref for item in evidence for ref in item.source_refs}) if field == "evidence" else []))
        note = {section: {field: "" for field in fields} for section, fields in RECORD_FIELDS.items()}
        note["S"]["cc"] = self._chief_text(state, episodes)
        chiefs = state.case.chief_complaints()
        if chiefs:
            note["S"]["hpi"] = self._line(texts.soap_labels["hpi"], "; ".join(dict.fromkeys(
                self._describe_record(item, episodes) for item in chiefs)))
        hpi_targets = {target for item in self._obtained([*chiefs, *state.case.S["hpi"].values()])
                       for target in item.value.concept_ids}
        for field, item in state.case.entries():
            section, name = field.split(".")
            if field != "S.cc" and item.status == "done" and item.value and (section in {"A", "P"} or item.source_refs):
                text = self._section_entry(field, item, episodes, multiple_hpi_targets=len(hpi_targets) > 1)
                if text:
                    if field == "O.exam":
                        turns = sorted({entry.turn for entry in state.interaction.history if entry.id in item.source_refs
                                        and entry.kind == "EXAM" and entry.delivered and entry.turn is not None})
                        if turns:
                            text = texts.exam_turn_format.format(text=text, turn=", ".join(map(str, turns)))
                    note[section][name] += (texts.record_separator if note[section][name] else "") + text
        note["O"]["tests"] = ""
        if not self.config.education_enabled:
            note["P"]["education"] = ""
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
