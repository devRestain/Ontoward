import argparse
from collections import Counter
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'submission'))

from Dev.ontology.database import SourceDatabase,file_hash
from Dev.ontology.contributions import feature_contributions
from Dev.ontology.v5 import write
from knowledge.graph import ClinicalKnowledge,OW
from knowledge.conditions import ScoringPolicy
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.state.models import ClinicalValue,RecordItem,SessionContext,WorkflowState
from rdflib import Graph,RDF


def verify(directory,output=None):
    directory=directory.resolve()
    db=SourceDatabase(directory/'ontology.sqlite3',readonly=True)
    checks=[]
    def require(value,name):
        if not value: raise AssertionError(name)
        checks.append(name)
    try:
        require(db.meta('stage')=='complete','completed_full_build')
        require(db.connection.execute('PRAGMA quick_check').fetchone()[0]=='ok','sqlite_integrity')
        inventory=db.inventory()
        total=0
        for source in inventory:
            require(source['complete']==1,'complete_source:'+source['path'])
            actual=db.connection.execute('SELECT COUNT(*) FROM source_rows WHERE file_id=?',(source['id'],)).fetchone()[0]
            require(actual==source['row_count'],'row_accounting:'+source['path'])
            require(file_hash(ROOT/source['path'])==source['sha256'],'unchanged_source:'+source['path'])
            total+=actual
        require(total==db.connection.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0],'all_input_rows_accounted')
        require(db.connection.execute("SELECT COUNT(*) FROM source_rows WHERE disposition IS NULL OR reason IS NULL OR reason=''").fetchone()[0]==0,'every_row_has_explained_disposition')
        require(db.connection.execute('PRAGMA foreign_key_check').fetchone() is None,'source_and_projection_references_valid')
        require(db.connection.execute('SELECT COUNT(*) FROM inactive_rf2_rows').fetchone()[0]==
                db.connection.execute("SELECT COUNT(*) FROM rf2_components WHERE active='0'").fetchone()[0],
                'inactive_component_classification_is_lossless_without_raw_source_rewrites')
        roles=db.meta('target_roles')
        require(len(roles)>3,'full_clinical_target_discovery')
        files={Path(s['path']).name:s['row_count'] for s in inventory}
        require(files['nodes_condition.csv']==779 and files['nodes_symptom.csv']==4037 and files['edges_present_in.csv']==10352,'complete_bodhi_diagnostic_files')
        require(sum(files[name] for name in ('edges_present_in.csv','edges_treated_by.csv','edges_is_influenced_by.csv','edges_related_to.csv','edges_has_prerequisite.csv'))==13204,'all_bodhi_relationship_types_retained')
        modules=db.meta('composition')['module_versions']
        require(modules['11000267109']=='20260615' and modules['900000000000207008']=='20260501','pinned_international_korean_composition')
        preview=directory/'preview'
        manifest=json.loads((preview/'manifest.json').read_text())
        require(manifest['preparation_status']=='preview_only','preview_cannot_claim_admission')
        for asset in [manifest['schema'],manifest['vocabulary'],*manifest['bundles'],manifest['scoring_policy']]:
            require(file_hash(preview/Path(asset['path']).name)==asset['sha256'],'rdf_asset_digest:'+asset['path'])
        started=time.perf_counter()
        graph=Graph()
        for name in ('schema.ttl','vocabulary.ttl','clinical.ttl'):
            graph.parse(preview/name,format='turtle')
        knowledge=ClinicalKnowledge(graph,policy=ScoringPolicy.model_validate_json((preview/'scoring_policy.json').read_text()))
        knowledge.validate_graph()
        elapsed=time.perf_counter()-started
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        require(elapsed<=600 and peak<=8*1024*1024,'full_preview_load_under_runtime_limits')
        require(len(knowledge._profile_cache)==db.connection.execute('SELECT COUNT(*) FROM associations').fetchone()[0],'rdf_sqlite_associations_match')
        original=set(graph)
        profiles=list(knowledge._profile_cache.values())
        require(any(p.relation_basis=='bodhi_present_in' and p.score==0 for p in profiles),'valid_zero_labels_retained')
        require(any(p.relation_basis!='bodhi_present_in' for p in profiles),'real_snomed_associations_projected')
        grouped={}
        for p in profiles: grouped.setdefault(p.id,[]).append(p)
        require(any(len({p.disease_id for p in group})>1 and len({p.score for p in group})>1 for group in grouped.values()),'shared_patterns_keep_disease_specific_scores')
        disease,target=str(OW.SnomedCT65275009),str(OW.SymptomSnomedCT21522001)
        candidates=[p for p in knowledge.get_disease_patterns(disease) if p.target==target]
        features={p.association_id:knowledge.get_pattern_features(p.id) for p in candidates}
        baseline=next(p for p in candidates if all(f.expected is None for f in features[p.association_id]))
        locations=[p for p in candidates if all(not f.expected or f.attribute==str(OW.Location) for f in features[p.association_id])]
        upper=next(p for p in locations if p.score==1 and len([f for f in features[p.association_id] if f.expected])==1)
        detailed=next(p for p in locations if p.score==4 and knowledge.pattern_refines(p.id,upper.id))
        require((baseline.score,upper.score,detailed.score)==(2,1,4),'real_source_refinement_weights')
        require(any(c.delta_score==-1 and c.kind=='atomic' for c in feature_contributions(knowledge,upper.association_id)) and
                any(c.delta_score==2 and c.kind=='joint' for c in feature_contributions(knowledge,detailed.association_id)),'atomic_and_joint_contributions')
        state=WorkflowState(session=SessionContext(session_id='synthetic-full-db-check',deadline=datetime.now(timezone.utc)+timedelta(minutes=5),turns_remaining=50,current='DifferentialDiagnosis',initialized=True))
        def observe(ident,attribute=None,expected=None,episode='one',status='present'):
            state.case.put('S.hpi' if attribute else 'S.cc',RecordItem(id=ident,scope='DifferentialDiagnosis',status='done',source_refs=['synthetic:'+ident],
                value=ClinicalValue(kind='attribute' if attribute else 'symptom',text=ident,status=status,concept_ids=[target],attribute_id=attribute,
                                   values=[expected] if expected else [],observation_id='abdominal',episode_id=episode,time_context='current')))
        reasoner=ClinicalReasoner(knowledge)
        observe('pain')
        reasoner.retrieve_candidates(state)
        score=lambda:next(h.evidence_score for h in state.differential.hypotheses if h.disease_id==disease)
        sequence=[score()]
        condition=next(f for f in features[upper.association_id] if f.expected)
        observe('unknown',condition.attribute,condition.expected.concept,status='unknown')
        reasoner.refresh_hypotheses(state)
        require(score()==2,'unknown_detail_never_activates_refinement')
        state.case.remove({'unknown'})
        observe('upper',condition.attribute,condition.expected.concept)
        reasoner.refresh_hypotheses(state)
        sequence.append(score())
        other=next(f for f in features[detailed.association_id] if f.expected and f.signature()!=condition.signature())
        observe('right-upper',other.attribute,other.expected.concept)
        reasoner.refresh_hypotheses(state)
        sequence.append(score())
        require(sequence==[2,1,4],'real_full_graph_replaces_ancestor_scores')
        state.case.get('right-upper').value.episode_id='two'
        reasoner.refresh_hypotheses(state)
        require(score()==1,'separate_episodes_cannot_complete_variant')
        require(set(graph)==original,'retrieval_and_scoring_leave_graph_read_only')
        kinds=Counter(f.expected.kind for pattern in grouped for f in knowledge.get_pattern_features(pattern) if f.expected)
        require(all(kinds[k] for k in ('concept','concept_set','quantity','interval')),'all_four_value_types_retained')
        query_started=time.perf_counter()
        query_targets=sorted(knowledge._target_profiles)[:100]
        for target_id in query_targets: knowledge.get_patterns_by_target(target_id)
        query_seconds=time.perf_counter()-query_started
        receipt=json.loads((preview/'review-batch.json').read_text())
        require(receipt['approved'] is False and not receipt['approved_associations'],'human_approval_remains_pending')
        result={'status':'pass','checks':checks,'check_count':len(checks),'source_files':len(inventory),'source_rows':total,
                'patterns':len(grouped),'associations':len(profiles),'graph_triples':len(graph),'expected_value_kinds':dict(kinds),
                'preview_load_seconds':elapsed,'peak_rss_kib':peak,'indexed_query_count':len(query_targets),'indexed_query_seconds':query_seconds,
                'cholecystitis_scores':sequence,'network':'none','patient_observations':'synthetic',
                'clinical_review':'not_run','runtime_admission':'not_run','production_prepare':'not_run',
                'diagnostic_performance':'not_run','authenticated_sdk':'not_run'}
        write(output or directory/'verification.json',result)
        return result
    finally:
        db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=verify(args.directory,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='checks'},indent=2))
