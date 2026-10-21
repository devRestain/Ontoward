"""Offline protocol doubles; no model or clinical quality claims."""
import copy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import itertools
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

SOURCE = (Path(os.environ['ONTOWARD_TEST_SUBMISSION']) if 'ONTOWARD_TEST_SUBMISSION' in os.environ else
          Path(__file__).resolve().parents[3] / 'submission').resolve()
sys.path.insert(0, str(SOURCE))
from rdflib import Graph, Literal, RDF, RDFS
from knowledge.graph import ClinicalKnowledge, OW
from knowledge.conditions import ExpectedValue, QuestionTemplate, AttributeRole
from workflow.runtime import PreparedResources, assemble_consultation, prepare
from workflow.state.models import CaseFact, GraphBinding, ObservedNumber, Question, SessionContext, WorkflowState
from workflow.state.evidence import EvidenceIndex, EvidenceRecord
from workflow.text_config import TextConfig
from nova_sdk import NovaError, RECORD_FIELDS
from education_fixtures import education_response
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'Test'))
from brain_double import clinical_response, attach_sink
from protocol import decode_context

FIXED = datetime(2026, 10, 18, tzinfo=timezone.utc)
CONFIG = TextConfig.load().model_copy(update={'education_enabled':False})
TTL = '@prefix ow: <urn:ontoward:> .\n@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\now:Alpha a ow:Disease; rdfs:label "가상질환A"@ko; ow:hasAssociation ow:alphaBase, ow:alphaLocation .\now:Beta a ow:Disease; rdfs:label "가상질환B"@ko; ow:hasAssociation ow:betaBase, ow:betaLocation, ow:betaExamAssociation; ow:evaluatedBy ow:TestX .\now:Complaint a ow:Symptom; rdfs:label "가상증상"@ko; ow:hasAttribute ow:Location, ow:Quality .\now:Other a ow:Symptom; rdfs:label "별도증상"@ko .\now:Location a ow:FindingAttribute; rdfs:label "위치"@ko; ow:canHaveValue ow:Here, ow:Elsewhere .\now:Quality a ow:FindingAttribute; rdfs:label "양상"@ko; ow:canHaveValue ow:Dull .\now:Here a ow:AttributeValue; rdfs:label "가상부위"@ko .\now:Elsewhere a ow:AttributeValue; rdfs:label "다른부위"@ko .\now:Dull a ow:AttributeValue; rdfs:label "둔함"@ko .\now:baseX a ow:ClinicalPattern; ow:targets ow:Complaint; ow:hasFeature ow:basePresent .\now:basePresent a ow:ClinicalFeature; ow:expectedStatus "present" .\now:locationX a ow:ClinicalPattern; ow:targets ow:Complaint; ow:hasFeature ow:locationPresent, ow:locationFeature; ow:refinesPattern ow:baseX .\now:locationPresent a ow:ClinicalFeature; ow:expectedStatus "present" .\now:locationFeature a ow:ClinicalFeature; ow:onAttribute ow:Location; ow:expected ow:hereExpected .\now:hereExpected a ow:ExpectedValue; ow:valueJSON \'{"kind":"concept","concept":"urn:ontoward:Here"}\'^^rdf:JSON .\now:alphaBase a ow:DiseasePatternAssociation; ow:pattern ow:baseX; ow:targetScope \'{"subject":"patient","subject_member":null,"time_context":"current"}\'^^rdf:JSON; ow:diagnosticEffect "support" .\now:betaBase a ow:DiseasePatternAssociation; ow:pattern ow:baseX; ow:targetScope \'{"subject":"patient","subject_member":null,"time_context":"current"}\'^^rdf:JSON; ow:diagnosticEffect "support" .\now:alphaLocation a ow:DiseasePatternAssociation; ow:pattern ow:locationX; ow:targetScope \'{"subject":"patient","subject_member":null,"time_context":"current"}\'^^rdf:JSON; ow:diagnosticEffect "support" .\now:betaLocation a ow:DiseasePatternAssociation; ow:pattern ow:locationX; ow:targetScope \'{"subject":"patient","subject_member":null,"time_context":"current"}\'^^rdf:JSON; ow:diagnosticEffect "support" .\now:betaExam a ow:ClinicalPattern; ow:targets ow:ExamX; ow:hasFeature ow:examPresent .\now:examPresent a ow:ClinicalFeature; ow:expectedStatus "present" .\now:betaExamAssociation a ow:DiseasePatternAssociation; ow:pattern ow:betaExam; ow:targetScope \'{"subject":"patient","subject_member":null,"time_context":"current"}\'^^rdf:JSON; ow:diagnosticEffect "support" .\now:ExamX a ow:ExamFinding; rdfs:label "가상소견"@ko; ow:detectedBy ow:MethodX .\now:MethodX a ow:ExamMethod; ow:examRequestText "가상 진찰을 하겠습니다" .\now:Context a ow:ContextFactor; rdfs:label "가상병력"@ko; ow:contextType "past_medical_history" .\now:TestX a ow:Test; rdfs:label "가상검사"@ko .\now:Alpha ow:hasAssociation ow:alphaContext .\now:alphaContext a ow:DiseasePatternAssociation; ow:pattern ow:contextPattern; ow:diagnosticEffect "support"; ow:targetScope \'{"subject":"patient","subject_member":null,"time_context":"any"}\'^^rdf:JSON .\now:contextPattern a ow:ClinicalPattern; ow:targets ow:Context; ow:hasFeature ow:contextPresent .\now:contextPresent a ow:ClinicalFeature; ow:expectedStatus "present" .\n'


