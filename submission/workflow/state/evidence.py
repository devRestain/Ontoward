from dataclasses import dataclass

from ..model_context import fact_record


def patient_payload(case):
    return {'facts': [fact_record(f, f'f_{index}') for index, f in enumerate(case.current_facts(), 1)]}


def fixed_case_payload(case):
    """Project one frozen case with request-local, mutually resolvable fact IDs."""
    facts = case.current_facts()
    refs = {fact.id: f'f_{index}' for index, fact in enumerate(facts, 1)}
    diagnosis = case.fixed_diagnosis()
    if any(ident not in refs for ident in diagnosis['evidence_ids']):
        raise ValueError('fixed_diagnosis_evidence_outside_current_facts')
    diagnosis['evidence_ids'] = [refs[ident] for ident in diagnosis['evidence_ids']]
    return {'patient': {'facts': [fact_record(fact, refs[fact.id]) for fact in facts]},
            'fixed_diagnosis': diagnosis}


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

@dataclass(frozen=True)
class EvidenceIndex:
    entries: tuple
    groups: dict
    contexts: tuple
    by_target: dict

    @classmethod
    def from_case(cls, case, knowledge):
        facts = case.current_facts()
        def scope(fact):
            return (fact.target, fact.subject, fact.subject_member, fact.observation_id,
                    fact.episode_id, fact.time_context,
                    fact.acquisition == 'EXAM' or fact.source_ref == 'initial:vital_signs')
        bases = {scope(fact) for fact in facts if fact.kind in {'symptom', 'finding'}
                 and fact.status == 'present' and fact.polarity_scope == 'general'}
        records = []
        for fact in facts:
            if not fact.graph_binding or fact.polarity_scope == 'qualified' or (
                    fact.kind == 'attribute' and scope(fact) not in bases):
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
                polarity_scope=fact.polarity_scope))
        groups, contexts = {}, []
        for item in records:
            if item.kind == 'context':
                contexts.append(item)
            original = case.facts[item.id]
            objective = original.acquisition == 'EXAM' or original.source_ref == 'initial:vital_signs'
            key = (item.subject, item.subject_member, item.observation_id or item.id,
                item.episode_id or item.id, item.time_context, objective)
            group = groups.setdefault(key, {'base':[], 'attributes':[]})
            group['attributes' if item.kind == 'attribute' else 'base'].append(item)
        by_target = {}
        for group in groups.values():
            for target in {r.target for r in (*group['base'], *group['attributes'])}:
                by_target.setdefault(target, []).append({key: [r for r in rows if r.target == target]
                                                        for key, rows in group.items()})
        return cls(tuple(records), groups, tuple(contexts), by_target)
