import json
import math
import unittest

import fixtures as f
from workflow.input_types import ContextStatement
from workflow.rules.normalization import candidate_contracts, exact_mapping, validate_mapping, strict_json
from workflow.state.models import Question, ObservedNumber
from workflow.state.evidence import EvidenceIndex


class BindingTests(unittest.TestCase):
    def test_exact_binding_calls_context_once_and_no_mapper(self):
        s,c,client = f.interpret([f.statement()])
        self.assertEqual([p['task'] for p in client.requests],['input_context'])
        self.assertEqual(s.case.chief().target,'Test complaint')
        self.assertIsNone(s.turn)
        self.assertEqual(s.case.presenting_text, 'Reported complaint')

    def test_prior_care_denial_and_observation_are_notes_without_mapping_calls(self):
        rows = [f.statement('No treatment',target_terms=['treatment'],assertion='absent',record_category='previous_care',
                            note_value='No previous treatment'),
                f.statement('Just observing',target_terms=['observation'],record_category='previous_care',
                            note_value='Watchful observation only')]
        s,c,client = f.interpret(rows,s=f.chief(f.state()),q=Question(item_id='care',purpose='intake',
            text='치료받으셨나요?',target='Test complaint',category='previous_care',coverage=True))
        self.assertEqual(len(f.graph_facts(s.case)),1)
        self.assertEqual(len(f.unbound(s.case)),2)
        self.assertEqual([p['task'] for p in client.requests],['input_context'])
        c.close_collection(s)
        c.writer.build_soap(s)
        self.assertIn('No previous treatment (-)',s.turn.payload['note']['S']['hpi'])
        self.assertIn('Watchful observation only (+)',s.turn.payload['note']['S']['hpi'])
        self.assertEqual(s.case.chief(confirmed=True).status,'present')

    def test_multiple_targets_scopes_and_attribute_values_stay_independent(self):
        rows = [f.statement('Complaint',primary_concern=True),
                f.statement('Both sites',focus='attribute',attribute_terms=['Location'],value_terms=['head','abdomen'],anchor=0),
                f.statement('Other',target_terms=['Other symptom']),
                f.statement('Mother',target_terms=['Test complaint'],subject='family',subject_member='mother',time_context='past'),
                f.statement('Earlier',target_terms=['Test complaint'],time_context='past')]
        s,c,_ = f.interpret(rows)
        self.assertEqual(len(f.graph_facts(s.case)),5)
        location = next(fact for fact in s.case.facts.values() if fact.attribute)
        self.assertEqual(set(location.values),{'head','abdomen'})
        self.assertEqual(location.observation_id,s.case.chief().observation_id)
        self.assertEqual(len({fact.id for fact in s.case.facts.values()}),5)
        self.assertEqual(s.case.chief().subject,'patient')
        self.assertTrue(any(fact.subject_member=='mother' for fact in s.case.facts.values()))

    def test_two_presenting_targets_require_primary_choice(self):
        s,c,_ = f.interpret([f.statement('Complaint'),f.statement('Other',target_terms=['Other symptom'])])
        self.assertIsNone(s.case.chief())
        c.sessions["ChiefComplaint"].prepare(s)
        self.assertTrue(s.interview.queue[0].primary_choice)
        self.assertEqual(len(f.graph_facts(s.case)),2)

    def test_attribute_scoped_value_names_never_cross_attributes(self):
        k = f.knowledge()
        from rdflib import RDF,RDFS,Literal
        k._graph.add((f.OW.Laterality,RDF.type,f.OW.FindingAttribute))
        k._graph.add((f.OW.Laterality,RDFS.label,Literal('Laterality',lang='en')))
        k._graph.add((f.OW.OtherHead,RDF.type,f.OW.AttributeValue))
        k._graph.add((f.OW.OtherHead,RDFS.label,Literal('head',lang='en')))
        k._graph.add((f.OW.Laterality,f.OW.canHaveValue,f.OW.OtherHead))
        k.prepare_terms()
        self.assertNotEqual(k.value_id('Location','head'),k.value_id('Laterality','head'))
        self.assertIsNone(k.value_id('Quality','head'))
        statement = ContextStatement(**f.statement(focus='attribute',attribute_terms=['Quality'],value_terms=['head']))
        contracts = candidate_contracts(k,statement,None)
        with self.assertRaises(ValueError):
            validate_mapping({'Test complaint':{'Quality':'head'}},statement,contracts)

    def test_duplicate_context_row_repair_preserves_valid_sibling(self):
        count = 0
        def response(payload):
            nonlocal count
            if payload['task'] != 'input_context':
                return None
            count += 1
            if count == 1:
                return {'statements':[f.statement('Complaint'),f.statement('Foreign',observation_id='foreign')]}
            self.assertEqual(payload['statement_indices'],[1])
            return {'statements':[f.statement('Foreign',target_terms=['Other symptom'])]}
        s,c,client = f.interpret([],text='Complaint Foreign',responses=response)
        self.assertEqual(len(f.graph_facts(s.case)),2)
        self.assertEqual(count,2)

    def test_failed_context_row_does_not_erase_valid_sibling(self):
        def response(payload):
            return {'statements':[f.statement('Complaint'),f.statement('Not in input')]} if payload['phase']=='context' else '{'
        s,c,_ = f.interpret([],text='Complaint',responses=response)
        self.assertEqual(len(f.graph_facts(s.case)),1)
        self.assertEqual(s.case.chief().target,'Test complaint')

    def test_unknown_empty_and_acknowledgement_always_call_context_without_false_presence(self):
        for text in ('','모르겠어요','알겠습니다'):
            with self.subTest(text=text):
                row = f.statement(text or ' ',role='unknown',target_terms=[],assertion='unknown')
                s,c,client = f.interpret([] if not text else [row],text=text)
                self.assertTrue(client.requests)
                self.assertFalse(f.graph_facts(s.case))

    def test_conditional_negative_is_not_general_absence(self):
        s,c,_ = f.interpret([f.statement('Current'),f.statement('Only sometimes absent',assertion='absent',
            polarity_scope='qualified',observation_id=None)])
        records = EvidenceIndex.from_case(s.case,c.knowledge).entries
        self.assertTrue(any(record.status=='present' for record in records))
        self.assertFalse(any(record.status=='absent' for record in records))

    def test_negative_attribute_does_not_negate_target(self):
        s,c,_ = f.interpret([f.statement('Complaint'),f.statement('Not head',focus='attribute',assertion='absent',
            attribute_terms=['Location'],value_terms=['head'],anchor=0)])
        self.assertEqual(s.case.chief().status,'present')
        attr = next(x for x in s.case.facts.values() if x.attribute)
        self.assertEqual(attr.status,'absent')
        self.assertEqual(attr.values,('head',))

    def test_mapping_review_only_unresolved_siblings(self):
        calls = []
        def response(payload):
            if payload['task']=='input_context':
                return {'statements':[f.statement('Exact'),f.statement('Ambiguous',target_terms=['test'])]}
            calls.append(payload)
            if payload['phase']=='mapping':
                return [{}]
            return [{'Test complaint':'(+)'}]
        s,c,_ = f.interpret([],text='Exact Ambiguous',responses=response)
        self.assertEqual([p['phase'] for p in calls],['mapping','mapping_repair'])
        self.assertTrue(all(p['statement_indices']==[1] for p in calls))
        self.assertEqual(len(f.graph_facts(s.case)),2)
        self.assertEqual(sum(fact.binding=='broader' for fact in s.case.facts.values()),1)
        self.assertFalse(any(not row['candidates'] for p in calls for row in p['statements']))

    def test_bad_mapping_json_has_one_repair_then_preserves_unbound_note(self):
        calls = []
        def response(payload):
            if payload['task']=='input_context':
                return {'statements':[f.statement('Ambiguous',target_terms=['test'])]}
            calls.append(payload['phase'])
            return '{'
        s,c,_ = f.interpret([],text='Ambiguous',responses=response)
        self.assertEqual(calls,['mapping','mapping_repair'])
        self.assertFalse(f.graph_facts(s.case))
        self.assertEqual(next(iter(f.unbound(s.case).values())).value, 'test')

    def test_unrepresentable_number_preserved_as_note_without_evidence(self):
        row = f.statement('Growing 3 cm each year',focus='attribute',target_terms=['growth rate'],
            record_category='course',measurement={'kind':'quantity','value':3,'unit':'cm/year','approximate':True})
        s,c,client = f.interpret([row])
        self.assertFalse(f.graph_facts(s.case))
        self.assertEqual(len(f.unbound(s.case)),1)
        self.assertEqual(next(iter(f.unbound(s.case).values())).measurement.unit,'cm/year')
        self.assertTrue(next(iter(f.unbound(s.case).values())).measurement.approximate)
        self.assertFalse(EvidenceIndex.from_case(s.case,c.knowledge).entries)
        self.assertEqual(len(client.requests),1)

    def test_orphan_registered_attribute_is_record_only(self):
        row = f.statement('head',focus='attribute',attribute_terms=['Location'],value_terms=['head'])
        s,c,_ = f.interpret([row])
        attr = next(iter(s.case.facts.values()))
        self.assertIsNotNone(attr.graph_binding)
        self.assertFalse(EvidenceIndex.from_case(s.case,c.knowledge).entries)
        self.assertIsNone(s.case.chief())

    def test_explicit_correction_preserves_channel_scope_and_audit(self):
        s = f.chief(f.state())
        row = f.statement('Actually absent',assertion='absent',correction_id='chief',observation_id='obs1',episode_id='episode1')
        q = Question(item_id='correct',purpose='clarification',text='다시 확인할게요.',target='Test complaint',
            observation_id='obs1',episode_id='episode1',time_context='current')
        events = []
        s,c,_ = f.interpret([row],s=s,q=q,audit=lambda event,**data:events.append((event,data)))
        self.assertEqual(s.case.facts['chief'].status,'absent')
        self.assertIsNone(s.case.chief())
        self.assertTrue(events)
        s = f.state()
        s.case.apply([f.fact(acquisition='initial')])
        s,c,_ = f.interpret([row],s=s,q=q)
        self.assertEqual(s.case.facts['chief'].status,'present')

    def test_home_report_cannot_create_exam_and_actual_exam_can(self):
        row = f.statement('Finding',target_terms=['Test examination finding'])
        s,c,_ = f.interpret([row])
        self.assertFalse(f.graph_facts(s.case))
        self.assertEqual(len(f.unbound(s.case)),1)
        q = Question(item_id='exam',kind='EXAM',purpose='feature',text='진찰하겠습니다.',target='Test examination finding')
        s,c,_ = f.interpret([row],q=q)
        self.assertTrue(any(x.kind=='finding' and x.acquisition=='EXAM' for x in s.case.facts.values()))

    def test_numbers_reject_nonfinite_strings_bounds_and_comparison_invention(self):
        for raw in ({'kind':'quantity','value':float('nan'),'unit':'cm'},
                    {'kind':'quantity','value':'3','unit':'cm'},
                    {'kind':'quantity','value':3,'unit':'cm','operator':'gt'},
                    {'kind':'interval','lower':3,'upper':2,'unit':'day'}):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                ObservedNumber(**raw)
        for raw in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(raw)

    def test_demographics_and_raw_dialogue_are_private_to_interpreter(self):
        def response(payload):
            return {'statements':[f.statement('Complaint')],
                'patient_context':[{'key':'age','value':'7 years','quote':'7 years'}]}
        s,c,_ = f.interpret([],text='7 years Complaint',responses=response)
        self.assertEqual({n.context_key:n.value for n in f.unbound(s.case).values()},{'age':'7 years'})
        self.assertFalse(hasattr(c.ear,'patient_context'))
        self.assertNotIn('Complaint',str(f.unbound(s.case)))

    def test_initial_chief_review_shares_the_context_repair(self):
        phases = []
        def response(payload):
            phases.append(payload['phase'])
            row = f.statement('Complaint',primary_concern=True)
            if payload['phase']=='context':
                row.update(role='uncertain',assertion='uncertain')
            return {'statements':[row]}
        s,c,_ = f.interpret([],text='Complaint',responses=response)
        self.assertEqual(phases,['context','context_repair'])
        self.assertIsNotNone(s.case.chief(confirmed=True))