def knowledge():
    graph = Graph().parse(SOURCE / 'knowledge/schema.ttl', format='turtle')
    graph.parse(data=TTL, format='turtle')
    names = dict(Alpha='Disease alpha', Beta='Disease beta', Complaint='Test complaint', Other='Other symptom',
        Location='Location', Quality='Quality', Here='head', Elsewhere='abdomen', Dull='dull',
        ExamX='Test examination finding', Context='Test history', TestX='Test evaluation')
    for ident,name in names.items():
        graph.add((OW[ident], RDFS.label, Literal(name, lang='en')))
    questions = {str(OW[key]):QuestionTemplate(text=text, answer_type=kind, affirmative=kind=='presence')
        for key,text,kind in [('Complaint','가상증상이 있나요?','presence'), ('Other','별도증상이 있나요?','presence'),
            ('Location','어느 부위인가요?','category'), ('Quality','어떤 느낌인가요?','category'),
            ('Context','가상병력이 있나요?','presence')]}
    k = ClinicalKnowledge(graph, questions=questions, attribute_roles={str(OW.Location):AttributeRole(order=0,category='other'), str(OW.Quality):AttributeRole(order=1,category='quality')})
    k.validate_graph()
    k.validate_question_assets()
    k.prepare_terms()
    return k


def resources(k=None, education=False):
    k = k or knowledge()
    if education and k.guidelines is None:
        k.guidelines = SimpleNamespace(read=lambda disease:([],[]))
    return PreparedResources(k, CONFIG.model_copy(update={'education_enabled':education}))


def state(scope='Initiation', *, turns=50, initialized=False):
    s = WorkflowState(session=SessionContext(session_id='offline', deadline=FIXED+timedelta(minutes=25), turns_remaining=turns))
    s.interview.current = scope
    s.interview.status = 'collecting' if initialized else 'uninitialized'
    return s


def graph_fact(**values):
    binding = {key: values.pop(key) for key in ('kind', 'target', 'attribute', 'values') if key in values}
    binding['method'] = values.pop('binding', 'exact')
    return CaseFact(graph_binding=GraphBinding(**binding), **values)


def unbound(case):
    return {key: value for key, value in case.facts.items() if value.graph_binding is None}


def graph_facts(case):
    return {key: value for key, value in case.facts.items() if value.graph_binding is not None}


