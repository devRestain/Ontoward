import hashlib
import json
from dataclasses import dataclass, replace


def patient_payload(case):
    fields = {'id', 'kind', 'target', 'attribute', 'values', 'measurement', 'status', 'subject',
              'subject_member', 'reported_by', 'time_context', 'observation_id', 'episode_id',
              'acquisition', 'polarity_scope', 'evidence_use', 'binding'}
    return {'facts':[f.model_dump(include=fields, exclude_none=True) for f in case.current_facts()]}


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    target: str
    kind: str
    status: str
    attribute: str | None = None
    values: tuple = ()
    measurement: object = None
    subject: str = 'patient'
    subject_member: str | None = None
    observation_id: str | None = None
    episode_id: str | None = None
    time_context: str = 'current'
    polarity_scope: str = 'general'
    evidence_use: str = 'reasoning'

    def signature(self):
        return (self.id, self.target, self.attribute, self.values,
                self.measurement.signature() if self.measurement else None, self.status,
                self.subject, self.subject_member, self.observation_id, self.episode_id,
                self.time_context, self.polarity_scope, self.evidence_use)


@dataclass(frozen=True)
class EvidenceIndex:
    raw: tuple
    entries: tuple
    groups: dict
    contexts: tuple
    fingerprint: str

    @classmethod
    def from_case(cls, case, knowledge):
        records = []
        for fact in case.active_facts():
            kinds = ('Symptom', 'ExamFinding') if fact.kind == 'attribute' else (
                {'symptom':'Symptom', 'finding':'ExamFinding', 'context':'ContextFactor'}[fact.kind],)
            target = next((ident for kind in kinds if (ident := knowledge.term_id(fact.target, kind))), None)
            attribute = knowledge.term_id(fact.attribute, 'FindingAttribute') if fact.attribute else None
            values = tuple(knowledge.value_id(fact.attribute, value) for value in fact.values)
            if not target or fact.attribute and not attribute or any(v is None for v in values):
                raise ValueError('Fact has no scoped admitted terminology binding')
            records.append(EvidenceRecord(id=fact.id, target=target, attribute=attribute, values=values,
                kind=fact.kind, status=fact.status, measurement=fact.measurement,
                subject=fact.subject, subject_member=fact.subject_member, observation_id=fact.observation_id,
                episode_id=fact.episode_id, time_context=fact.time_context,
                polarity_scope=fact.polarity_scope, evidence_use=fact.evidence_use))
        return cls.from_records(records)

    @classmethod
    def from_records(cls, records):
        records = tuple(records)
        groups, contexts = {}, []
        # A simulation uses the same conflict rule as obtained evidence.
        grouped = {}
        for record in records:
            key = (record.target, record.attribute, record.subject, record.subject_member,
                   record.observation_id, record.episode_id, record.time_context, record.polarity_scope)
            grouped.setdefault(key, []).append(record)
        conflicts = set()
        for group in grouped.values():
            definite = [r for r in group if r.status in {'present', 'absent'}]
            positive = {v for r in definite if r.status == 'present' for v in r.values}
            negative = {v for r in definite if r.status == 'absent' for v in r.values}
            numeric = {str(r.measurement.signature()) for r in definite if r.status == 'present' and r.measurement}
            if (len({r.status for r in definite}) > 1 and not any(r.values for r in definite)
                    or len(numeric) > 1 or positive & negative):
                conflicts.update(r.id for r in group)
        current = tuple(replace(r, status='uncertain') if r.id in conflicts else r for r in records)
        entries = tuple(r for r in current if r.evidence_use == 'reasoning'
                        and not (r.status == 'absent' and r.polarity_scope == 'qualified' and not r.attribute))
        for item in entries:
            if item.kind == 'context':
                contexts.append(item)
            elif item.subject == 'patient' and item.time_context != 'past':
                key = (item.observation_id or item.id, item.episode_id or item.id, item.time_context)
                group = groups.setdefault(key, {'base':[], 'attributes':[]})
                group['attributes' if item.kind == 'attribute' else 'base'].append(item)
        digest = hashlib.sha256(json.dumps([r.signature() for r in sorted(entries, key=lambda r:r.id)],
                                           sort_keys=True).encode()).hexdigest()
        return cls(records, entries, groups, tuple(contexts), digest)

    def patch(self, patch):
        records = {r.id:r for r in self.raw}
        records.update((r.id, r) for r in patch)
        return self.from_records(records.values())

    def records(self, target, attribute=None, observation=None, episode=None, subject='patient', timing=None):
        return [r for r in self.entries if r.target == target and r.attribute == attribute and r.subject == subject
                and (observation is None or r.observation_id == observation)
                and (episode is None or r.episode_id == episode)
                and (timing is None or r.time_context == timing)]
