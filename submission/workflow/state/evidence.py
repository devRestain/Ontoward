import hashlib
import json
from dataclasses import dataclass

from .models import CaseState
from .canonical import CanonicalSnapshot


@dataclass(frozen=True)
class EvidenceIndex:
    raw: tuple
    entries: tuple
    groups: dict
    contexts: tuple
    fingerprint: str

    @classmethod
    def from_case(cls, case, *, copy=True):
        if copy:
            isolated = CaseState()
            for field, item in case.entries():
                isolated.put(field, item.model_copy(deep=True))
            case = isolated
        canonical = CanonicalSnapshot.from_case(case)
        entries = tuple((field, item) for field, item in canonical.entries
                        if item.status == "done" and item.source_refs and item.value
                        and item.value.evidence_use == "reasoning"
                        and not (item.value.status == "absent" and item.value.polarity_scope == "qualified"
                                 and not item.value.attribute_id)
                        and item.value.kind in {"symptom", "finding", "attribute", "context"})
        groups, contexts = {}, []
        for _, item in entries:
            value = item.value
            if value.kind == "context":
                contexts.append(item)
            elif value.subject == "patient" and value.time_context != "past":
                key = (value.observation_id or item.id, value.episode_id or item.id, value.time_context)
                group = groups.setdefault(key, {"base": [], "attributes": []})
                group["attributes" if value.kind == "attribute" else "base"].append(item)
        values = [(field, i.id, i.value.model_dump(exclude={"text", "record_category", "record_details"}))
                  for field, i in sorted(entries, key=lambda p: p[1].id)]
        digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        return cls(canonical.entries, entries, groups, tuple(contexts), digest)

    def patch(self, patch):
        case = CaseState()
        for field, item in self.raw:
            case.put(field, item)
        for field, item in patch:
            case.put(field, item.model_copy(deep=True))
        return self.from_case(case, copy=False)

    def records(self, target, attribute=None, observation=None, episode=None, subject="patient", timing=None):
        return [item for _, item in self.entries if target in item.value.concept_ids
                and item.value.attribute_id == attribute and item.value.subject == subject
                and (observation is None or item.value.observation_id == observation)
                and (episode is None or item.value.episode_id == episode)
                and (timing is None or item.value.time_context == timing)]
