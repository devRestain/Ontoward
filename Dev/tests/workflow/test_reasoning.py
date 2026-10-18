from dataclasses import replace
import itertools
import unittest

import fixtures as f
from knowledge.conditions import ExpectedValue, FeatureCondition, numeric_match
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.state.evidence import EvidenceIndex, EvidenceRecord
from workflow.rules.selection import QuestionEvaluation, QuestionPath, answer_patch, answer_regions, decision_value, question_key


def scores(snapshot):
    return [(h.disease_id,h.score,h.evidence_score,h.chief_score,h.context_bonus,h.contradiction_penalty,
             h.chief_coverage,h.evidence_ids,h.contradiction_ids,h.unresolved_conditions,h.contradicted_conditions)
            for h in snapshot.hypotheses]


class ReasoningTests(unittest.TestCase):
    def test_joint_two_and_three_step_question_value_without_premature_support(self):
        for count in (1,2):
            k=f.knowledge()
            k._graph.remove((f.OW.Alpha,f.OW.hasSupportingContext,f.OW.Context))
            from rdflib import Literal
            k._graph.set((f.OW.betaExamAssociation,f.OW.predictiveness,Literal('zero')))
            conditions=[(f.OW.Quality,{'kind':'concept','concept':str(f.OW.Dull)})]
            if count==2:
                conditions.append((f.OW.Location,{'kind':'concept','concept':str(f.OW.Here)}))
            pattern=f.add_pattern(k,'jointOther',f.OW.Other,conditions)
            c,s=f.consultation(prepared=f.resources(k)),f.chief(f.state('DifferentialDiagnosis',initialized=True))
            base=c.reasoner.refresh_hypotheses(s)
            paths,_=c.planner._frontier(s,base,[h.disease_id for h in base.hypotheses])
            path=next(p for p in paths if p.pattern_id==str(pattern))
            self.assertEqual(len(path.specs),count+1)
            spec=path.specs[0]
            result=QuestionEvaluation(c.reasoner,base,[h.disease_id for h in base.hypotheses]).assess({question_key(spec):spec},[path])
            self.assertEqual(result[question_key(spec)]['direct_value'],0)
            self.assertGreater(result[question_key(spec)]['plan_value'],0)
            self.assertFalse(any(fact.target=='Other symptom' for fact in s.case.facts.values()))

    def test_conditional_pattern_requires_true_prerequisite(self):
        for status in ('present','absent','unknown'):
            k=f.knowledge()
            f.add_pattern(k,'conditional',f.OW.Other,[],applicability=[{'concept_id':str(f.OW.Context),
                'status':'present','subject':'patient','time_context':'current'}])
            c,s=f.consultation(prepared=f.resources(k)),f.chief(f.state())
            s.case.apply([f.fact('ctx',target='Test history',kind='context',status=status,category=None)])
            before=c.reasoner.refresh_hypotheses(s)
            spec=c.planner._spec(s,str(f.OW.Other),episode='episode1')
            after=c.reasoner.evaluate_delta(before,[answer_patch(spec)])
            difference=next(h.score for h in after.hypotheses if h.disease_id==str(f.OW.Beta))-next(h.score for h in before.hypotheses if h.disease_id==str(f.OW.Beta))
            self.assertEqual(difference,4 if status=='present' else 0)

    def test_observed_and_delta_match_full_evaluation_without_mutating_actual(self):
        c,s = f.consultation(),f.chief(f.state('DifferentialDiagnosis'))
        base = c.reasoner.refresh_hypotheses(s)
        before = s.model_dump()
        specs = [c.planner._spec(s,str(f.OW.Complaint),str(f.OW.Location),'obs1','episode1'),
                 c.planner._spec(s,str(f.OW.ExamX),episode='episode1'),
                 c.planner._spec(s,str(f.OW.Context),purpose='context',field='S.pmh')]
        for spec,status in itertools.product(specs,('present','absent','unknown')):
            patch = (answer_patch(spec,status=status,values=[str(f.OW.Here)] if spec['attribute_id'] else []),)
            after = c.reasoner.evaluate_delta(base,patch)
            full = c.reasoner.evaluate(base.evidence.patch(patch),base.chief)
            self.assertEqual(scores(after),scores(full))
        self.assertEqual(s.model_dump(),before)
        self.assertIs(c.reasoner._snapshot,base)

    def test_replacement_recomputes_both_old_and_new_dependencies(self):
        c,s = f.consultation(),f.chief(f.state())
        s.case.apply([f.fact('ctx',kind='context',target='Test history',category=None)])
        base = c.reasoner.refresh_hypotheses(s)
        for ident in ('chief','ctx'):
            original = next(r for r in base.evidence.raw if r.id==ident)
            for timing,status in itertools.product(('current','past','unspecified'),('present','absent','unknown')):
                patch = (replace(original,status=status,time_context=timing),)
                self.assertEqual(scores(c.reasoner.evaluate_delta(base,patch)),
                    scores(c.reasoner.evaluate(base.evidence.patch(patch),base.chief)))

    def test_common_support_zero_discrimination_and_exam_has_value(self):
        c,s = f.consultation(),f.chief(f.state())
        base = c.reasoner.refresh_hypotheses(s)
        candidates = [h.disease_id for h in base.hypotheses]
        spec = c.planner._spec(s,str(f.OW.Complaint),str(f.OW.Location),'obs1','episode1')
        outcomes = [c.reasoner.evaluate_delta(base,(answer_patch(spec,status=status,values=[str(f.OW.Here)]),))
                    for status in ('present','absent')]
        self.assertEqual(decision_value(base,outcomes,candidates,c.planner.knowledge.reasoning)[0],0)
        spec = c.planner._spec(s,str(f.OW.ExamX),episode='episode1')
        outcomes = [c.reasoner.evaluate_delta(base,(answer_patch(spec,status=status),)) for status in ('present','absent')]
        value = decision_value(base,outcomes,candidates,c.planner.knowledge.reasoning)
        self.assertGreater(value[0],0)
        self.assertEqual(value,decision_value(base,outcomes*3,list(reversed(candidates)),c.planner.knowledge.reasoning))

    def test_refinement_replaces_parent_and_duplicate_facts_do_not_inflate(self):
        c,s = f.consultation(),f.chief(f.state())
        base = c.reasoner.refresh_hypotheses(s)
        s.case.apply([f.fact('loc',kind='attribute',attribute='Location',values=('head',),category=None)])
        refined = c.reasoner.refresh_hypotheses(s)
        alpha = next(h for h in refined.hypotheses if h.disease_id==str(f.OW.Alpha))
        expected = next(p.score for p in c.planner.knowledge.get_disease_patterns(str(f.OW.Alpha)) if p.id==str(f.OW.locationX))
        self.assertEqual(alpha.evidence_score,expected)
        s.case.apply([f.fact('duplicate',kind='attribute',attribute='Location',values=('head',),category=None)])
        duplicate = c.reasoner.refresh_hypotheses(s)
        self.assertEqual([(h.disease_id,h.score) for h in refined.hypotheses],[(h.disease_id,h.score) for h in duplicate.hypotheses])
        self.assertTrue(all(h.evidence_score==1 for h in base.hypotheses))

    def test_other_episode_cannot_complete_chief(self):
        c,s = f.consultation(),f.chief(f.state())
        s.case.apply([f.fact('other',observation_id='obs2',episode_id='episode2'),
            f.fact('loc',kind='attribute',attribute='Location',values=('head',),category=None,observation_id='obs2',episode_id='episode2')])
        snapshot = c.reasoner.refresh_hypotheses(s)
        self.assertTrue(all(h.chief_score==1 for h in snapshot.hypotheses))

    def test_nonexclusive_values_and_only_explicit_value_conflicts(self):
        s = f.chief(f.state())
        s.case.apply([f.fact('a',kind='attribute',attribute='Location',values=('head',),category=None),
                     f.fact('b',kind='attribute',attribute='Location',values=('abdomen',),category=None)])
        self.assertTrue(all(r.status=='present' for r in s.case.current_facts()))
        s.case.apply([f.fact('neg',kind='attribute',attribute='Location',values=('head',),status='absent',category=None)])
        self.assertEqual(next(r for r in s.case.current_facts() if r.id=='chief').status,'present')
        self.assertTrue(all(r.status=='uncertain' for r in s.case.current_facts() if r.attribute))

    def test_numeric_threshold_calendar_and_approximation_truth_tables(self):
        rows = [('gt',2,'day',2,'day','contradicted'),('ge',2,'day',2,'day','matched'),
            ('lt',2,'day',2,'day','contradicted'),('le',2,'day',2,'day','matched'),
            ('eq',1,'year',12,'month','matched'),('eq',1,'month',30,'day','unknown'),
            ('eq',1.5,'h',90,'min','matched'),('eq',0,'NRS',0,'NRS','matched')]
        for operator,a,unit,b,other,expected in rows:
            with self.subTest(row=(operator,a,unit,b,other)):
                self.assertEqual(numeric_match(ExpectedValue(kind='quantity',value=a,unit=unit,operator=operator),
                    f.ObservedNumber(kind='quantity',value=b,unit=other)),expected)
        self.assertEqual(numeric_match(ExpectedValue(kind='quantity',value=3,unit='cm',operator='gt'),
            f.ObservedNumber(kind='interval',lower=2,upper=4,unit='cm')),'unknown')

    def test_categorical_any_all_open_world_truth_tables(self):
        reasoner = ClinicalReasoner(f.knowledge())
        for selection,positive,negative,expected in [('any_of',['Here'],[],'matched'),('any_of',[],['Here'],'unknown'),
                ('any_of',[],['Here','Elsewhere'],'contradicted'),('all_of',['Here'],[],'unknown'),
                ('all_of',['Here','Elsewhere'],[],'matched'),('all_of',['Here'],['Elsewhere'],'contradicted')]:
            feature = FeatureCondition(id='table',attribute=str(f.OW.Location),expected=ExpectedValue(kind='concept_set',
                concepts=[str(f.OW.Here),str(f.OW.Elsewhere)],selection=selection))
            records = [EvidenceRecord(id=status,target=str(f.OW.Complaint),kind='attribute',status=status,
                attribute=str(f.OW.Location),values=tuple(str(f.OW[v]) for v in values))
                for status,values in [('present',positive),('absent',negative)] if values]
            self.assertEqual(reasoner._match(feature,str(f.OW.Complaint),'present',[],records)[0],expected)

    def test_conflict_correction_delta_recovers_definite_status(self):
        a = EvidenceRecord(id='a',target='t',kind='symptom',status='present',observation_id='o',episode_id='e')
        b = replace(a,id='b',status='absent')
        index = EvidenceIndex.from_records([a,b])
        self.assertTrue(all(r.status=='uncertain' for r in index.entries))
        corrected = index.patch([replace(b,status='present')])
        self.assertTrue(all(r.status=='present' for r in corrected.entries))

    def test_question_simulations_are_local_and_do_not_change_patient_or_actual_cache(self):
        c,s = f.consultation(),f.chief(f.state('DifferentialDiagnosis'))
        base = c.reasoner.refresh_hypotheses(s)
        spec = c.planner._spec(s,str(f.OW.ExamX),episode='episode1')
        path = QuestionPath((spec,),None,str(f.OW.Beta),None)
        evaluation = QuestionEvaluation(c.reasoner,base,[h.disease_id for h in base.hypotheses])
        before = s.model_dump()
        assessment = evaluation.assess({question_key(spec):spec},[path])
        self.assertGreater(assessment[question_key(spec)]['utility'],0)
        self.assertEqual(s.model_dump(),before)
        self.assertIs(c.reasoner._snapshot,base)
        self.assertTrue(evaluation.cache)
        self.assertNotIn('outcomes',str(assessment))

    def test_unknown_context_does_not_supply_supporting_bonus(self):
        for status,expected in [('present',1),('absent',0),('unknown',0)]:
            c,s = f.consultation(),f.chief(f.state())
            s.case.apply([f.fact('ctx',kind='context',target='Test history',status=status,category=None)])
            h = next(h for h in c.reasoner.refresh_hypotheses(s).hypotheses if h.disease_id==str(f.OW.Alpha))
            self.assertEqual(h.context_bonus,expected)


if __name__=='__main__':
    unittest.main()
