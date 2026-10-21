"""Synthetic knowledge and provider responses; never production clinical output."""
import copy
import json
from pathlib import Path

from ontoward_extraction.compile import compile_bundle
from ontoward_extraction.llm import Provider
from ontoward_extraction.models import Concept, canonical, identifier

PROJECT = Path(__file__).resolve().parents[2]
SEED = json.loads((PROJECT / 'Extraction/augmentation/insomnia_growth.seed.json').read_text())
INSOMNIA = SEED['clusters'][0]['target_ids'][0]
HYPNOTIC = SEED['clusters'][0]['reference_ids'][0]
SHORT, SHORT2 = SEED['clusters'][1]['target_ids']
FALTER, GHD = SEED['clusters'][1]['reference_ids']
WITHDRAWAL = SEED['clusters'][0]['reference_ids'][1]
SCOPE = dict(subject='patient', subject_member=None, time_context='current')


def config():
    value = json.loads((PROJECT / 'Extraction/config.api-luna.json').read_text())
    value['prompt_directory'] = str(PROJECT / 'Extraction/prompts')
    return value


def clinical(disease, target, *, features=None, applicability=(), effect='support'):
    return dict(disease_id=disease, target_id=target, target_scope=SCOPE,
        features=features or [dict(status='present')], applicability=list(applicability), effect=effect)


def context(ident, *, subject='patient', status='present', time='current'):
    return dict(concept_id=ident, subject=subject, subject_member=None, time_context=time, status=status)


def parent_bundle(directory):
    rows = []
    def node(ident, kind, name, korean, **kwargs):
        rows.append(Concept(id=ident, kind=kind, name=name, korean=korean, **kwargs).model_dump())
    for ident, name in [(GHD, 'Growth hormone deficiency'), (WITHDRAWAL, 'Benzodiazepine withdrawal'),
                        ('urn:fixture:thyroid', 'Hyperthyroidism')]:
        node(ident, 'Disease', name, '가상진단')
    for ident, name in [(INSOMNIA, 'Insomnia complaint'), (SHORT, 'Short stature for age'),
            (SHORT2, 'Short stature complaint'), (FALTER, 'Growth faltering complaint'),
            ('urn:fixture:weight', 'Weight loss'), ('urn:fixture:heat', 'Heat intolerance')]:
        node(ident, 'Symptom', name, '가상주호소', attributes=['urn:fixture:quantity'],
            question=dict(text='이 증상이 있나요?', answer_type='presence', affirmative=True, time_context='current'))
    node(HYPNOTIC, 'ContextFactor', 'Hypnotic use', '수면제복용', context_type='medication_history',
        question=dict(text='수면제를 복용하시나요?', answer_type='presence', affirmative=True, time_context='current'))
    node('urn:fixture:quantity', 'FindingAttribute', 'Existing measurement', '기존측정',
        question=dict(text='측정값은 얼마인가요?', answer_type='quantity', units=['cm'], time_context='current'),
        attribute_role=dict(order=0, category='measurement'))
    node('urn:fixture:quality', 'FindingAttribute', 'Existing quality', '기존양상', values=['urn:fixture:value'],
        question=dict(text='어떤 양상인가요?', answer_type='category'), attribute_role=dict(order=1, category='quality'))
    node('urn:fixture:value', 'AttributeValue', 'Existing value', '기존값')
    node('urn:fixture:related', 'AttributeValue', 'Related value', '관련값')
    rows[3]['attributes'].append('urn:fixture:quality')
    relations = [clinical(GHD, SHORT), clinical(GHD, SHORT2), clinical(GHD, FALTER), clinical(WITHDRAWAL, INSOMNIA),
        clinical('urn:fixture:thyroid', 'urn:fixture:weight'), clinical('urn:fixture:thyroid', 'urn:fixture:heat'),
        clinical(GHD, SHORT, features=[dict(attribute='urn:fixture:quantity',
            expected=dict(kind='interval', lower=0., upper=2., unit='cm', lower_inclusive=False, upper_inclusive=True))])]
    override = dict(text='이전 키 측정값은 얼마인가요?', answer_type='quantity', affirmative=False,
        interviewable=True, reason=None, units=['cm'], time_context='current')
    compile_bundle(directory, 'fixture-parent', rows, relations, preserve_ids=True,
        value_paths=[dict(observed='urn:fixture:related', expected='urn:fixture:value', relation='is_a')],
        question_overrides={SHORT + '|urn:fixture:quantity': override})
    return Path(directory) / 'manifest.json'


