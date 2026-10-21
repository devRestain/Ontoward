import csv
import json
from pathlib import Path

from ontoward_extraction.models import Concept, Relation
from ontoward_extraction.inputs import BODHI_HEADERS


def nodes():
    raw=[
        dict(id='disease',kind='Disease',name='Synthetic disease',korean='가상질환'),
        dict(id='symptom',kind='Symptom',name='Synthetic complaint',korean='가상증상',attributes=['quality'],
            question=dict(text='가상증상이 있나요?',answer_type='presence',affirmative=True,time_context='current')),
        dict(id='quality',kind='FindingAttribute',name='Synthetic quality',korean='양상',values=['sharp'],
            question=dict(text='어떤 느낌인가요?',answer_type='category',time_context='current'),attribute_role=dict(order=0,category='quality')),
        dict(id='sharp',kind='AttributeValue',name='Sharp',korean='날카로움'),
        dict(id='context',kind='ContextFactor',name='Synthetic history',korean='가상병력',context_type='past_medical_history',
            question=dict(text='가상병력이 있나요?',answer_type='presence',affirmative=True,time_context='past')),
        dict(id='finding',kind='ExamFinding',name='Synthetic tenderness',korean='가상압통',exam_method='method'),
        dict(id='method',kind='ExamMethod',name='Synthetic palpation',korean='촉진',exam_text='배를 눌러 확인하겠습니다'),
    ]
    return [Concept.model_validate(row).model_dump() for row in raw]


def relation(effect='support', target='symptom', status='present', **values):
    raw=dict(disease_id='disease',target_id=target,target_scope=dict(subject='patient',subject_member=None,time_context='current'),
        features=[dict(status=status)],effect=effect)
    raw.update(values)
    return Relation.model_validate(raw).model_dump()


def inputs(directory):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    snapshot=root/'Snapshot';snapshot.mkdir(exist_ok=True)
    (snapshot/'sct2_Concept_Snapshot_20260501.txt').write_text('id\teffectiveTime\tactive\tmoduleId\tdefinitionStatusId\n100001\t20260501\t1\t900001\t900002\n')
    for role,fields in BODHI_HEADERS.items():
        path=root/(role+'.csv')
        with path.open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=sorted(fields));writer.writeheader()
            if role=='nodes_condition': writer.writerow(dict(snomed_id='100001',concept_type='disorder',name='Synthetic disease'))
            elif role=='nodes_symptom': writer.writerow(dict(uuid='sym1',root_snomed_id='100002',name='Synthetic complaint'))
    (root/'evidences.json').write_text(json.dumps({'E1':dict(name='Synthetic complaint',question_en='Complaint?',data_type='B',**{'possible-values':[]})}))
    (root/'conditions.json').write_text(json.dumps({'D1':dict(condition_name='Synthetic disease',symptoms={'E1':{}},antecedents={})}))
    (root/'anything.json').write_text(json.dumps({'nodes':[{'id':'S1','node_type':'Symptom','en':'Synthetic complaint','ko':'가상증상','prior_policy':'IGNORE THIS'}],
        'attribute_bindings':[],'cpx_topics':[],'snapshot':{'forbidden':'old graph'}}))
    return root


class ScriptedProvider:
    name='nova_dev'

    def __init__(self, after_send=None):
        self.calls=[];self.after_send=after_send

    def payload(self,request_id,messages,schema,final=False):
        return dict(request_id=request_id,messages=messages,model='openai/gpt-6.1-sol' if final else 'openai/gpt-6-luna')

    def send(self,payload):
        parts=[json.loads(message['content']) for message in payload['messages'] if message['role']=='user']
        packet=parts[-1];phase=packet['phase'];results=[]
        if phase=='draft' and packet.get('wire_contract')=='draft-shared-1':
            definitions=[dict(zip(part['vocabulary_columns'],row)) for part in parts for row in part.get('vocabulary',[])]
            vocabulary={node['id']:node for node in definitions}
            packet=dict(packet,jobs=[job for part in parts for job in part.get('jobs',[])])
            for job in packet['jobs']:
                if 'source_material_ref' in job['input']:
                    reference=job['input']['source_material_ref']
                    material=[row for part in parts if part.get('source_material_for')==reference for row in part['source_material']]
                    if len(material)!=job['input']['source_material_count']:raise ValueError('source_material_part_count_mismatch')
                    job['input']['source_material']=material
                job['input']=dict(job['input'],disease=vocabulary[job['input']['disease']],
                    available_targets=[node for node in vocabulary.values() if node['kind'] in {'Symptom','ExamFinding','ContextFactor'}])
        for job in packet['jobs']:
            self.calls.append(job['job_id'])
            data=job['input'];result=dict(job_id=job['job_id'],concepts=[],relations=[],value_matches=[])
            if phase=='normalize': result['concepts']=nodes()
            elif phase=='questions':
                node=data['concept']
                template=next(item for item in nodes() if (item['name'],item['kind'])==(node['name'],node['kind']))
                result['concepts']=[dict(id=node['id'],question=template['question'],exam_text=template['exam_text'],
                    attribute_role=template['attribute_role'],exam_method=node['exam_method'])]
                result['new_concepts']=[]
            elif phase=='draft':
                target=next(node for node in data['available_targets'] if node['kind']=='Symptom')
                result['relations']=[relation(disease_id=data['disease']['id'],target_id=target['id'])]
            elif phase=='final': result['relations']=[data['draft_relation']]
            elif phase=='conflict': result['relations']=[data['conflicting_relations'][0]]
            else: result['concepts']=[data['gap']['concept']]
            results.append(result)
        if self.after_send: self.after_send()
        return dict(content=json.dumps({'results':results}),finish_reason='stop',usage=dict(day='2026-10-19',model=payload['model'],input_tokens=1,output_tokens=1))