if __name__=='__main__':
    unittest.main()

class NumericAndScopeTests(unittest.TestCase):
    def test_registered_number_preserves_approximation_boundaries_and_canonical_terms(self):
        k=f.knowledge()
        from rdflib import RDF,RDFS,Literal
        k._graph.add((f.OW.EpisodeDuration,RDF.type,f.OW.FindingAttribute))
        k._graph.add((f.OW.EpisodeDuration,RDFS.label,Literal('Episode duration',lang='en')))
        f.add_pattern(k,'duration',f.OW.Complaint,[(f.OW.EpisodeDuration,{'kind':'quantity','value':2.0,'unit':'h','operator':'gt'})])
        row=f.statement('about 1 to 2 hours',focus='attribute',attribute_terms=['Episode duration'],
            measurement={'kind':'interval','lower':1,'upper':2,'unit':'h','upper_inclusive':False,'approximate':True},anchor=0)
        s,c,client=f.interpret([f.statement('Complaint'),row],k=k)
        attr=next(fact for fact in s.case.facts.values() if fact.attribute)
        self.assertEqual(attr.target,'Test complaint')
        self.assertEqual(attr.attribute,'Episode duration')
        self.assertFalse(attr.measurement.upper_inclusive)
        self.assertTrue(attr.measurement.approximate)
        self.assertEqual(len(client.requests),1)
        c.close_collection(s)
        c.writer.build_soap(s)
        self.assertIn('approximately',s.turn.payload['note']['S']['hpi'])
        self.assertNotIn('urn:',s.turn.payload['note']['S']['hpi'])

    def test_family_members_and_measurement_times_do_not_merge(self):
        rows=[f.statement('Mother',subject='family',subject_member='mother',time_context='past'),
              f.statement('Father',subject='family',subject_member='father',time_context='past',assertion='absent'),
              f.statement('Now',time_context='current'),f.statement('Earlier',time_context='past',assertion='absent')]
        s,c,_=f.interpret(rows)
        self.assertEqual(len(s.case.current_facts()),4)
        self.assertEqual({r.subject_member for r in s.case.current_facts() if r.subject=='family'},{'mother','father'})
        self.assertEqual(s.case.chief(confirmed=True).time_context,'current')

    def test_domain_history_denial_creates_note_and_no_individual_negative(self):
        s,c,client=f.interpret([f.statement('No history',assertion='absent',assertion_scope='domain',
            target_terms=['Test history'],record_category='medical_history',note_value='No reported medical history')])
        self.assertFalse(f.graph_facts(s.case))
        self.assertEqual(len(f.unbound(s.case)),1)
        self.assertEqual(len(client.requests),1)

    def test_unregistered_numeric_note_preserves_upper_unit_and_exclusive_bounds(self):
        row=f.statement('Mixed interval',focus='attribute',record_category='measurement',target_terms=['Growth observation'],
            measurement={'kind':'interval','lower':1,'unit':'year','upper':18,'upper_unit':'month','upper_inclusive':False})
        s,c,_=f.interpret([row])
        note=next(iter(f.unbound(s.case).values()))
        self.assertEqual(note.measurement.upper_unit,'month')
        self.assertFalse(note.measurement.upper_inclusive)
        self.assertFalse(f.graph_facts(s.case))
        c.close_collection(s)
        self.assertIsNone(s.session.termination)
        self.assertTrue(s.case.assessment.frozen)
        self.assertFalse(s.case.primary().supports)

    def test_bad_correction_cannot_change_target_subject_or_episode(self):
        for change in ({'subject':'family','subject_member':'mother'}, {'target_terms':['Other symptom']}, {'episode_id':'foreign'}):
            s=f.chief(f.state())
            row=f.statement('Correction',assertion='absent',correction_id='chief',observation_id='obs1',episode_id='episode1',**{
                k:v for k,v in change.items() if k!='episode_id'})
            row.update(change)
            q=Question(item_id='q',purpose='clarification',text='다시 확인할게요.',target='Test complaint',
                observation_id='obs1',episode_id='episode1',time_context='current')
            s,c,_=f.interpret([row],s=s,q=q)
            self.assertEqual(s.case.facts['chief'].status,'present')

    def test_past_context_cannot_complete_a_current_target_question(self):
        q=Question(item_id='current',purpose='feature',text='지금 증상이 있나요?',target='Other symptom',
                   time_context='current',observation_id='obs2',episode_id='episode2')
        s,c,_=f.interpret([f.statement('Past only',target_terms=['Other symptom'],time_context='past')],q=q)
        self.assertEqual(s.interview.answers[-1].outcome,'unknown')
        self.assertFalse(c.tools.has_resolved_evidence(s,'Other symptom',time_context='current'))
        self.assertTrue(any(fact.target=='Other symptom' and fact.time_context=='past' for fact in s.case.facts.values()))

    def test_clarification_resolves_only_its_matching_acquired_uncertainty(self):
        for target,resolved in [('Test complaint',True),('Other symptom',False)]:
            s=f.state()
            s.case.apply([f.fact(status='uncertain')])
            q=Question(item_id='clarify',purpose='clarification',text='다시 확인할게요.',target='Test complaint',
                observation_id='obs1',episode_id='episode1',time_context='current',clarifies_id='chief')
            row=f.statement('Confirmed',target_terms=[target])
            s,c,_=f.interpret([row],s=s,q=q)
            self.assertEqual('chief' not in {fact.id for fact in s.case.active_facts()},resolved)
