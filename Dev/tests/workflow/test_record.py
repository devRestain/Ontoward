import unittest
import json
from pathlib import Path

import fixtures as f
from workflow.state.models import NoteFact, Question, TurnContext

PUBLIC_STARTS=json.loads((Path(__file__).resolve().parents[3]/'Test/initial_reports.json').read_text())


def initial(rows, opening, *, demographics=(), vitals=None, state=None, knowledge=None):
    def response(payload):
        if payload['task']=='input_context':
            return {'statements':rows,'patient_context':list(demographics)}
    c=f.consultation(f.FakeSDK(chat_handler=response),f.resources(knowledge))
    s=state or f.state()
    s.turn=TurnContext(kind='initial',response={'opening':opening,**({'vital_signs':vitals} if vitals else {})})
    c.ear.process_input(s,c.brain.knowledge,c.client)
    return c,s


class RecordTests(unittest.TestCase):
    def test_c03_public_opening_patient_historian_and_reported_growth_only(self):
        opening=PUBLIC_STARTS['C03']['opening']
        rows=[f.statement('키가 또래에 비해 많이 작은 것 같아',primary_concern=True),f.statement('일 년 전에는 백 센티미터였고 지금은 백오 센티미터 정도였다',
            focus='attribute',target_terms=['Height'],record_category='measurement',note_value='Home height over 1 year',
            measurement={'kind':'interval','lower':100,'upper':105,'unit':'cm','approximate':True})]
        demographics=[dict(key='age',value='6 years',quote='여섯 살'),dict(key='sex',value='male',quote='남자아이'),
            dict(key='reporter',value='mother',quote='엄마'),dict(key='age',value='37 years',quote='서른일곱 살',subject='family',subject_member='mother')]
        c,s=initial(rows,opening,demographics=demographics,vitals=PUBLIC_STARTS['C03']['vital_signs'])
        self.assertTrue(all(n.reported_by=='mother' for n in s.case.notes.values()
            if n.category=='patient_context' or n.subject=='family'))
        c.close_collection(s);c.writer.build_soap(s);note=s.turn.payload['note']
        self.assertTrue(note['S']['hpi'].startswith('Age: 6 years'))
        self.assertIn('Sex: male',note['S']['hpi']);self.assertIn('Historian: mother',note['S']['hpi'])
        for value in ('100','105','cm','over 1 year'):
            self.assertIn(value,note['S']['hpi'])
        self.assertNotIn('37 years',note['S']['hpi']);self.assertIn('37 years',note['S']['fh'])
        self.assertEqual(note['O']['exam'],'');self.assertEqual(note['O']['tests'],'')
        self.assertNotIn('Tanner',str(note));self.assertNotIn('percentile',str(note))
        self.assertNotIn('6 years',note['S']['sh'])

    def test_c10_public_opening_weight_report_is_separate_from_initial_objective_pulse(self):
        start=PUBLIC_STARTS['C10']
        rows=[f.statement('최근 석 달 사이에 칠 키로그람 정도 빠져서 지금은 사십구 키로그람 정도이다',
            focus='attribute',target_terms=['Weight'],record_category='measurement',
            note_value='Reported weight declined from 56 to 49 kg over 3 months',
            measurement={'kind':'quantity','value':49,'unit':'kg'},input_segment='opening'),
            f.statement('맥박 : 102 회/분',target_terms=[],record_category='objective_observation',
                note_value='Pulse 102 beats/min',input_segment='vital_signs')]
        c,s=initial(rows,start['opening'],vitals=start['vital_signs'])
        fields,_=c.writer.build_record_view(s.case)
        self.assertIn('56 to 49 kg over 3 months',' '.join(fields['S.hpi']))
        self.assertIn('Pulse 102 beats/min',' '.join(fields['O.exam']))
        self.assertNotIn('49 kg',' '.join(fields['O.exam']))
        self.assertTrue(all(n.source_ref=='initial:vital_signs' for n in s.case.notes.values()
            if n.category=='objective_observation'))

    def test_same_initial_text_report_and_objective_segment_remain_distinct(self):
        text='Test examination finding'
        rows=[f.statement(text,target_terms=[text],record_category='measurement',note_value='Reported finding',input_segment='opening'),
            f.statement(text,target_terms=[text],input_segment='vital_signs')]
        c,s=initial(rows,text,vitals=text)
        self.assertTrue(any(fact.kind=='finding' and fact.source_ref=='initial:vital_signs' for fact in s.case.facts.values()))
        fields,_=c.writer.build_record_view(s.case)
        self.assertIn('Reported finding',' '.join(fields['S.hpi']))
        self.assertIn('Test examination finding',' '.join(fields['O.exam']))
        self.assertNotIn('turn 0',' '.join(fields['O.exam']))

    def test_untrusted_segment_cannot_promote_opening_to_objective(self):
        c,s=initial([f.statement('Finding',target_terms=['Test examination finding'],input_segment='vital_signs')],'Finding')
        self.assertFalse(any(fact.kind=='finding' for fact in s.case.facts.values()))
        self.assertFalse(c.writer.build_record_view(s.case)[0]['O.exam'])

    def test_demographic_duplicate_conflict_and_explicit_correction(self):
        c,s=initial([], '6 years',demographics=[dict(key='age',value='6 years',quote='6 years')])
        _,s=initial([], '6 years',state=s,demographics=[dict(key='age',value='6 years',quote='6 years')])
        self.assertEqual(len(s.case.notes),1)
        _,s=initial([], '7 years',state=s,demographics=[dict(key='age',value='7 years',quote='7 years')])
        self.assertEqual(next(iter(s.case.notes.values())).status,'uncertain')
        _,s=initial([], '7 years',state=s,demographics=[dict(key='age',value='7 years',quote='7 years',correction=True)])
        note=next(iter(s.case.notes.values()));self.assertEqual((note.value,note.status),('7 years','present'))

    def test_exam_attributes_keep_acquisition_turn_and_subjective_notes_remain_s(self):
        c,s=f.consultation(),f.chief(f.state())
        s.case.apply([f.fact('exam',kind='finding',target='Test examination finding',category=None,
            acquisition='EXAM',source_ref='exam-4',turn=4,observation_id='exam',episode_id='episode'),
            f.fact('attribute',kind='attribute',target='Test examination finding',attribute='Location',values=('head',),
            acquisition='EXAM',source_ref='exam-5',turn=5,observation_id='exam',episode_id='episode')],
            [NoteFact(id='objective',category='objective_observation',value='Observed additional sign',
                acquisition='EXAM',source_ref='exam-4',turn=4),
             NoteFact(id='history',category='medical_history',value='Reported past condition',
                acquisition='EXAM',source_ref='exam-4',turn=4)])
        fields,_=c.writer.build_record_view(s.case)
        exam=' '.join(fields['O.exam'])
        self.assertIn('Location',exam);self.assertIn('turn 4',exam);self.assertIn('turn 5',exam)
        self.assertIn('Observed additional sign',exam);self.assertNotIn('Reported past condition',exam)
        self.assertIn('Reported past condition',' '.join(fields['S.pmh']))

    def test_qualified_notes_preserve_c01_and_c10_conditions_without_calculations(self):
        c,s=f.consultation(),f.chief(f.state())
        s.case.apply(notes=[NoteFact(id='sleep',category='previous_care',value='Symptoms when medication is withheld; bedtime dose 1 mg',
            acquisition='SAY',source_ref='one'),NoteFact(id='exercise',category='associated_symptoms',
            value='Breathlessness during exercise, absent at rest; loose stool, denies diarrhea',acquisition='SAY',source_ref='two')])
        c.close_collection(s);c.writer.build_soap(s);text=str(s.turn.payload['note']['S'])
        for value in ('when medication is withheld','bedtime dose 1 mg','during exercise','absent at rest','loose stool','denies diarrhea'):
            self.assertIn(value,text)
        self.assertNotIn('daily total',text)

    def test_planned_education_without_delivery_is_not_claimed_as_delivered(self):
        c,s=f.consultation(prepared=f.resources(education=True)),f.chief(f.state('Education'))
        c.close_collection(s);c.brain.prepare_education(s,c.client);c.writer.build_soap(s)
        self.assertIn('planned (not delivered)',s.turn.payload['note']['P']['education'])

    def test_education_requires_freeze_and_last_input_changes_primary_before_freeze(self):
        c,s=f.consultation(),f.chief(f.state('DifferentialDiagnosis'))
        with self.assertRaises(ValueError): c.brain.prepare_education(s,c.client)
        c.brain.refresh_assessment(s,c.client);s.interview.queue.clear()
        from brain_double import clinical_response
        def reply(payload):
            if payload['task']=='clinical_decision':
                value=clinical_response(payload);value['ranked_disease_refs'].reverse();return value
        c.client.chat_handler=reply
        s.case.apply([f.fact('last',kind='attribute',attribute='Location',values=('head',),category=None)])
        c.close_collection(s)
        self.assertEqual(s.case.primary().name,'Disease beta')
        c.writer.build_soap(s);self.assertEqual(s.turn.payload['diagnosis'],'Disease beta')

    def test_subjective_objective_note_is_rejected_without_crashing_input(self):
        q=Question(item_id='q',purpose='feature',text='증상을 알려주세요.',target='Test complaint')
        s,c,_=f.interpret([f.statement('Reported sign',target_terms=[],record_category='objective_observation',
            note_value='Reported sign')],q=q)
        self.assertFalse(any(n.category=='objective_observation' for n in s.case.notes.values()))
        self.assertFalse(c.writer.build_record_view(s.case)[0]['O.exam'])

    def test_qualified_report_keeps_actual_condition_and_is_not_reasoning_input(self):
        row=f.statement('Pain during exercise',polarity_scope='qualified',record_category='associated_symptoms',
            note_value='Only during exercise, absent at rest')
        s,c,_=f.interpret([row])
        from workflow.state.evidence import EvidenceIndex, patient_payload
        self.assertFalse(EvidenceIndex.from_case(s.case,c.brain.knowledge).entries)
        self.assertFalse(patient_payload(s.case)['facts'])
        fields,_=c.writer.build_record_view(s.case)
        self.assertIn('Only during exercise, absent at rest',str(fields))
