from dataclasses import dataclass


def patient_payload(case):
    fields = {'id', 'kind', 'target', 'attribute', 'values', 'measurement', 'status', 'subject',
              'subject_member', 'reported_by', 'time_context', 'observation_id', 'episode_id',
              'acquisition', 'polarity_scope', 'evidence_use', 'binding'}
    return {'facts':[f.model_dump(include=fields, exclude_none=True) for f in case.current_facts()
        if f.evidence_use=='reasoning' and f.polarity_scope!='qualified']}


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

@dataclass(frozen=True)
class EvidenceIndex:
    entries: tuple
    groups: dict
    contexts: tuple

    @classmethod
    def from_case(cls, case, knowledge):
        records = []
        for fact in case.current_facts():
            if fact.evidence_use != 'reasoning' or fact.polarity_scope == 'qualified':
                continue
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
        groups, contexts = {}, []
        for item in records:
            if item.kind == 'context':
                contexts.append(item)
            elif item.subject == 'patient' and item.time_context != 'past':
                original = case.facts[item.id]
                objective = original.acquisition == 'EXAM' or original.source_ref == 'initial:vital_signs'
                key = (item.subject, item.subject_member, item.observation_id or item.id,
                    item.episode_id or item.id, item.time_context, objective)
                group = groups.setdefault(key, {'base':[], 'attributes':[]})
                group['attributes' if item.kind == 'attribute' else 'base'].append(item)
        return cls(tuple(records), groups, tuple(contexts))
