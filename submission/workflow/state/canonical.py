from dataclasses import dataclass

from ..rules.normalization import measurement_value


def value_mapping(value):
    if len(value.concept_ids) != 1 or value.status not in {"present", "absent"}:
        return {}
    target = value.concept_ids[0]
    sign = "(+)" if value.status == "present" else "(-)"
    if not value.attribute_id:
        return {target: sign}
    if value.measurement:
        return {target: {value.attribute_id: measurement_value(value.measurement)}}
    if not value.values:
        return {}
    selected = value.values[0] if len(value.values) == 1 and value.status == "present" else {
        ident: sign for ident in value.values}
    return {target: {value.attribute_id: selected}}


@dataclass(frozen=True)
class CanonicalSnapshot:
    entries: tuple
    outcomes: tuple

    @classmethod
    def from_case(cls, case):
        entries = []
        for field, item in case.current_entries():
            value = item.value
            if (not field.startswith(("S.", "O.")) or item.status != "done" or not item.source_refs or value is None
                    or value.kind not in {"symptom", "finding", "context", "attribute"} or not value.concept_ids):
                continue
            item = item.model_copy(deep=True)
            item.value.text = ""
            item.value.record_details = []
            item.value.quantities = []
            item.mapping = value_mapping(item.value)
            entries.append((field, item))
        return cls(tuple(entries), tuple(outcome.model_copy(deep=True) for outcome in case.outcomes))

    def payload(self):
        return {"facts": [{"fact_id": item.id, "field": field, "mapping": item.mapping,
            "kind": item.value.kind, "evidence_use": item.value.evidence_use,
            "subject": item.value.subject, "subject_member": item.value.subject_member,
            "reported_by": item.value.reported_by, "time_context": item.value.time_context,
            "observation_id": item.value.observation_id, "episode_id": item.value.episode_id,
            "acquisition": item.acquisition, "polarity_scope": item.value.polarity_scope,
            "mapping_status": item.value.mapping_status, "forced_by": item.value.forced_by,
            "status": item.value.status} for field, item in self.entries],
            "outcomes": [outcome.model_dump() for outcome in self.outcomes]}
