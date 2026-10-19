import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unicodedata
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import build_identity, configuration
from ontoward_extraction.build import accept_response, collected, phase_schema, run_phase
from ontoward_extraction.inputs import discover, index
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical, digest, response_schema
from ontoward_extraction.recovery import recover_normalization
from support import inputs, nodes, ScriptedProvider

ROOT=Path(__file__).resolve().parents[1]


class KoreanPhaseTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.config=configuration(ROOT/'config.json')
        self.jobs=Jobs(self.root/'work');self.addCleanup(self.jobs.close)

    def accept(self,phase,concepts):
        ident=self.jobs.add(phase,{'fixture':len(list(self.jobs.db.execute('SELECT * FROM requests')))})
        request_id='request-'+ident
        self.jobs.prepare_request(request_id,'nova_dev',{},[ident])
        response=dict(content=canonical(dict(results=[dict(job_id=ident,concepts=concepts,relations=[],value_matches=[])])),finish_reason='stop')
        self.jobs.request_state(request_id,'received',response)
        request=self.jobs.db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
        return ident,accept_response(self.jobs,request,response)

    def test_normalization_defers_action_text_before_question_semantic_validation(self):
        raw=nodes()
        raw[1]['question']=dict(text='How long has the synthetic complaint been present?',answer_type='duration',affirmative=True,units=['day'])
        raw[2]['attribute_role']['clarification']='An English definition that exceeds thirty characters'
        raw[-1]['exam_text']='Assess the synthetic finding with a long English examination instruction.'
        original=copy.deepcopy(raw)
        ident,invalid=self.accept('normalize',raw)
        self.assertEqual(invalid,{})
        self.assertEqual(raw,original)
        accepted=self.jobs.results('normalize')[0]['concepts']
        for before,after in zip(raw,accepted):
            self.assertIsNone(after['question'])
            self.assertIsNone(after['exam_text'])
            self.assertEqual(after['id'],before['id'])
            self.assertEqual(after['name'],before['name'])
            self.assertEqual(after['korean'],before['korean'])
            self.assertEqual(after['attributes'],before['attributes'])
            if after['attribute_role']:
                self.assertIsNone(after['attribute_role']['clarification'])
                self.assertEqual(after['attribute_role']['category'],before['attribute_role']['category'])
        saved=json.loads(self.jobs.db.execute('SELECT response FROM requests').fetchone()[0])
        self.assertEqual(json.loads(saved['content'])['results'][0]['concepts'],raw)

    def test_normalization_still_rejects_invalid_clinical_labels(self):
        raw=nodes();raw[0]['name']='가상질환'
        ident,invalid=self.accept('normalize',raw)
        self.assertIn('normalized English canonical name',invalid[ident])
        self.assertEqual(self.jobs.results('normalize'),[])

    def test_questions_enforce_rendered_korean_length_nfc_and_language(self):
        for text,expected in [('가'*30,None),('가'*31,'rendered_length'),('English only','contains_korean'),
            (unicodedata.normalize('NFD','가상증상'),'"nfc":false'),('{symptom}'+'가'*27,'rendered_length')]:
            raw=nodes()[1];raw['question']['text']=text
            ident,invalid=self.accept('questions',[raw])
            if expected is None: self.assertEqual(invalid,{})
            else:
                self.assertIn('invalid_executable_korean_text',invalid[ident])
                self.assertIn(expected,invalid[ident])
                self.assertIn('question.text',invalid[ident])

    def test_question_error_explains_affirmative_and_units_invariants(self):
        for question,expected in [
            (dict(text='얼마나 오래됐나요?',answer_type='duration',affirmative=True,units=['day']),'Only a presence question'),
            (dict(text='어떤 느낌인가요?',answer_type='category',units=['day']),'Numeric units require a numeric question')]:
            raw=nodes()[2];raw['question']=question
            ident,invalid=self.accept('questions',[raw])
            self.assertIn(expected,invalid[ident])

    def test_legacy_normalization_actions_are_deferred_without_rewriting_done_result(self):
        raw=dict(job_id='legacy',concepts=nodes(),relations=[],value_matches=[])
        with self.jobs.db:
            self.jobs.db.execute('INSERT INTO jobs(job_id,phase,normalized_input,status,result) VALUES(?,?,?,?,?)',
                ('legacy','normalize','{}','done',canonical(raw)))
        before=self.jobs.db.execute("SELECT result FROM jobs WHERE job_id='legacy'").fetchone()[0]
        normalized,_,_=collected(self.jobs,['normalize'])
        self.assertTrue(all(node['question'] is None and node['exam_text'] is None for node in normalized))
        self.assertEqual(self.jobs.db.execute("SELECT result FROM jobs WHERE job_id='legacy'").fetchone()[0],before)


class TextCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.work=self.root/'work'
        self.assets=inputs(self.root/'assets');self.entries=discover(self.assets)
        self.config=configuration(ROOT/'config.json')
        self.identity=build_identity(self.entries,self.config,self.assets)
        previous=copy.deepcopy(self.identity);previous['generator']['build.py']='before-phase-ownership'
        self.source_id=digest(previous)[:32];self.source=self.work/self.source_id
        jobs=Jobs(self.source,previous)
        with patch('sys.stdout',new=io.StringIO()): index(jobs,self.entries,1)
        self.ids=[jobs.add('normalize',{'value':number}) for number in range(3)]
        results=[]
        for ident in self.ids:
            raw=nodes()
            raw[1]['question']=dict(text='How long has this synthetic complaint been present?',answer_type='duration',affirmative=True,units=['day'])
            results.append(dict(job_id=ident,concepts=raw,relations=[],value_matches=[]))
        payload=dict(messages=[dict(role='system',content='JSON Schema:\n'+canonical(response_schema()))])
        jobs.prepare_request('saved','nova_dev',payload,self.ids)
        response=dict(content=canonical(dict(results=results)),finish_reason='stop')
        jobs.request_state('saved','received',response)
        self.kept=canonical(dict(job_id=self.ids[0],concepts=nodes(),relations=[],value_matches=[]))
        jobs.accept('saved',{self.ids[0]:json.loads(self.kept)},
            {self.ids[1]:'invalid_rendered_korean_length_or_normalization',
             self.ids[2]:'output_validation_failed:[{"path":"concepts.1.question","type":"value_error"}]'},
            dict(day='2026-10-19',model='openai/gpt-6-luna',input_tokens=3,output_tokens=4))
        for key,value in dict(state='paused',phase='normalize',normalize_frozen=True,pause_requested=True).items():jobs.set(key,value)
        jobs.close()

    def recover(self):
        with patch('sys.stdout',new=io.StringIO()):
            return recover_normalization(self.work,self.source_id,self.identity,repair='text')

    def test_text_recovery_keeps_done_bytes_and_recovers_saved_invalid_siblings_offline(self):
        before=hashlib.sha256((self.source/'jobs.sqlite3').read_bytes()).hexdigest()
        report=self.recover()
        self.assertEqual(report['model_calls_started'],0)
        self.assertEqual(report['jobs_kept_done'],1)
        self.assertEqual(report['recovered_from_saved_responses'],2)
        self.assertEqual(report['jobs_pending'],0)
        jobs=Jobs(self.work/report['run_id']);self.addCleanup(jobs.close)
        self.assertEqual(jobs.status()['jobs'],{'done':3})
        self.assertEqual(jobs.status()['usage'][0]['calls'],1)
        self.assertEqual(jobs.db.execute('SELECT result FROM jobs WHERE job_id=?',(self.ids[0],)).fetchone()[0],self.kept)
        self.assertEqual(jobs.db.execute('SELECT attempt_count FROM jobs WHERE job_id=?',(self.ids[0],)).fetchone()[0],1)
        self.assertEqual(jobs.status()['requests'],{'accepted':1})
        receipt=json.loads((jobs.directory/'recovery.json').read_text())
        self.assertEqual(receipt,jobs.get('recovery'))
        provider=ScriptedProvider();provider.send=lambda payload:self.fail('Done jobs must not call a model')
        with patch('sys.stdout',new=io.StringIO()): run_phase(jobs,'normalize',self.config,provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(hashlib.sha256((self.source/'jobs.sqlite3').read_bytes()).hexdigest(),before)

    def test_text_recovery_refuses_other_clinical_errors_and_unknown_requests(self):
        for query,error in [
            ("UPDATE jobs SET error='invalid_relation_endpoint' WHERE status!='done'",'not_an_action_text_failure'),
            ("UPDATE requests SET state='outcome_unknown'",'settled_requests')]:
            original=(self.source/'jobs.sqlite3').read_bytes()
            jobs=Jobs(self.source)
            with jobs.db:jobs.db.execute(query)
            jobs.close()
            try:
                with self.assertRaisesRegex(ValueError,error):self.recover()
            finally:(self.source/'jobs.sqlite3').write_bytes(original)


if __name__=='__main__':unittest.main()
