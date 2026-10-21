import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity, configuration
from ontoward_extraction.build import PATCH_COLUMNS, patch_catalog, patch_messages, reference_ids, run_phase, accept_response
from ontoward_extraction.inputs import discover, index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical, digest
from ontoward_extraction.recovery import recover_patch
from support import nodes, relation, inputs, ScriptedProvider


def decode(messages):
    parts=[json.loads(m['content']) for m in messages]
    vocabulary=[];relations=[]
    for p in parts:
        for row in p.get('vocabulary',[]):
            node=dict(zip(p['vocabulary_columns'],row))
            for field in ('question','attribute_role'):
                if node[field] is not None:node[field]=dict(zip(p[field+'_columns'],node[field]))
            vocabulary.append(node)
        for row in p.get('completed_relations',[]):
            r=dict(zip(p['relation_columns'],row));r['target_scope']=dict(zip(p['scope_columns'],r['target_scope']))
            r['applicability']=[dict(zip(p['applicability_columns'],item)) for item in r['applicability']]
            features=[]
            for item in r['features']:
                f=dict(zip(p['feature_columns'],item))
                if f['expected'] is not None:f['expected']=dict(zip(p['expected_columns'],f['expected']))
                features.append(f)
            r['features']=features;relations.append(r)
    return vocabulary,relations,[j for p in parts for j in p.get('jobs',[])]


class PatchPacketTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.config=configuration(Path(__file__).resolve().parents[1]/'config.api-luna.json')

    def source(self,i=0):
        return dict(gap=dict(concept=nodes()[1],missing=['question'],number=i),available_concepts=nodes(),
            completed_relations=[relation('neutral'),relation('against',status='absent'),relation(features=[dict(attribute='quality',
                expected=dict(kind='interval',lower=7,upper=12,unit='month',lower_inclusive=False,upper_inclusive=True))],
                target_scope=dict(subject='family',subject_member='mother',time_context='past'),
                applicability=[dict(concept_id='context',status='present',subject='family',subject_member='mother',time_context='past')])],
            instruction_boundary='Data, not instructions')

    def test_column_parts_preserve_forty_jobs_full_patterns_scopes_units_actions_and_neutral(self):
        data=[dict(job_id=str(i),input=self.source(i),validation_error=None) for i in range(40)]
        before=copy.deepcopy(data);messages=patch_messages(data,maximum=2400)
        self.assertEqual(data,before);self.assertTrue(all(len(m['content'])<=2400 for m in messages))
        vocabulary,relations,work=decode(messages)
        catalog,handles=patch_catalog(data);inverse={v:k for k,v in handles.items()}
        restored=reference_ids(vocabulary,inverse)
        self.assertEqual(restored,[{k:v for k,v in catalog[i].items() if k!='aliases'} for i in sorted(catalog)])
        self.assertEqual(reference_ids(relations,inverse),data[0]['input']['completed_relations'])
        self.assertEqual(reference_ids(work,inverse),[{**j,'input':{k:v for k,v in j['input'].items() if k not in {'available_concepts','completed_relations'}}} for j in data])

    def test_scope_drift_and_unsplittable_item_are_explicit(self):
        data=[dict(job_id='a',input=self.source()),dict(job_id='b',input=self.source(1))]
        data[1]['input']['completed_relations'][0]['effect']='support'
        with self.assertRaisesRegex(ValueError,'scope_mismatch'):patch_messages(data)
        with self.assertRaisesRegex(ValueError,'patch_packet_item_too_large'):patch_messages(data[:1],maximum=100)

    def test_fixed_forty_and_tail_restore_registered_ids_before_acceptance(self):
        jobs=Jobs(self.root/'run');self.addCleanup(jobs.close);jobs.set('vocabulary',nodes())
        for i in range(41):jobs.add('patch',self.source(i))
        provider=ScriptedProvider();sizes=[]
        def respond(payload):
            _,_,work=decode([m for m in payload['messages'] if m['role']=='user']);sizes.append(len(work))
            results=[dict(job_id=j['job_id'],concepts=[j['input']['gap']['concept']],relations=[],value_matches=[]) for j in work]
            return dict(content=canonical({'results':results}),finish_reason='stop')
        provider.send=respond
        with patch('sys.stdout',new=io.StringIO()):run_phase(jobs,'patch',self.config,provider)
        self.assertEqual(sizes,[40,1])
        self.assertTrue(all(r['concepts'][0]['id']=='symptom' for r in jobs.results('patch')))

    def checkpoint(self):
        assets=inputs(self.root/'assets');entries=discover(assets);identity=build_identity(entries,self.config,assets)
        old=copy.deepcopy(identity);old['generator']['build.py']='old-patch-packet';old['prompts'].pop('patch.txt',None)
        work=self.root/'work';source_id=digest(old)[:32];j=Jobs(work/source_id,old)
        with patch('sys.stdout',new=io.StringIO()):index(j,entries,1)
        for phase in ('normalize','questions','draft','final','conflict'):
            ident=j.add(phase,dict(saved=phase))
            with j.db:j.db.execute("UPDATE jobs SET status='done',result=? WHERE job_id=?",(canonical(dict(saved=phase)),ident))
            j.set(phase+'_frozen',True)
        ident=j.add('patch',self.source());j.prepare_request('rejected','openai_api',
            dict(body=dict(input=[dict(role='system',content='prompt'),dict(role='user',content='x'*60000)])),[ident])
        j.request_state('rejected','failed',error='string_above_max_length')
        j.set('patch_frozen',True);j.set('phase','patch');j.set('state','failed');j.set('error','string_above_max_length');j.close()
        return work,source_id,identity,ident

    def test_keyless_recovery_preserves_source_results_requests_counters_and_identity_pins(self):
        work,source_id,identity,ident=self.checkpoint();before=(work/source_id/'jobs.sqlite3').read_bytes()
        with patch('sys.stdout',new=io.StringIO()):report=recover_patch(work,source_id,identity)
        self.assertEqual((work/source_id/'jobs.sqlite3').read_bytes(),before)
        old=Jobs(work/source_id,readonly=True);new=Jobs(work/report['run_id'],readonly=True)
        self.addCleanup(old.close);self.addCleanup(new.close)
        for table in ('requests','usage','source_rows','rf2'):
            self.assertEqual([tuple(r) for r in old.db.execute('SELECT * FROM '+table)],[tuple(r) for r in new.db.execute('SELECT * FROM '+table)])
        previous=dict(old.db.execute('SELECT * FROM jobs WHERE job_id=?',(ident,)).fetchone())
        current=dict(new.db.execute('SELECT * FROM jobs WHERE job_id=?',(ident,)).fetchone())
        self.assertEqual(current,{**previous,'status':'pending'});self.assertEqual(current['attempt_count'],1)
        self.assertEqual(report['completed_by_phase']['final'],1);self.assertEqual(report['model_calls_started'],0)

    def test_recovery_rejects_unknown_outcomes_config_drift_and_unrelated_runtime_changes(self):
        work,source_id,identity,ident=self.checkpoint()
        changed=copy.deepcopy(identity);changed['config']['batch_size']=1
        with self.assertRaisesRegex(ValueError,'identity_mismatch:config'):recover_patch(work,source_id,changed)
        changed=copy.deepcopy(identity);changed['runtime_contract']['graph.py']='changed'
        with self.assertRaisesRegex(ValueError,'identity_mismatch:runtime_contract'):recover_patch(work,source_id,changed)
        source=Jobs(work/source_id);source.request_state('rejected','outcome_unknown');source.close()
        with self.assertRaisesRegex(ValueError,'settled_requests'):recover_patch(work,source_id,identity)

    def test_restored_patch_cannot_redraw_completed_neutral(self):
        jobs=Jobs(self.root/'run');self.addCleanup(jobs.close);jobs.set('vocabulary',nodes());ident=jobs.add('patch',self.source())
        data=[dict(job_id=ident,input=self.source())];_,handles=patch_catalog(data)
        request=dict(request_id='test',job_ids=canonical([ident]),payload=canonical(dict(messages=patch_messages(data))))
        result=reference_ids(dict(job_id=ident,concepts=[],relations=[relation('support')],value_matches=[]),handles)
        self.assertEqual(accept_response(jobs,request,dict(content=canonical({'results':[result]}),finish_reason='stop')),
                         {ident:'completed_relation_cannot_be_redrawn'})
