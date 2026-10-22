import copy
import unittest

import fixtures as f
from brain_double import clinical_response
from knowledge.conditions import ExpectedValue, FeatureCondition, numeric_match
from workflow.rules.assessment import graph_candidates, match_feature
from workflow.state.evidence import EvidenceRecord
from workflow.state.models import Answer, ObservedNumber, Question


class BrainTests(unittest.TestCase):
    def test_partial_features_keep_general_support(self):
        s,k=f.chief(f.state()),f.knowledge()
        entry=graph_candidates(s.case,k)[str(f.OW.Alpha)].entry
        self.assertTrue(any(r.graph_ref.id==str(f.OW.alphaBase) for r in entry.supports))
        self.assertTrue(any(r.scope[2]=='Location' for r in entry.unresolved))
        s.case.apply([f.fact('repeat',source_ref='other-source')])
        repeated=graph_candidates(s.case,k)[str(f.OW.Alpha)].entry
        self.assertEqual(len(repeated.supports),len(entry.supports))
        s.case.apply([f.fact('loc',kind='attribute',attribute='Location',values=('head',),category=None)])
        entry=graph_candidates(s.case,k)[str(f.OW.Alpha)].entry
        self.assertTrue(any(r.graph_ref.id==str(f.OW.alphaLocation) for r in entry.supports))
        s.case.apply([f.fact('loc',kind='attribute',attribute='Location',values=('head',),status='absent',category=None)])
        contradicted=graph_candidates(s.case,k)[str(f.OW.Alpha)].entry
        self.assertTrue(any(r.graph_ref.id==str(f.OW.alphaBase) for r in contradicted.supports))
        self.assertFalse(any('loc' in r.fact_ids for r in contradicted.against))

    def test_no_positive_support_gate_and_new_fact_candidate_expansion(self):
        c,s=f.consultation(),f.state('DifferentialDiagnosis')
        s.case.apply([f.fact(status='unknown')])
        c.differential.decide(s,c.client)
        self.assertTrue(s.case.assessment.differential)
        self.assertTrue(all(not e.supports for e in s.case.assessment.differential))
        k=f.knowledge();f.add_pattern(k,'newOther',f.OW.Other,[],disease=f.OW.Beta)
        s=f.state();s.case.apply([f.fact('other',target='Other symptom')])
        self.assertIn(str(f.OW.Beta),graph_candidates(s.case,k))

    def test_applicability_is_separate_from_feature_matches(self):
        k=f.knowledge()
        f.add_pattern(k,'conditional',f.OW.Complaint,[],applicability=[dict(concept_id=str(f.OW.Context),
            status='present',subject='patient',time_context='current')])
        for status in ('unknown','absent','present'):
            s=f.chief(f.state());s.case.apply([f.fact('ctx',kind='context',target='Test history',status=status,category=None)])
            entry=graph_candidates(s.case,k)[str(f.OW.Beta)].entry
            refs=[r for r in (*entry.supports,*entry.against) if r.graph_ref.id==str(f.OW.conditionalAssociation)
                or r.graph_ref.association_id==str(f.OW.conditionalAssociation)]
            self.assertEqual(bool(refs),status=='present')
            if status=='unknown': self.assertTrue(any(r.reason=='applicability_unknown' for r in entry.unresolved))

    def test_different_episode_cannot_complete_pattern(self):
        k,s=f.knowledge(),f.chief(f.state())
        s.case.apply([f.fact('attr',kind='attribute',attribute='Location',values=('head',),
            observation_id='other',episode_id='other',category=None)])
        entry=graph_candidates(s.case,k)[str(f.OW.Alpha)].entry
        self.assertFalse(any(r.graph_ref.id==str(f.OW.alphaLocation) for r in entry.supports))

    def test_correction_reclassifies_evidence_and_numeric_mismatch_keeps_actual_ref(self):
        c,s=f.consultation(),f.chief(f.state('DifferentialDiagnosis'))
        c.differential.decide(s,c.client)
        s.case.apply([f.fact(status='absent')]);c.differential.decide(s,c.client)
        self.assertFalse(any('chief' in r.fact_ids for e in s.case.assessment.differential for r in e.against))
        self.assertFalse(any('chief' in r.fact_ids for e in s.case.assessment.differential for r in e.supports))
        feature=FeatureCondition(id='numeric',attribute=str(f.OW.Location),
            expected=ExpectedValue(kind='quantity',value=3,unit='day',operator='ge'))
        actual=EvidenceRecord(id='actual',kind='attribute',target=str(f.OW.Complaint),status='present',
            attribute=str(f.OW.Location),measurement=ObservedNumber(kind='quantity',value=1,unit='day'))
        self.assertEqual(match_feature(c.knowledge,feature,[],[actual]),('contradicted',('actual',)))

    def test_one_question_keeps_disease_specific_expected_answers(self):
        k=f.knowledge()
        f.add_pattern(k,'elsewhere',f.OW.Complaint,[(f.OW.Location,dict(kind='concept',concept=str(f.OW.Elsewhere)))])
        c,s=f.consultation(prepared=f.resources(k)),f.chief(f.state('DifferentialDiagnosis'))
        payload=c.differential.prepare_decision(s).payload
        location=[q for q in payload['questions'] if q.get('attribute')=='Location']
        self.assertEqual(len(location),1);self.assertEqual(len(location[0]['expected_by_disease']),2)
        expected={payload['relations'][row['relation']]['full_pattern'][row['feature']]['expected']
            for rows in location[0]['expected_by_disease'].values() for row in rows}
        self.assertEqual(expected, {'head', 'abdomen'})

    def test_rank_rejects_unregistered_duplicate_or_omitted_previous_candidates(self):
        for mode in ('unknown','duplicate','omitted'):
            c,s=f.consultation(),f.chief(f.state('DifferentialDiagnosis'))
            c.differential.decide(s,c.client);old=s.case.assessment
            def bad(payload):
                if payload['task']=='clinical_decision':
                    rank=payload['prior_order'][:1] if mode=='omitted' else ['missing'] if mode=='unknown' else ['d_1','d_1']
                    return dict(ranked_disease_refs=rank,next_action={'kind':'finish_collection'})
            c.client.chat_handler=bad
            s.case.apply([f.fact('loc',kind='attribute',attribute='Location',values=('head',),category=None)])
            c.differential.decide(s,c.client)
            self.assertEqual(s.case.assessment,old)
            self.assertNotEqual(s.case.assessment.based_on_case_revision,s.case.revision)
            s.interview.queue.clear();c.differential.close(s,c.client)
            self.assertEqual(s.case.primary().kind, 'disease')
            self.assertEqual(s.case.assessment.differential, old.differential)
            self.assertEqual(s.case.assessment.based_on_case_revision, old.based_on_case_revision)

    def test_grouped_question_retains_applicability_and_expected_negative_context(self):
        k=f.knowledge()
        f.add_pattern(k,'conditionalAbsent',f.OW.Complaint,[],applicability=[dict(concept_id=str(f.OW.Context),
            status='absent',subject='patient',time_context='current')])
        c,s=f.consultation(prepared=f.resources(k)),f.chief(f.state('ChiefComplaint'))
        c.sessions['ChiefComplaint'].close(s,c.client)
        s.interview.current='ContextFactor'
        context=c.sessions['ContextFactor']
        c.enter_session(s);context.prepare_context(s)
        self.assertTrue(any(q.target=='Test history' and q.time_context=='current' for q in s.interview.queue))
        details=graph_candidates(s.case,k)[str(f.OW.Beta)].details
        self.assertTrue(any(condition['status']=='absent' for detail in details for condition in detail['conditions']))

    def test_valid_ranking_survives_bad_question_and_action_only_repair(self):
        k=f.knowledge();f.add_pattern(k,'strongChief',f.OW.Complaint,[],disease=f.OW.Alpha)
        self.assertTrue(any(p.effect=='strong_support' for p in k.get_disease_patterns(str(f.OW.Alpha))))
        for invalid in ('unregistered_question', 'missing_action', 'wrong_type'):
            with self.subTest(invalid=invalid):
                tasks=[]
                def reply(payload):
                    tasks.append(payload['task']);value=clinical_response(payload)
                    if payload['task']=='clinical_decision':
                        value['ranked_disease_refs'].reverse()
                        if invalid=='missing_action':
                            value.pop('next_action')
                        else:
                            value['next_action']=7 if invalid=='wrong_type' else {'kind':'ask','question_ref':'missing'}
                    return value
                c,s=f.consultation(f.FakeSDK(chat_handler=reply),f.resources(k)),f.chief(f.state('DifferentialDiagnosis'))
                c.differential.decide(s,c.client)
                self.assertEqual(tasks,['clinical_decision','clinical_action'])
                self.assertEqual(s.case.assessment.differential[0].name,'Disease beta')
                s.interview.queue.clear();c.close_collection(s);c.writer.build_soap(s)
                self.assertEqual(s.turn.payload['diagnosis'],'Disease beta')
                self.assertIn('Disease beta',s.turn.payload['note']['A']['evidence'])

    def test_against_is_code_owned_and_unknown_response_runs_one_dd_decision(self):
        c,s=f.consultation(),f.chief(f.state('DifferentialDiagnosis'))
        s.case.apply([f.fact(status='absent')]);c.differential.decide(s,c.client)
        old=copy.deepcopy(s.case.assessment);calls=len(c.client.requests)
        s.interview.answers.append(Answer(question_id='unknown',source_ref='unknown',scope='DifferentialDiagnosis',
            purpose='feature',outcome='unknown'))
        c.differential.decide(s,c.client)
        self.assertEqual(len(c.client.requests),calls+1)
        self.assertEqual([e.against for e in old.differential],[e.against for e in s.case.assessment.differential])

    def test_freeze_blocks_input_and_submission_repair_does_not_call_llm(self):
        c,s=f.consultation(),f.chief(f.state('DifferentialDiagnosis'));c.close_collection(s)
        before=s.case.model_dump()
        with self.assertRaises(ValueError): s.case.apply([f.fact(status='absent')])
        c.writer.build_soap(s);calls=len(c.client.requests);c.repair_submission(s)
        self.assertEqual(calls,len(c.client.requests));self.assertEqual(before,s.case.model_dump())

    def test_family_member_and_chief_attribute_completion_scopes(self):
        c,s=f.consultation(),f.chief(f.state('ChiefComplaint',initialized=True))
        s.case.apply([f.fact('other',kind='attribute',target='Other symptom',attribute='Quality',values=('dull',),
            observation_id='other',episode_id='other',category='quality')])
        self.assertEqual(c.tools.chief_statuses(s)['Quality'],'unasked')
        mother=Question(item_id='mother',purpose='context',text='병력이 있나요?',target='Test history',
            subject='family',subject_member='mother')
        father=mother.model_copy(update={'item_id':'father','subject_member':'father'})
        self.assertNotEqual(mother.semantic_key(),father.semantic_key())
        c.questions.complete(s,mother,'mother',outcome='unknown')
        self.assertFalse(c.tools.was_asked(s,'Test history',subject='family',subject_member='father'))

    def test_calendar_and_open_world_truth_tables(self):
        for a,unit,b,other,result in [(1,'year',12,'month','matched'),(1,'month',30,'day','unknown')]:
            self.assertEqual(numeric_match(ExpectedValue(kind='quantity',value=a,unit=unit),
                ObservedNumber(kind='quantity',value=b,unit=other)),result)
        k=f.knowledge()
        for selection,positive,negative,result in [('any_of',['Here'],[],'matched'),('all_of',['Here'],[],'unknown'),
            ('any_of',[],['Here'],'unknown'),('all_of',['Here'],['Elsewhere'],'contradicted')]:
            feature=FeatureCondition(id='set',attribute=str(f.OW.Location),expected=ExpectedValue(kind='concept_set',
                concepts=[str(f.OW.Here),str(f.OW.Elsewhere)],selection=selection))
            rows=[EvidenceRecord(id=status,kind='attribute',target=str(f.OW.Complaint),status=status,
                attribute=str(f.OW.Location),values=tuple(str(f.OW[v]) for v in values))
                for status,values in [('present',positive),('absent',negative)] if values]
            self.assertEqual(match_feature(k,feature,[],rows)[0],result)