def freeze_for_education(consultation, state):
    state.interview.current = 'DifferentialDiagnosis'
    consultation.close_collection(state)
    state.interview.current = 'Education'


def fact(ident='chief', **changes):
    values = dict(id=ident, kind='symptom', target='Test complaint', status='present', acquisition='SAY',
        source_ref=ident, observation_id='obs1', episode_id='episode1', time_context='current', category='presentation')
    values.update(changes)
    return graph_fact(**values)


def chief(s):
    s.case.apply([fact()])
    return s


def statement(quote='Reported complaint', **changes):
    row = dict(quote=quote, role='clinical', assertion='present', target_terms=['Test complaint'], time_context='current')
    row.update(changes)
    return row


class FakeSDK:
    timeout = 120
    def __init__(self, *, target='Test complaint', context='present', education=False, chat_handler=None):
        self.session_id, self.remaining = 'offline-case', 50
        self.deadline = FIXED + timedelta(minutes=25)
        self.status, self.target, self.context = 'active', target, context
        self.actions, self.submissions, self.requests = [], [], []
        self.chat_handler = chat_handler
    def session(self):
        return dict(session_id=self.session_id, status=self.status, deadline=self.deadline.isoformat(),
            turns_remaining=self.remaining, initial={'opening':self.target}, allowed_actions=['SAY','EXAM','DIAGNOSE'])
    @staticmethod
    def completion(value, *, finish_reason='stop'):
        return {'choices':[{'message':{'content':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)},
                            'finish_reason':finish_reason}], 'usage':{'prompt_tokens':20,'completion_tokens':10}}
    def chat(self, messages, **kwargs):
        payload = decode_context(messages[-1]['content'])
        self.requests.append(copy.deepcopy(payload))
        if self.chat_handler:
            reply = self.chat_handler(payload)
            if reply is not None:
                return reply if isinstance(reply,dict) and 'choices' in reply else self.completion(reply)
        clinical = clinical_response(payload)
        if clinical is not None:
            return self.completion(clinical)
        education = education_response(payload)
        if education is not None:
            return self.completion(education)
        if payload['task'] == 'input_mapping':
            return self.completion([{} for _ in payload['statements']])
        q, text = payload['question'], payload['input']
        if q is None:
            return self.completion({'statements':[statement(text, target_terms=[self.target], primary_concern=True)]})
        purpose = q['purpose']
        if purpose == 'open_inquiry':
            return self.completion({'statements':[statement(text,role='nonclinical',assertion='unknown',target_terms=[])]})
        if purpose in {'intake','history'}:
            return self.completion({'statements':[statement(text, target_terms=[], assertion_scope='domain',
                record_category=q['category'],note_value='No reported '+q['category'].replace('_',' '),assertion='absent')]})
        if q.get('attribute'):
            return self.completion({'statements':[statement(text,focus='attribute',target_terms=[q['target']],
                attribute_terms=[q['attribute']],value_terms=['head' if q['attribute']=='Location' else 'dull'],
                observation_id=q['observation_id'],episode_id=q['episode_id'])]})
        if purpose == 'context':
            return self.completion({'statements':[statement(text,target_terms=[q['target']],
                subject=q.get('subject','patient'), time_context=q.get('time_context','unspecified'),
                role='unknown' if self.context=='unknown' else 'clinical',assertion=self.context)]})
        return self.completion({'statements':[statement(text,target_terms=[q.get('target') or self.target],
            subject=q.get('subject','patient'), time_context=q.get('time_context','current'))]})
    def _action(self, kind, content, request_id):
        self.remaining -= 1
        self.actions.append(dict(kind=kind,content=content,request_id=request_id))
        return dict(status='OK',turn=50-self.remaining,turns_remaining=self.remaining,
                    **{'content' if kind=='SAY' else 'result':'확인한 환자 응답입니다'})
    def say(self, content, request_id):
        return self._action('SAY',content,request_id)
    def exam(self, content, request_id):
        return self._action('EXAM',content,request_id)
    def diagnose(self, **payload):
        self.submissions.append(copy.deepcopy(payload))
        return {'status':'completed'}


