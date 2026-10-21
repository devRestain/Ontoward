import copy
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ontoward_extraction.__main__ import configuration,build_identity
from ontoward_extraction.build import draft_catalog,draft_messages,phase_schema,accept_response,reference_ids
from ontoward_extraction.inputs import discover,index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical,digest,Concept,Condition
from ontoward_extraction.recovery import recover_draft
from support import inputs,nodes,relation


class DraftEndpointTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.vocabulary=nodes()
        self.config=configuration(Path(__file__).resolve().parents[1]/'config.api-luna.json')

    def source(self):
        return dict(disease=self.vocabulary[0],available_targets=[n for n in self.vocabulary if n['kind'] in {'Symptom','ExamFinding','ContextFactor'}],
            attributes_and_values=[n for n in self.vocabulary if n['kind'] in {'FindingAttribute','AttributeValue'}],source_material=[])

    def test_native_schema_rejects_wrong_roles_and_unknown_ids_preserving_new_typed_targets(self):
        data=[dict(job_id='job',input=self.source())];catalog,handles=draft_catalog(data)
        schema=phase_schema('draft',data);definitions=schema['$defs'];properties=definitions['Relation']['properties']
        pattern=properties['target_id']['pattern']
        for ident,node in catalog.items():
            self.assertEqual(bool(re.fullmatch(pattern,handles[ident])),node['kind'] in {'Symptom','ExamFinding','ContextFactor'})
        self.assertFalse(re.fullmatch(pattern,'k999999'))
        self.assertTrue(re.fullmatch(pattern,'new:Symptom:new_complaint'))
        self.assertFalse(re.fullmatch(pattern,'new:Disease:existing_disease'))
        self.assertEqual(properties['disease_id']['enum'],[handles[self.source()['disease']['id']]])
        self.assertEqual(definitions['Result']['properties']['job_id']['enum'],['job'])
        self.assertEqual(schema['properties']['results']['minItems'],1)

    def test_native_conditions_exclude_empty_and_unpaired_features(self):
        schema=phase_schema('draft',[dict(job_id='job',input=self.source())])
        presence,attribute=schema['$defs']['Condition']['anyOf']
        self.assertEqual(presence['properties']['status']['enum'],['present','absent'])
        self.assertEqual(presence['properties']['attribute'],{'type':'null'})
        self.assertEqual(presence['properties']['expected'],{'type':'null'})
        self.assertTrue(attribute['properties']['attribute']['pattern'])
        self.assertFalse(any(v.get('type')=='null' for v in attribute['properties']['expected']['anyOf']))
        with self.assertRaises(ValueError):Condition.model_validate(dict(status=None,attribute=None,expected=None))

    def test_native_expectation_variants_preserve_numeric_conditions_and_reject_concept_range_flags(self):
        schema=phase_schema('draft',[dict(job_id='job',input=self.source())])
        variants={v['properties']['kind']['enum'][0]:v['properties'] for v in schema['$defs']['ExpectedValue']['anyOf']}
        for kind in ('concept','concept_set'):
            self.assertEqual(variants[kind]['lower_inclusive']['enum'],[True])
            self.assertEqual(variants[kind]['upper_inclusive']['enum'],[True])
            self.assertEqual(variants[kind]['unit'],{'type':'null'})
        self.assertEqual(variants['quantity']['value'],{'type':'number'})
        self.assertEqual(variants['quantity']['unit'],{'type':'string','minLength':1})
        self.assertEqual(variants['quantity']['operator']['enum'],['eq','lt','le','gt','ge'])
        self.assertIn('anyOf',variants['interval']['lower'])
        self.assertEqual(variants['interval']['lower_inclusive']['type'],'boolean')

    def test_acceptance_keeps_strict_roles_detailed_errors_and_registered_definitions(self):
        jobs=Jobs(self.root/'accept');self.addCleanup(jobs.close);jobs.set('vocabulary',self.vocabulary)
        ident=jobs.add('draft',self.source());source=self.source();_,handles=draft_catalog([dict(job_id=ident,input=source)])
        payload=dict(body=dict(input=draft_messages([dict(job_id=ident,input=source)])))
        for name,target,concepts,error in [('disease',source['disease']['id'],[],'invalid_relation_endpoint'),
            ('overwrite',source['disease']['id'],[dict(source['disease'],kind='Symptom')],'draft_cannot_redefine_registered_concept'),
            ('new','new:Symptom:new_complaint',[Concept(id='new:Symptom:new_complaint',kind='Symptom',name='New complaint',korean='새증상').model_dump()],None)]:
            jobs.prepare_request(name,'openai_api',payload,[ident])
            value=dict(job_id=ident,concepts=reference_ids(concepts,handles),relations=[reference_ids(relation(target_id=target),handles)],value_matches=[])
            request=jobs.db.execute('SELECT * FROM requests WHERE request_id=?',(name,)).fetchone()
            invalid=accept_response(jobs,request,dict(content=canonical(dict(results=[value])),finish_reason='stop'))
            if error:
                self.assertIn(error,invalid[ident])
                if name=='disease':self.assertIn('"target_kind":"Disease"',invalid[ident])
            else:self.assertEqual(invalid,{})

    def checkpoint(self):
        assets=inputs(self.root/'assets');entries=discover(assets);identity=build_identity(entries,self.config,assets)
        previous=copy.deepcopy(identity);previous['generator']['build.py']='untyped_schema';previous['prompts']['draft.txt']='old'
        work=self.root/'recover';source_id=digest(previous)[:32];source=Jobs(work/source_id,previous)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        for phase in ('normalize','questions'):
            ident=source.add(phase,dict(complete=True));source.prepare_request(phase,'openai_api',{},[ident])
            source.accept(phase,{ident:dict(job_id=ident,concepts=self.vocabulary,relations=[],value_matches=[])},{},dict(day='2026-10-20',model='gpt-6-luna',input_tokens=1,output_tokens=1))
            source.request_state(phase,'accepted',dict(content='saved'))
        done=source.add('draft',self.source());second=copy.deepcopy(self.source());second['disease']['id']='other_disease'
        retry=source.add('draft',second);source.prepare_request('draft','openai_api',{},[done,retry])
        source.accept('draft',{done:dict(job_id=done,concepts=[],relations=[relation()],value_matches=[])},{retry:'invalid_relation_endpoint'},dict(day='2026-10-20',model='gpt-6-luna',input_tokens=1,output_tokens=1))
        source.request_state('draft','accepted',dict(content='saved',finish_reason='stop'))
        for key,value in dict(state='paused',phase='draft',normalize_frozen=True,questions_frozen=True,draft_frozen=True).items():source.set(key,value)
        source.close();return work,source_id,identity

    def test_paused_partial_draft_copy_preserves_source_completed_bytes_requests_usage_and_attempts(self):
        work,source_id,identity=self.checkpoint();before=(work/source_id/'jobs.sqlite3').read_bytes()
        with patch('sys.stdout',new=io.StringIO()):report=recover_draft(work,source_id,identity,repair_endpoints=True)
        self.assertEqual((work/source_id/'jobs.sqlite3').read_bytes(),before)
        old=Jobs(work/source_id,readonly=True);new=Jobs(work/report['run_id'],readonly=True)
        try:
            for table in ('jobs','requests','usage'):
                self.assertEqual([dict(r) for r in old.db.execute('SELECT * FROM '+table)],[dict(r) for r in new.db.execute('SELECT * FROM '+table)])
            self.assertEqual(report['completed_by_phase']['draft'],1)
            self.assertEqual(report['model_calls_started'],0)
        finally:old.close();new.close()

    def test_endpoint_copy_rejects_unknown_outcomes_and_config_drift(self):
        work,source_id,identity=self.checkpoint();changed=copy.deepcopy(identity);changed['config']['batch_size']=10
        with self.assertRaisesRegex(ValueError,'identity_mismatch:config'):recover_draft(work,source_id,changed,repair_endpoints=True)
        source=Jobs(work/source_id);source.request_state('normalize','outcome_unknown');source.close()
        with self.assertRaisesRegex(ValueError,'requires_settled_requests'):recover_draft(work,source_id,identity,repair_endpoints=True)

    def test_prompt_only_correction_requires_prior_endpoint_repair_lineage(self):
        work,source_id,identity=self.checkpoint();source=Jobs(work/source_id)
        previous=source.get('identity');identity['generator']['build.py']=previous['generator']['build.py']
        source.close()
        with self.assertRaisesRegex(ValueError,'not_a_draft_packet_change'):
            recover_draft(work,source_id,identity,repair_endpoints=True)
        source=Jobs(work/source_id);source.set('recovery',dict(contract='draft-endpoint-recovery-1'));source.close()
        with patch('sys.stdout',new=io.StringIO()):report=recover_draft(work,source_id,identity,repair_endpoints=True)
        self.assertEqual(report['completed_by_phase']['draft'],1)
        self.assertEqual(report['counters_reset'],0)
