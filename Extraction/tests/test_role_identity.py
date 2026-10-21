import unittest
from ontoward_extraction.normalize import concepts,relation
from ontoward_extraction.models import Concept
from ontoward_extraction.compile import compile_bundle
from knowledge.graph import ClinicalKnowledge,OW
from rdflib import RDF
from pathlib import Path
import copy
import tempfile
from support import nodes,relation as diagnostic_relation

class RoleIdentityTests(unittest.TestCase):
    def test_shared_temporary_value_id_cannot_overwrite_symptom_identity_or_question(self):
        rows=[Concept.model_validate(n).model_dump() for n in [
            dict(id='weight-loss',kind='Symptom',name='Weight loss',korean='체중 감소',
                 question=dict(text='체중이 줄었나요?',answer_type='presence',affirmative=True,time_context='current')),
            dict(id='trend',kind='FindingAttribute',name='Weight trend',korean='체중 변화',values=['weight-loss']),
            dict(id='weight-loss',kind='AttributeValue',name='Weight loss',korean='체중 감소')]]
        normalized,mapping,values=concepts(rows)
        symptom=next(n for n in normalized if n['kind']=='Symptom')
        attribute=next(n for n in normalized if n['kind']=='FindingAttribute')
        value=next(n for n in normalized if n['kind']=='AttributeValue')
        self.assertNotEqual(symptom['id'],value['id'])
        self.assertEqual(mapping['weight-loss'],symptom['id'])
        self.assertEqual(attribute['values'],[value['id']])
        self.assertEqual(symptom['question'],rows[0]['question'])
        mapped=relation(dict(disease_id='d',target_id='weight-loss',features=[dict(attribute='trend',expected=dict(kind='concept',concept='weight-loss'))]),mapping,values)
        self.assertEqual(mapped['target_id'],symptom['id'])
        self.assertEqual(mapped['features'][0]['expected']['concept'],value['id'])
        again,_,_=concepts(normalized)
        self.assertEqual(sorted(normalized,key=lambda n:n['id']),sorted(again,key=lambda n:n['id']))

    def test_finding_specific_exam_text_is_not_lost_or_shared_between_findings(self):
        raw=nodes();raw[5]['exam_text']='배를 눌러 확인하겠습니다';raw[6]['exam_text']=None
        other=copy.deepcopy(raw[5]);other.update(id='other',name='Other finding',korean='다른 소견',exam_text='등을 눌러 확인하겠습니다');raw.append(other)
        raw[0]['systems']=['body'];raw.append(Concept(id='body',kind='BodySystem',name='Body',korean='신체').model_dump())
        before=copy.deepcopy(raw)
        with tempfile.TemporaryDirectory() as temp:
            compile_bundle(temp,'test',raw,[diagnostic_relation()])
            knowledge=ClinicalKnowledge.load(Path(temp)/'manifest.json')
            methods=[knowledge.get_exam_methods(str(n)) for n in knowledge._graph.subjects(RDF.type,OW.ExamFinding)]
            self.assertEqual({m[0]['text'] for m in methods},{'배를 눌러 확인하겠습니다','등을 눌러 확인하겠습니다'})
        self.assertEqual(raw,before)