def specifications():
    defs = {}
    tasks = []
    def new(ref, kind, name, korean, *, owner=None, **kwargs):
        ref = 'new:' + ref
        tasks.append(dict(ref=ref, kind=kind, name=name, owner_ref=owner, reuse_id=None,
            instruction='Synthetic protocol definition for ' + name))
        defs[ref] = Concept(id=ref, kind=kind, name=name, korean=korean, **kwargs).model_dump()
        return ref
    use = new('UseDisorder', 'Disease', 'Sedative, hypnotic, or anxiolytic use disorder', '진정수면항불안제사용장애')
    failed = new('FailedReduction', 'ContextFactor', 'Unsuccessful attempts to reduce hypnotic use', '수면제감량실패', context_type='medication_history')
    harm = new('ContinuedHarm', 'ContextFactor', 'Continued hypnotic use despite harm', '위해에도수면제지속', context_type='medication_history')
    cdgp = new('CDGP', 'Disease', 'Constitutional growth delay', '체질성성장지연')
    fss = new('FSS', 'Disease', 'Familial short stature', '가족성저신장')
    velocity = new('Velocity', 'FindingAttribute', 'Height velocity', '성장속도')
    trajectory = new('Trajectory', 'FindingAttribute', 'Linear growth trajectory', '성장경과')
    stable = new('Stable', 'AttributeValue', 'Stable linear growth channel', '안정적성장경로', owner=trajectory)
    impaired = new('Impaired', 'AttributeValue', 'Declining linear growth trajectory', '성장경과악화', owner=trajectory)
    defs[trajectory]['values'] = [stable, impaired]
    late = new('FamilyLate', 'ContextFactor', 'Family history of late growth or maturation', '가족늦은성숙력', context_type='family_history')
    parental = new('FamilyShort', 'ContextFactor', 'Parental short stature', '부모저신장', context_type='family_history')
    relations = {}
    work = [dict(disease_ref=use, target_ref=INSOMNIA, replace_association_id=None, instruction='use_insomnia'),
            dict(disease_ref=use, target_ref=failed, replace_association_id=None, instruction='use_behavior')]
    relations['use_insomnia'] = clinical(use, INSOMNIA, applicability=[context(HYPNOTIC), context(failed), context(harm)])
    relations['use_behavior'] = clinical(use, failed, applicability=[context(HYPNOTIC), context(harm)], effect='strong_support')
    for index, target in enumerate((SHORT, SHORT2)):
        features = [dict(status='present'), dict(attribute=trajectory, expected=dict(kind='concept', concept=stable))]
        for ref, label, applicability in [(cdgp, 'cdgp', []), (fss, 'fss', [context(parental, subject='family', time='past')])]:
            key = label + str(index)
            work.append(dict(disease_ref=ref, target_ref=target, replace_association_id=None, instruction=key))
            relations[key] = clinical(ref, target, features=features, applicability=applicability)
        key = 'late' + str(index)
        work.append(dict(disease_ref=cdgp, target_ref=target, replace_association_id=None, instruction=key))
        relations[key] = clinical(cdgp, target, features=features, applicability=[context(late, subject='family', time='past')], effect='strong_support')
    # One meaningless draft is deliberately completed neutral and excluded from RDF.
    work.append(dict(disease_ref=use, target_ref=HYPNOTIC, replace_association_id=None, instruction='neutral'))
    relations['neutral'] = clinical(use, HYPNOTIC, effect='neutral')
    discovery = dict(concepts=tasks, extensions=[dict(id=t, aliases=[], attributes=[velocity, trajectory], values=[]) for t in (SHORT, SHORT2)], relations=work)
    return defs, discovery, relations


