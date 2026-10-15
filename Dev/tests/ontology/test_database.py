import csv
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'submission'))

from Dev.ontology.database import SourceDatabase,json_text,file_hash
from Dev.ontology.source_projection import BODHI_FILES,build,export,temporal_value
from Dev.ontology.model_normalization import ModelNormalizer,kst_day
from Dev.ontology.admission import admit,validated_selection,RULES
from knowledge.conditions import ExpectedValue,numeric_match


def run():
    scratch=Path(os.environ.get('ONTOWARD_ONTOLOGY_TEST_OUTPUT',ROOT/'Tmp/ontology-database-tests'))
    scratch.mkdir(parents=True,exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='run-',dir=scratch))
    checks=[]
    def require(value,name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    def fails(call,name):
        try:
            call()
        except (ValueError,sqlite3.IntegrityError):
            checks.append(name)
        else:
            raise AssertionError(name)
    module='900000000000207008'
    date='20260501'
    def table(path,columns,records,delimiter='\t'):
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=columns,delimiter=delimiter)
            writer.writeheader()
            writer.writerows(records)
    def row(cid,**values):
        return dict(id=cid,effectiveTime=date,active='1',moduleId=module,**values)
    release=directory/'international'
    release.mkdir()
    (release/'release_package_information.json').write_text(json.dumps({'effectiveTime':date,'licenceStatement':'synthetic_only'}))
    dependency=row('dependency',refsetId='dep',referencedComponentId='900000000000012004',sourceEffectiveTime=date,targetEffectiveTime=date)
    table(release/'Snapshot/Refset/Metadata/der2_ssRefset_ModuleDependencySnapshot_INT.txt',list(dependency),[dependency])
    concept_ids=['404684003','64572001','19019007','21522001','49727002','386661006','65275009','1010','999']
    concepts=[row(cid,definitionStatusId='primitive') for cid in concept_ids]
    table(release/'Snapshot/Terminology/sct2_Concept_Snapshot_INT.txt',list(concepts[0]),concepts)
    descriptions=[]
    names={'404684003':'Clinical finding (finding)','64572001':'Disease (disorder)','19019007':'Symptom (finding)',
           '21522001':'Abdominal pain (finding)','49727002':'Cough (finding)','386661006':'Fever (finding)',
           '65275009':'Cholecystitis (disorder)','1010':'Abdominal pain due to cholecystitis (finding)','999':'Old concept (finding)'}
    for index,cid in enumerate(concept_ids):
        descriptions.append(row(str(10000+index),conceptId=cid,languageCode='en',typeId='900000000000003001',term=names[cid],caseSignificanceId='case'))
    table(release/'Snapshot/Terminology/sct2_Description_Snapshot-en_INT.txt',list(descriptions[0]),descriptions)
    relationships=[]
    for child,parent in [('64572001','404684003'),('19019007','404684003'),('21522001','19019007'),('49727002','19019007'),('386661006','19019007'),('65275009','64572001'),('1010','21522001')]:
        relationships.append(row(str(20000+len(relationships)),sourceId=child,destinationId=parent,relationshipGroup='0',typeId='116680003',characteristicTypeId='900000000000011006',modifierId='mod'))
    relationships.append(row('30000',sourceId='1010',destinationId='65275009',relationshipGroup='1',typeId='42752001',characteristicTypeId='900000000000011006',modifierId='mod'))
    table(release/'Snapshot/Terminology/sct2_Relationship_Snapshot_INT.txt',list(relationships[0]),relationships)
    bodhi=directory/'bodhi/csv'
    original=ROOT/'assets/bodhi/bodhi-s/csv'
    variants=[]
    with (original/'nodes_symptom.csv').open(newline='') as f:
        symptom_columns=next(csv.reader(f))
    for uuid,location in [('base',''),('upper','upper abdomen'),('detailed','upper abdomen')]:
        item={key:'' for key in symptom_columns}
        item.update(uuid=uuid,root_snomed_id='21522001',root_snomed_name='Abdominal pain',name=uuid)
        if location:
            item.update(relation1_type='location',child1_name=location)
        if uuid=='detailed':
            item.update(relation2_type='location',child2_name='right upper quadrant')
        variants.append(item)
    item=dict(variants[0],uuid='linked',relation1_type='characteristic',child1_name='with chills')
    variants.append(item)
    records={}
    with (original/'nodes_condition.csv').open(newline='') as f:
        columns=next(csv.reader(f))
    condition={key:'' for key in columns}
    condition.update(snomed_id='65275009',name='Cholecystitis',concept_type='Disorder',type_condition='acute')
    records['nodes_condition.csv']=[condition]
    records['nodes_symptom.csv']=variants
    with (original/'edges_present_in.csv').open(newline='') as f:
        columns=next(csv.reader(f))
    edges=[]
    for uuid,weight in [('base','medium'),('upper','low'),('detailed','very_high'),('linked','high')]:
        edge={key:'' for key in columns}
        edge.update(symptom_uuid=uuid,condition_snomed_id='65275009',likelihood_condition_given_symptom=weight,likelihood_symptom_given_condition='medium')
        edges.append(edge)
    records['edges_present_in.csv']=edges
    for name in BODHI_FILES:
        with (original/name).open(newline='') as f:
            columns=next(csv.reader(f))
        table(bodhi/name,columns,records.get(name,[]),',')
    output=directory/'build'
    report=build(release,None,bodhi,output)
    require(report['bodhi_selected_variants']==4,'all_source_variants_accounted')
    require(report['bodhi_projected_variants']==3,'linked_finding_keeps_whole_variant_unresolved')
    require(report['associations']>=3,'source_associations_and_precedence')
    require(build(release,None,bodhi,output,resume=True)==report,'completed_resume_is_idempotent')
    db=SourceDatabase(output/'ontology.sqlite3')
    expected=sum(f['row_count'] for f in db.inventory())
    require(expected==db.connection.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0],'every_file_row_has_source_custody')
    require(db.connection.execute("SELECT COUNT(*) FROM source_rows WHERE disposition IS NULL OR reason IS NULL").fetchone()[0]==0,'every_source_row_has_disposition')
    receipt=json.loads((output/'preview/review-batch.json').read_text())
    fails(lambda:validated_selection(db,receipt),'pending_batch_cannot_admit')
    receipt.update(approved=True,approver='synthetic-test-only',approved_at=datetime.now(timezone.utc).isoformat(),
                   approved_associations=receipt['available_associations'],approved_registry=receipt['available_registry'],reviewed_rules=RULES)
    require(bool(validated_selection(db,receipt).graph),'explicit_pinned_batch_selection')
    missing=dict(receipt,approved_registry=[])
    fails(lambda:validated_selection(db,missing),'mapping_dependency_closure_required')
    altered=dict(receipt,candidate_set_sha256='0'*64)
    fails(lambda:validated_selection(db,altered),'stale_candidate_receipt_rejected')
    explicit=dict(receipt,reviewed_rules=[],accepted_rules=RULES,approval_basis='explicit_user_candidate_acceptance',independent_clinical_validation='not_run')
    require(bool(validated_selection(db,explicit).graph),'explicit_user_acceptance_does_not_claim_clinician_review')
    fails(lambda:validated_selection(db,dict(explicit,accepted_rules=RULES[:-1])),'acceptance_requires_all_source_rules')
    db.close()
    exported=directory/'export-again'
    export(output/'ontology.sqlite3',exported)
    require((exported/'clinical.ttl').read_bytes()==(output/'preview/clinical.ttl').read_bytes(),'deterministic_rdf_export')
    review_path=directory/'approved-synthetic.json'
    labels_path=directory/'labels.ko.json'
    labels_path.write_text(json.dumps({'urn:ontoward:AbdominalPain':'합성 복통'},ensure_ascii=False))
    questions_path=directory/'questions.ko.json'
    questions_path.write_text(json.dumps({'urn:ontoward:AbdominalPain':'합성 복통 있나요?'},ensure_ascii=False))
    receipt['text_assets']={name:{'path':path.relative_to(ROOT).as_posix(),'sha256':file_hash(path)}
                            for name,path in [('labels',labels_path),('questions',questions_path)]}
    review_path.write_text(json.dumps(receipt))
    production_manifest=ROOT/'submission/knowledge/manifest.json'
    production_before=file_hash(production_manifest) if production_manifest.exists() else None
    admitted=admit(output/'ontology.sqlite3',review_path,destination=directory/'admitted/submission/knowledge')
    require(admitted['status']=='admitted' and admitted['metrics']['associations']>=3,'isolated_admission_executes_real_prepare')
    require((file_hash(production_manifest) if production_manifest.exists() else None)==production_before,
            'synthetic_admission_never_touches_real_runtime')
    admitted_manifest=directory/'admitted/submission/knowledge/manifest.json'
    pinned=file_hash(admitted_manifest)
    require(admitted['clinical_text']=='minimal_questions_prepared' and 'labels' in json.loads(admitted_manifest.read_text()),'admission_prepares_pinned_question_and_label_assets')
    labels_path.write_text('{}')
    fails(lambda:admit(output/'ontology.sqlite3',review_path,destination=directory/'admitted/submission/knowledge'),'changed_text_pin_rejects_admission')
    require(file_hash(admitted_manifest)==pinned,'failed_text_admission_preserves_published_manifest')
    from knowledge.graph import ClinicalKnowledge,OW
    from Dev.ontology.v5 import PreviewBuilder
    from rdflib import Graph
    toy=PreviewBuilder()
    target='urn:ontoward:RefinementTestSymptom'
    disease='urn:ontoward:RefinementTestDisease'
    toy.concept(target,'Symptom','Synthetic symptom')
    toy.concept(disease,'Disease','Synthetic disease')
    category=toy.concept('urn:ontoward:RefinementTestValue','AttributeValue','Synthetic value')
    alternatives=[[],[{'attribute':str(OW.Location),'expected':{'kind':'concept','concept':str(category)}}],
                  [{'attribute':str(OW.Location),'expected':{'kind':'concept_set','concepts':[str(category)],'selection':'all_of'}}],
                  [{'attribute':str(OW.EpisodeDuration),'expected':{'kind':'quantity','value':2.0,'unit':'h','operator':'gt'}}],
                  [{'attribute':str(OW.EpisodeDuration),'expected':{'kind':'interval','lower':3.0,'upper':5.0,'unit':'h'}}]]
    pattern_ids=[]
    for features in alternatives:
        pattern=toy.pattern(target,features)
        pattern_ids.append(pattern)
        toy.association(disease,pattern,source_ref='synthetic',relation_basis='due_to')
    combined=Graph().parse(ROOT/'data/ontology/schema.ttl')
    combined+=toy.vocabulary
    combined+=toy.graph
    reader=ClinicalKnowledge(combined)
    reader.validate_graph()
    indexed=set(reader._refinement_edges(pattern_ids))
    expected={(child,parent) for child in pattern_ids for parent in pattern_ids if reader.pattern_refines(child,parent)}
    require(indexed==expected and bool(indexed),'indexed_refinement_preserves_numeric_set_and_presence_semantics')
    latest=directory/'latest.txt'
    newer=dict(concepts[-1],active='0')
    older=dict(concepts[-1],effectiveTime='20260401')
    table(latest,list(newer),[newer,older])
    merge=SourceDatabase(directory/'latest.sqlite3')
    merge.import_file(latest,dataset='SNOMED_CT',release_date=date,versions={module:date})
    require(merge.connection.execute("SELECT active FROM rf2_components WHERE id='999'").fetchone()[0]=='0','latest_selected_before_active_filter')
    conflict=directory/'conflict.txt'
    table(conflict,list(newer),[dict(newer,active='1')])
    fails(lambda:merge.import_file(conflict,dataset='SNOMED_CT',release_date=date,versions={module:date}),'same_version_conflict_rolls_back')
    future=directory/'future.txt'
    table(future,list(newer),[dict(newer,id='future',effectiveTime='20260601')])
    fails(lambda:merge.import_file(future,dataset='SNOMED_CT',release_date=date,versions={module:date}),'future_row_rejected')
    merge.close()
    require(temporal_value('more than a month')['operator']=='gt','explicit_calendar_article_normalization')
    interval=ExpectedValue.model_validate(temporal_value('30 mins to 3 hours'))
    observation=ExpectedValue(kind='quantity',value=2.0,unit='h')
    require(numeric_match(interval,observation)=='matched','mixed_fixed_time_interval_matches')
    fails(lambda:temporal_value('few hours'),'ambiguous_duration_not_invented')
    class Fake:
        def __init__(self,invalid=False): self.count=0;self.invalid=invalid
        def chat(self,messages,**kwargs):
            self.count+=1
            packets=json.loads(messages[-1]['content'])['packets']
            if self.invalid: return {'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
            items=[dict(packet_id=p['packet_id'],decision='unresolved',evidence=p['text'],reason='synthetic unresolved',features=[],role=None) for p in packets]
            return {'choices':[{'message':{'content':json.dumps({'items':items})},'finish_reason':'stop'}]}
    packets=[dict(packet_id=str(i),kind='qualifier',text='Ring shaped',target_id=str(i),axis='characteristic') for i in range(25)]
    ledger=directory/'ledger.sqlite3'
    fake=Fake()
    model=ModelNormalizer(ledger,max_calls=1,daily_remaining=100,client=fake,namespace='test')
    results=model.normalize(packets)
    require(fake.count==1 and len(results)==20,'run_allowance_stops_without_retry')
    model.close()
    cached=ModelNormalizer(ledger,max_calls=1,daily_remaining=99,client=fake,namespace='test')
    require(len(cached.normalize(packets[:20]))==20 and fake.count==1,'persistent_packet_cache_uses_no_calls')
    cached.close()
    bad=Fake(invalid=True)
    failed=ModelNormalizer(directory/'failure.sqlite3',max_calls=100,daily_remaining=100,client=bad)
    failed.normalize(packets)
    require(bad.count==1 and failed.stopped=='ValueError','malformed_whole_response_stops_once')
    failed.close()
    again=ModelNormalizer(directory/'failure.sqlite3',max_calls=100,daily_remaining=99,client=bad)
    again.normalize(packets[:20])
    require(bad.count==1,'failed_or_unknown_packets_never_auto_retransmit')
    again.close()
    shared=directory/'concurrent.sqlite3'
    initializer=ModelNormalizer(shared,max_calls=100,daily_remaining=100,client=Fake())
    for i in range(99):
        initializer.connection.execute('INSERT INTO calls VALUES(?,?,?, ?,NULL,NULL)',(str(i),kst_day(),'reserved','{}'))
    initializer.connection.commit()
    initializer.close()
    def reserve(i):
        worker=ModelNormalizer(shared,max_calls=100,daily_remaining=100,client=Fake())
        try: return bool(worker.reserve([dict(packets[i],packet_id='concurrent-'+str(i))]))
        finally: worker.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        reserved=list(executor.map(reserve,[0,1]))
    require(sum(reserved)==1,'concurrent_day_reservations_never_exceed_100')
    fails(lambda:ModelNormalizer(directory/'wrong-day.sqlite3',max_calls=1,daily_remaining=1,day='2000-01-01',client=Fake()),'allowance_date_must_be_current_kst')
    result={'status':'pass','checks':checks,'check_count':len(checks),'network':'none','model_calls':0,
            'patient_data':'synthetic','output':str(directory.relative_to(ROOT))}
    (directory/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    (scratch/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__': run()
