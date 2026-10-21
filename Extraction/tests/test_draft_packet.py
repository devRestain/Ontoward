import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity,configuration,main
from ontoward_extraction.build import draft_catalog,draft_messages,reference_ids,run_phase,accept_response
from ontoward_extraction.inputs import discover,index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical,digest
from ontoward_extraction.recovery import recover_draft
from support import inputs,nodes,relation,ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


class DraftPacketTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.config=configuration(ROOT/'config.sol.json')

    def data(self,number=0):
        vocabulary=nodes();disease=copy.deepcopy(vocabulary[0]);disease['id']+='-'+str(number)
        return dict(disease=disease,available_targets=[n for n in vocabulary if n['kind'] in {'Symptom','ExamFinding','ContextFactor'}],
            attributes_and_values=[n for n in vocabulary if n['kind'] in {'FindingAttribute','AttributeValue'}],
            source_material=[dict(name='source description',numeric_duration=3,unit='days')])

    def test_shared_catalog_keeps_every_definition_link_unit_and_forty_jobs(self):
        data=[dict(job_id=str(i),input=self.data(i),validation_error=None) for i in range(40)]
        before=copy.deepcopy(data);parts=[json.loads(m['content']) for m in draft_messages(data,maximum=3000)]
        self.assertEqual(data,before)
        self.assertEqual(sum(len(p.get('jobs',[])) for p in parts),40)
        catalog,handles=draft_catalog(data);wire=[dict(zip(p['vocabulary_columns'],n)) for p in parts for n in p.get('vocabulary',[])]
        self.assertEqual(len(wire),len(catalog));self.assertEqual(len({n['id'] for n in wire}),len(wire))
        inverse={v:k for k,v in handles.items()}
        for row in wire:
            original=catalog[inverse[row['id']]];restored=reference_ids(row,inverse)
            for key,value in original.items():
                if key not in {'aliases','question','exam_text','attribute_role'}:self.assertEqual(restored[key],value)
            self.assertEqual(row['units'],(original.get('question') or {}).get('units',[]))
        for part in parts:self.assertLessEqual(len(canonical(part)),3000)

    def test_references_do_not_change_names_or_numeric_semantics(self):
        original=dict(id='urn:a',name='k0',question=dict(units=['k0']),
            features=[dict(attribute='urn:a',expected=dict(kind='number',value=3,unit='days',op='gte'))])
        wire=reference_ids(original,{'urn:a':'k0'})
        self.assertEqual(wire['name'],'k0');self.assertEqual(wire['question'],original['question'])
        self.assertEqual(reference_ids(wire,{'k0':'urn:a'},strict=True),original)
        with self.assertRaisesRegex(ValueError,'unknown_draft_reference'):reference_ids(dict(target_id='k99'),{'k0':'urn:a'},strict=True)

    def test_fixed_forty_draft_batches_restore_ids_and_do_not_load_all_pending_inputs(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close);vocabulary=nodes()
        for i in range(41):
            source=self.data(i);vocabulary.append(source['disease']);jobs.add('draft',source)
        jobs.set('vocabulary',vocabulary)
        provider=ScriptedProvider();send=provider.send;sizes=[]
        def respond(payload):
            parts=[json.loads(m['content']) for m in payload['messages'] if m['role']=='user']
            sizes.append(sum(len(p.get('jobs',[])) for p in parts));return send(payload)
        provider.send=respond
        with patch.object(jobs,'pending',side_effect=AssertionError('unbounded pending read')),patch('sys.stdout',new=io.StringIO()):
            run_phase(jobs,'draft',self.config,provider)
        self.assertEqual(sizes,[40,1]);self.assertEqual(len(jobs.results('draft')),41)
        for result in jobs.results('draft'):self.assertTrue(result['relations'][0]['disease_id'].startswith('disease-'))

    def test_mixed_invalid_references_and_wrong_disease_do_not_discard_valid_sibling(self):
        jobs=Jobs(self.root/'work');self.addCleanup(jobs.close)
        ids=[jobs.add('draft',self.data(i)) for i in range(3)]
        data=[dict(job_id=i,input=json.loads(jobs.db.execute('SELECT normalized_input FROM jobs WHERE job_id=?',(i,)).fetchone()[0])) for i in ids]
        catalog,handles=draft_catalog(data);jobs.set('vocabulary',list(catalog.values()))
        payload=dict(messages=draft_messages(data));jobs.prepare_request('r','nova_dev',payload,ids)
        rows=[]
        for i,job in enumerate(data):
            r=reference_ids(relation(disease_id=job['input']['disease']['id'],target_id=job['input']['available_targets'][0]['id']),handles)
            if i==1:r['target_id']='k99999'
            if i==2:r['disease_id']=handles[data[0]['input']['disease']['id']]
            rows.append(dict(job_id=job['job_id'],concepts=[],relations=[r],value_matches=[]))
        request=jobs.db.execute('SELECT * FROM requests').fetchone()
        invalid=accept_response(jobs,request,dict(content=canonical(dict(results=rows)),finish_reason='stop'))
        self.assertEqual(set(invalid),set(ids[1:]));self.assertEqual(len(jobs.results('draft')),1)

    def test_api_and_cli_envelopes_restore_registered_identifiers(self):
        for provider,envelope in [('openai_api','body'),('codex_subscription','messages')]:
            jobs=Jobs(self.root/provider)
            try:
                source=self.data();ident=jobs.add('draft',source);data=[dict(job_id=ident,input=source)]
                catalog,handles=draft_catalog(data);jobs.set('vocabulary',list(catalog.values()))
                payload=dict(body=dict(input=draft_messages(data))) if envelope=='body' else dict(messages=draft_messages(data))
                jobs.prepare_request('r',provider,payload,[ident]);request=jobs.db.execute('SELECT * FROM requests').fetchone()
                value=reference_ids(relation(disease_id=source['disease']['id']),handles)
                invalid=accept_response(jobs,request,dict(finish_reason='stop',content=canonical(dict(results=[
                    dict(job_id=ident,concepts=[],relations=[value],value_matches=[])]))))
                self.assertEqual(invalid,{})
                self.assertEqual(jobs.results('draft')[0]['relations'][0]['disease_id'],source['disease']['id'])
            finally:jobs.close()

    def checkpoint(self):
        assets=inputs(self.root/'assets');entries=discover(assets);identity=build_identity(entries,self.config,assets)
        previous=copy.deepcopy(identity);previous['generator']['build.py']='repeated-catalog';previous['prompts']['draft.txt']='old'
        work=self.root/'recover';source_id=digest(previous)[:32];source=Jobs(work/source_id,previous)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        for phase in ('normalize','questions'):
            ident=source.add(phase,dict(complete=True));source.prepare_request(phase,'nova_dev',{},[ident])
            source.request_state(phase,'received',dict(content='saved'))
            source.accept(phase,{ident:dict(job_id=ident,concepts=nodes(),relations=[],value_matches=[])},{},
                dict(day='2026-10-20',model='openai/gpt-6.1-sol',input_tokens=1,output_tokens=1))
        pending=source.add('draft',self.data())
        source.prepare_request('oversized','nova_dev',dict(padding='x'*100_000_001),[pending])
        source.request_state('oversized','failed',error='INVALID_API_RESPONSE')
        for key,value in dict(state='failed',phase='draft',error='INVALID_API_RESPONSE',normalize_frozen=True,questions_frozen=True,draft_frozen=True).items():source.set(key,value)
        source.close();return work,source_id,identity,assets

    def test_guarded_keyless_copy_preserves_source_results_requests_and_counters(self):
        work,source_id,identity,_=self.checkpoint();path=work/source_id/'jobs.sqlite3';before=path.read_bytes()
        with patch('sys.stdout',new=io.StringIO()):report=recover_draft(work,source_id,identity)
        self.assertEqual(path.read_bytes(),before)
        old=Jobs(work/source_id,readonly=True);new=Jobs(work/report['run_id'],readonly=True)
        try:
            for table in ('jobs','requests','usage'):
                for left,right in zip(old.db.execute('SELECT * FROM '+table),new.db.execute('SELECT * FROM '+table)):
                    self.assertEqual(dict(left,status='pending') if table=='jobs' and left['status']=='running' else dict(left),dict(right))
            self.assertEqual(report['model_calls_started'],0);self.assertEqual(report['counters_reset'],0)
        finally:old.close();new.close()

    def test_recovery_rejects_unknown_small_request_and_contract_drift(self):
        work,source_id,identity,_=self.checkpoint()
        changed=copy.deepcopy(identity);changed['config']['batch_size']=10
        with self.assertRaisesRegex(ValueError,'recovery_identity_mismatch:config'):recover_draft(work,source_id,changed)
        source=Jobs(work/source_id);source.request_state('oversized','outcome_unknown',error='INVALID_API_RESPONSE');source.close()
        with self.assertRaisesRegex(ValueError,'recovery_requires_oversized_settled_request'):recover_draft(work,source_id,identity)
        source=Jobs(work/source_id);source.request_state('oversized','failed',error='INVALID_API_RESPONSE')
        with source.db:source.db.execute("UPDATE requests SET payload='{}'")
        source.close()
        with self.assertRaisesRegex(ValueError,'recovery_requires_oversized_settled_request'):recover_draft(work,source_id,identity)
