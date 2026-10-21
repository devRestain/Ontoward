import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity,configuration
from ontoward_extraction.build import draft_messages,run_phase
from ontoward_extraction.inputs import discover,index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical,digest
from ontoward_extraction.recovery import recover_draft
from support import inputs,nodes,relation,ScriptedProvider


class JobPacketTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.config=configuration(Path(__file__).resolve().parents[1]/'config.api-luna.json')
        self.vocabulary=nodes()

    def source(self,number=0,large=False):
        vocabulary=copy.deepcopy(self.vocabulary);disease=vocabulary[0];disease['id']+='-'+str(number)
        material=[dict(text='한국어 "인용"\n'+('source '*70),value=37.5,unit='C',present=False),dict(nested=[None,1,'표제'])]*120 if large else [dict(source=number)]
        return dict(disease=disease,available_targets=[n for n in vocabulary if n['kind'] in {'Symptom','ExamFinding','ContextFactor'}],
            attributes_and_values=[n for n in vocabulary if n['kind'] in {'FindingAttribute','AttributeValue'}],source_material=material)

    def test_oversized_jobs_keep_all_records_order_duplicates_numeric_values_and_forty_jobs(self):
        data=[dict(job_id=str(i),input=self.source(i,large=i<2),validation_error=None) for i in range(40)]
        before=copy.deepcopy(data);messages=draft_messages(data,maximum=3000)
        self.assertEqual(data,before)
        self.assertTrue(all(len(m['content'])<=3000 for m in messages))
        packets=[json.loads(m['content']) for m in messages];work=[j for p in packets for j in p.get('jobs',[])]
        self.assertEqual([j['job_id'] for j in work],[j['job_id'] for j in data])
        for job,original in zip(work,data):
            source=job['input']
            if 'source_material_ref' in source:
                self.assertEqual(source['source_material_ref'],job['job_id'])
                restored=[r for p in packets if p.get('source_material_for')==job['job_id'] for r in p['source_material']]
                self.assertEqual(source['source_material_count'],len(restored))
            else:restored=source['source_material']
            self.assertEqual(restored,original['input']['source_material'])

    def test_fixed_forty_requests_and_tail_use_split_sources_in_one_request(self):
        jobs=Jobs(self.root/'run');self.addCleanup(jobs.close);vocabulary=copy.deepcopy(self.vocabulary)
        for i in range(41):
            source=self.source(i,large=i in {0,40});vocabulary.append(source['disease']);jobs.add('draft',source)
        jobs.set('vocabulary',vocabulary);provider=ScriptedProvider();send=provider.send;sizes=[];split=0
        def respond(payload):
            nonlocal split
            packets=[json.loads(m['content']) for m in payload['messages'] if m['role']=='user']
            sizes.append(sum(len(p.get('jobs',[])) for p in packets));split+=sum('source_material_for' in p for p in packets)
            self.assertTrue(all(len(m['content'])<=50000 for m in payload['messages'] if m['role']=='user'))
            return send(payload)
        provider.send=respond
        with patch('sys.stdout',new=io.StringIO()):run_phase(jobs,'draft',self.config,provider)
        self.assertEqual(sizes,[40,1]);self.assertGreater(split,0);self.assertEqual(len(jobs.results('draft')),41)

    def test_unrepresentable_individual_record_fails_without_truncation(self):
        source=self.source(large=True);source['source_material']=[dict(text='x'*60000)];before=copy.deepcopy(source)
        with self.assertRaisesRegex(ValueError,'draft_packet_item_too_large:source_material'):
            draft_messages([dict(job_id='job',input=source)])
        self.assertEqual(source,before)

    def checkpoint(self):
        assets=inputs(self.root/'assets');entries=discover(assets);identity=build_identity(entries,self.config,assets)
        old=copy.deepcopy(identity);old['generator']['build.py']='atomic_job_packet';old['prompts']['draft.txt']='old'
        work=self.root/'work';source_id=digest(old)[:32];source=Jobs(work/source_id,old)
        with patch('sys.stdout',new=io.StringIO()):index(source,entries,1)
        for phase in ('normalize','questions','draft'):
            value=self.source() if phase=='draft' else dict(complete=True)
            ident=source.add(phase,value);source.prepare_request(phase,'openai_api',{},[ident])
            source.accept(phase,{ident:dict(job_id=ident,concepts=[],relations=[relation()] if phase=='draft' else [],value_matches=[])},{},
                dict(day='2026-10-20',model='gpt-6-luna',input_tokens=1,output_tokens=1))
            source.request_state(phase,'accepted',dict(content='saved',finish_reason='stop'))
        pending=source.add('draft',self.source(1,large=True))
        with source.db:source.db.execute("UPDATE jobs SET status='retry',attempt_count=1,error='preserved_old_validation_error' WHERE job_id=?",(pending,))
        for key,value in dict(state='failed',phase='draft',error='draft_packet_item_too_large:jobs',normalize_frozen=True,questions_frozen=True,draft_frozen=True).items():source.set(key,value)
        source.close();return work,source_id,identity

    def test_keyless_packet_recovery_preserves_partial_work_source_counters_requests_and_usage(self):
        work,source_id,identity=self.checkpoint();before=(work/source_id/'jobs.sqlite3').read_bytes()
        with patch('sys.stdout',new=io.StringIO()),patch('ontoward_extraction.build.Provider',side_effect=AssertionError('no model client')):
            report=recover_draft(work,source_id,identity,repair_packets=True)
        self.assertEqual((work/source_id/'jobs.sqlite3').read_bytes(),before)
        old=Jobs(work/source_id,readonly=True);new=Jobs(work/report['run_id'],readonly=True)
        try:
            for table in ('jobs','requests','usage'):
                self.assertEqual([dict(r) for r in old.db.execute('SELECT * FROM '+table)],[dict(r) for r in new.db.execute('SELECT * FROM '+table)])
            self.assertEqual(report['completed_by_phase']['draft'],1)
            self.assertEqual(report['model_calls_started'],0)
            self.assertEqual(report['counters_reset'],0)
            self.assertEqual(len(report['oversized_jobs']),1)
            self.assertNotIn('failed_request_id',report)
        finally:old.close();new.close()

    def test_packet_recovery_rejects_unknown_config_drift_and_nonreproducing_failure(self):
        work,source_id,identity=self.checkpoint();changed=copy.deepcopy(identity);changed['config']['batch_size']=1
        with self.assertRaisesRegex(ValueError,'identity_mismatch:config'):recover_draft(work,source_id,changed,repair_packets=True)
        source=Jobs(work/source_id);source.request_state('normalize','outcome_unknown');source.close()
        with self.assertRaisesRegex(ValueError,'requires_settled_requests'):recover_draft(work,source_id,identity,repair_packets=True)
        source=Jobs(work/source_id);source.request_state('normalize','accepted',dict(content='saved'))
        with source.db:source.db.execute("UPDATE jobs SET normalized_input=? WHERE status!='done'",(canonical(self.source(1)),))
        source.close()
        with self.assertRaisesRegex(ValueError,'requires_reproduced_oversized_job'):recover_draft(work,source_id,identity,repair_packets=True)
