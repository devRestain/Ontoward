import json
import unittest
from rdflib import Literal, RDF, RDFS
import fixtures as f
from knowledge.conditions import QuestionTemplate
from workflow.rules.assessment import graph_candidates
from workflow.state.models import Assessment, DifferentialEntry


class D49Tests(unittest.TestCase):
    def context(self,k):
        for predicate,value in [(RDF.type,f.OW.ContextFactor),(RDFS.label,Literal('Family history',lang='en')),
            (RDFS.label,Literal('가족병력',lang='ko')),(f.OW.contextType,Literal('family_history'))]:
            k._graph.add((f.OW.FamilyContext,predicate,value))
        k.questions[str(f.OW.FamilyContext)]=QuestionTemplate(text='가족 병력이 있나요?',answer_type='presence',affirmative=True)
        k.prepare_terms()

    def add(self,k,name,effect,target=None,status='present',scope=None,**kwargs):
        f.add_pattern(k,name,target or f.OW.Complaint,[],effect=effect,scope=scope,**kwargs)
        presence=f.OW[name+'Presence']
        k._graph.set((presence,f.OW.expectedStatus,Literal(status)))
        k.validate_graph();k.prepare_terms()

    def test_four_effects_activate_only_on_registered_full_match(self):
        for effect in ('support','strong_support','against','strong_against'):
            for expected in ('present','absent'):
                for actual in ('present','absent','unknown','uncertain'):
                    with self.subTest(effect=effect,expected=expected,actual=actual):
                        k=f.knowledge();self.add(k,'effect',effect,status=expected)
                        s=f.chief(f.state());s.case.apply([f.fact(status=actual)])
                        entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
                        refs=(*entry.supports,*entry.against)
                        activated=any(r.graph_ref.id==str(f.OW.effectAssociation) for r in refs)
                        self.assertEqual(activated,actual==expected)
                        category=entry.supports if effect in {'support','strong_support'} else entry.against
                        self.assertEqual(any(r.graph_ref.id==str(f.OW.effectAssociation) for r in category),actual==expected)

    def test_partial_strong_pattern_has_no_active_effect_or_automatic_opposition(self):
        k=f.knowledge();f.add_pattern(k,'partial',f.OW.Complaint,[(f.OW.Quality,dict(kind='concept',concept=str(f.OW.Dull)))])
        s=f.chief(f.state());entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
        self.assertFalse(any(r.graph_ref.id==str(f.OW.partialAssociation) for r in (*entry.supports,*entry.against)))
        s.case.apply([f.fact(status='absent')]);entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
        self.assertFalse(any(r.graph_ref.association_id==str(f.OW.partialAssociation) for r in entry.unresolved))
        self.assertFalse(entry.against)

    def test_against_only_does_not_expand_new_candidate_but_keeps_current_prior_path(self):
        k=f.knowledge();self.add(k,'negativeOnly','against',target=f.OW.Other)
        s=f.state();s.case.apply([f.fact('other',target='Other symptom')])
        self.assertNotIn(str(f.OW.Beta),graph_candidates(s.case,k))
        s.case.assessment=Assessment(differential=(DifferentialEntry(kind='disease',name='Disease beta'),),
            based_on_case_revision=s.case.revision,based_on_chief_fact_id=None)
        self.assertIn(str(f.OW.Beta),graph_candidates(s.case,k))

    def test_family_member_and_time_scope_preserve_unresolved_question(self):
        k=f.knowledge();self.context(k)
        scope=dict(subject='family',subject_member='mother',time_context='any')
        self.add(k,'mother','strong_support',target=f.OW.FamilyContext,scope=scope)
        s=f.chief(f.state('ContextFactor'))
        s.case.apply([f.fact('father',kind='context',target='Family history',subject='family',subject_member='father',
            time_context='past',observation_id='father',episode_id=None,category='family_history')])
        entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
        self.assertFalse(any(r.graph_ref.id==str(f.OW.motherAssociation) for r in entry.supports))
        missing=next(r for r in entry.unresolved if r.graph_ref.association_id==str(f.OW.motherAssociation))
        self.assertEqual(missing.scope[3:6],('family','mother','unspecified'))
        self.assertEqual(missing.scope[-2:],('',''))

    def test_named_member_negative_does_not_establish_whole_family_absence(self):
        k=f.knowledge();self.context(k)
        self.add(k,'whole','against',target=f.OW.FamilyContext,status='absent',
            scope=dict(subject='family',subject_member=None,time_context='any'))
        for member,active in [('mother',False),(None,True)]:
            s=f.chief(f.state());s.case.apply([f.fact('family',kind='context',target='Family history',status='absent',
                subject='family',subject_member=member,time_context='past',episode_id=None,category='family_history')])
            entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
            self.assertEqual(any(r.graph_ref.id==str(f.OW.wholeAssociation) for r in entry.against),active)

    def test_any_context_rule_resolves_with_current_fact_without_reasking(self):
        k=f.knowledge();c=f.consultation(prepared=f.resources(k));s=f.chief(f.state('ContextFactor'))
        s.case.apply([f.fact('context',kind='context',target='Test history',time_context='current',category='medical_history')])
        session=c.sessions['ContextFactor'];session.candidate_ids=(str(f.OW.Alpha),)
        session.prepare_context(s)
        self.assertFalse(s.interview.queue)

    def test_past_and_family_target_scopes_match_without_current_patient_leakage(self):
        for subject,member,timing in [('patient',None,'past'),('family','mother','past')]:
            k=f.knowledge();self.add(k,'scoped','support',scope=dict(subject=subject,subject_member=member,time_context=timing))
            s=f.chief(f.state());s.case.apply([f.fact('scoped',subject=subject,subject_member=member,time_context=timing,
                observation_id='past-observation',episode_id='past-episode')])
            entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
            ref=next(r for r in entry.supports if r.graph_ref.id==str(f.OW.scopedAssociation))
            self.assertEqual(ref.fact_ids,('scoped',))

    def test_attribute_presence_prerequisite_uses_the_exact_member_and_time(self):
        k=f.knowledge();c=f.consultation(prepared=f.resources(k));s=f.chief(f.state('DifferentialDiagnosis'))
        spec=c.tools._spec(s,str(f.OW.Complaint),str(f.OW.Quality),'family-observation','family-episode',
            subject='family',subject_member='mother',time_context='past')
        self.assertFalse(c.tools._eligible(s,spec))
        s.case.apply([f.fact('mother',subject='family',subject_member='mother',time_context='past',
            observation_id='family-observation',episode_id='family-episode')])
        self.assertTrue(c.tools._eligible(s,spec))
        wrong=dict(spec,subject_member='father');self.assertFalse(c.tools._eligible(s,wrong))

    def test_any_exam_rule_uses_concrete_question_scope_and_cannot_examine_a_relative(self):
        k=f.knowledge();k.questions[str(f.OW.ExamX)]=QuestionTemplate(text='가상 진찰을 하겠습니다',time_context='current')
        self.add(k,'anyExam','support',target=f.OW.ExamX,scope=dict(subject='patient',subject_member=None,time_context='any'))
        c=f.consultation(prepared=f.resources(k));s=f.chief(f.state('DifferentialDiagnosis'))
        entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
        ref=next(r for r in entry.unresolved if r.graph_ref.association_id==str(f.OW.anyExamAssociation))
        self.assertEqual(ref.scope[5],'current')
        self.assertIsNone(c.tools._spec(s,str(f.OW.ExamX),subject='family',subject_member='mother'))

    def test_attribute_only_pattern_offers_presence_before_attribute(self):
        k=f.knowledge();f.add_pattern(k,'attributeOnly',f.OW.Other,[(f.OW.Quality,dict(kind='concept',concept=str(f.OW.Dull)))],presence=False)
        k._graph.add((f.OW.Other,f.OW.hasAttribute,f.OW.Quality));k.validate_graph()
        s=f.chief(f.state('DifferentialDiagnosis'));s.case.apply([f.fact('unknown',target='Other symptom',status='unknown',observation_id='other',episode_id='other')])
        c=f.consultation(prepared=f.resources(k));work=c.differential.prepare_decision(s)
        options=[q for q in work.payload['questions'] if q['target']=='Other symptom']
        self.assertTrue(options);self.assertTrue(all(q.get('attribute') is None for q in options))

    def test_first_dd_action_contains_effect_scope_and_whole_pattern(self):
        k=f.knowledge();f.add_pattern(k,'compound',f.OW.Complaint,[(f.OW.Quality,dict(kind='concept',concept=str(f.OW.Dull)))])
        k._graph.set((f.OW.compoundFeature0,f.OW.expectedStatus,Literal('present')));k.validate_graph()
        c=f.consultation(prepared=f.resources(k));s=f.chief(f.state('ChiefComplaint'))
        c.sessions['ChiefComplaint'].close(s,c.client);s.interview.current='DifferentialDiagnosis'
        payload=c.differential.prepare_decision(s,mode='action').payload
        self.assertEqual(payload['evidence'],{})
        entries=[entry for q in payload['questions'] for values in q['expected_by_disease'].values() for entry in values]
        self.assertTrue(entries)
        self.assertTrue(all(entry['effect'] and entry['rule_scope'] and entry['full_pattern'] for entry in entries))
        self.assertTrue(any(feature['expected_status']=='present' and feature['expected']=='dull'
            for entry in entries for feature in entry['full_pattern']))


if __name__=='__main__': unittest.main()