class MockProvider:
    def __init__(self, configuration, directory, *, invalid_once=False, after_send=None):
        self.config, self.directory = configuration, Path(directory)
        self.name = configuration['provider']
        self.calls, self.invalid_once, self.after_send = [], invalid_once, after_send
        self.defs, self.discovery, self.relations = specifications()

    def payload(self, *args, **kwargs):
        return Provider.payload(self, *args, **kwargs)

    def send(self, payload):
        messages = payload.get('messages', payload.get('body', {}).get('input'))
        packets = [json.loads(m['content']) for m in messages if m['role'] == 'user']
        phase = packets[0]['phase']
        jobs = [j for packet in packets for j in packet.get('jobs', [])]
        self.calls.append((phase, [j['job_id'] for j in jobs]))
        # Effective registered identities appear only in the shared definition table.
        vocabulary = [n for packet in packets for n in packet.get('concepts', [])]
        by_name = {n['name']: n['id'] for n in vocabulary}
        mapping = {ref: by_name[node['name']] for ref, node in self.defs.items() if node['name'] in by_name}
        def mapped(value):
            if isinstance(value, str): return mapping.get(value, value)
            if isinstance(value, list): return [mapped(v) for v in value]
            if isinstance(value, dict): return {k: mapped(v) for k, v in value.items()}
            return value
        rows = []
        for index, job in enumerate(jobs):
            source = job['input']
            if phase == 'augment_discover':
                raw = copy.deepcopy(self.discovery)
                if source['cluster']['id'] == 'insomnia_medication':
                    raw['concepts'] = raw['concepts'][:3]
                    raw['extensions'] = []
                    raw['relations'] = [t for t in raw['relations'] if t['instruction'].startswith('use') or t['instruction'] == 'neutral']
                else:
                    raw['concepts'] = raw['concepts'][3:]
                    raw['relations'] = [t for t in raw['relations'] if t['instruction'] not in {'use_insomnia', 'use_behavior', 'neutral'}]
            elif phase == 'augment_concepts':
                raw = dict(concept=copy.deepcopy(self.defs[source['task']['ref']]))
                if self.invalid_once and index == 0:
                    raw['concept']['kind'] = 'Disease'
                    raw['concept']['name'] = 'Wrong identity'
                    self.invalid_once = False
            elif phase == 'augment_relations':
                raw = dict(relation=mapped(self.relations[source['task']['instruction']]), rationale='Offline protocol fixture', evidence_kind='model_medical_knowledge')
            elif phase == 'augment_review':
                raw = dict(relation=source['draft_relation'], rationale='One completed synthetic review', evidence_kind='model_medical_knowledge')
            else:
                node = source['concept']
                numeric = node['name'] == 'Height velocity'
                categorical = node['kind'] == 'FindingAttribute' and not numeric
                raw = dict(question=dict(text='성장속도는 연간 몇 cm인가요?' if numeric else '성장 경과는 어떤가요?' if categorical else '이 병력이 있나요?',
                    answer_type='quantity' if numeric else 'category' if categorical else 'presence',
                    affirmative=not (numeric or categorical), units=['cm/year'] if numeric else [],
                    time_context='past' if node['context_type'] == 'family_history' else 'current'),
                    attribute_role=dict(order=2, category='measurement' if numeric else 'course', clarification='측정된 성장 경과를 알려주세요') if source['role_requested'] else None)
            rows.append(dict(job_id=job['job_id'], **raw))
        if self.after_send:
            self.after_send()
        return dict(content=canonical(dict(results=rows)), finish_reason='stop',
            usage=dict(day='2026-10-21', model='gpt-6-luna', input_tokens=10, output_tokens=10))