def consultation(client=None, prepared=None, *, audit=None, cache=True):
    ids = itertools.count(1)
    c = assemble_consultation(client or FakeSDK(), prepared or resources(), now=lambda:FIXED,
        sleep=lambda delay:None,new_request_id=lambda:f'request-{next(ids)}')
    if audit:
        attach_sink(c,audit)
    return c


def run(client=None, prepared=None, *, audit=None, cache=True):
    from execution import observing_operations
    c = consultation(client, prepared, audit=audit, cache=cache)
    s = c.nova_session.initialize_case(c.client)
    snapshots = []
    def capture(kind, name, state, error):
        if kind == 'end':
            snapshots.append((name, state.model_dump(mode='json')))
    with observing_operations(c, capture):
        c.run(s)
    return c,s,snapshots


def interpret(rows, *, s=None, q=None, k=None, text=None, audit=None, responses=None):
    from workflow.state.models import TurnContext
    s,k = s or state(), k or knowledge()
    text = text or ' '.join(row['quote'] for row in rows)
    def handler(payload):
        if responses:
            return responses(payload)
        if payload['task']=='input_context':
            return {'statements':rows}
    client = FakeSDK(chat_handler=handler)
    c = consultation(client, resources(k),audit=audit)
    if q:
        c.questions.register(s,q)
        c.interactions.select_question(s,q)
        s.turn.stage,s.turn.response = 'received', {'content':text,'result':text,'turn':1}
    else:
        s.turn = TurnContext(kind='initial',response={'opening':text})
    c.ear.process_input(s,k,client)
    return s,c,client


def add_pattern(k,name,target,expectations,*,disease=OW.Beta,applicability=None,effect="strong_support",scope=None,presence=True):
    pattern,association=OW[name],OW[name+'Association']
    k._graph.add((disease,OW.hasAssociation,association))
    for predicate,value in ((RDF.type,OW.DiseasePatternAssociation),(OW.pattern,pattern),
            (OW.diagnosticEffect,Literal(effect)),
            (OW.targetScope,Literal(json.dumps(scope or dict(subject='patient',subject_member=None,time_context='current')),datatype=RDF.JSON))):
        k._graph.add((association,predicate,value))
    if applicability:
        applicability=[dict(subject_member=None,**item) for item in applicability]
        k._graph.add((association,OW.applicability,Literal(json.dumps(applicability),datatype=RDF.JSON)))
    k._graph.add((pattern,RDF.type,OW.ClinicalPattern))
    k._graph.add((pattern,OW.targets,target))
    include_presence=presence
    presence=OW[name+'Presence']
    if include_presence: k._graph.add((pattern,OW.hasFeature,presence))
    if include_presence:
        k._graph.add((presence,RDF.type,OW.ClinicalFeature))
        k._graph.add((presence,OW.expectedStatus,Literal('present')))
    for index,(attribute,expected) in enumerate(expectations):
        k._graph.add((target,OW.hasAttribute,attribute))
        feature,node=OW[name+f'Feature{index}'],OW[name+f'Expected{index}']
        for predicate,value in ((RDF.type,OW.ClinicalFeature),(OW.onAttribute,attribute),(OW.expected,node)):
            k._graph.add((feature,predicate,value))
        k._graph.add((pattern,OW.hasFeature,feature))
        k._graph.add((node,RDF.type,OW.ExpectedValue))
        k._graph.add((node,OW.valueJSON,Literal(json.dumps(expected),datatype=RDF.JSON)))
    k.validate_graph()
    k.prepare_terms()
    return pattern

def freeze(state, *, kind='disease', name='Disease alpha'):
    from workflow.state.models import Assessment, DifferentialEntry
    state.case.assessment = Assessment(differential=(DifferentialEntry(kind=kind,name=name),),
        based_on_case_revision=state.case.revision,based_on_chief_fact_id=state.case.chief_fact_id,frozen=True)
