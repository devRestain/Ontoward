import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

from rdflib import Graph, RDF, URIRef
from rdflib.util import from_n3
from Dev.ontology.database import SourceDatabase, file_hash
from Dev.ontology.findings import AXES, METHOD, INTERPRETS, INTERPRETATION, OBSERVABLE_METADATA, discover, finding_uri, observable_uri
from Dev.ontology.provenance import EvidenceSets
from Dev.ontology.source_projection import SnapshotSources
from Dev.ontology.v5 import OW, write


def verify(directory):
    directory = directory.resolve()
    db = SourceDatabase(directory/'ontology.sqlite3',readonly=True)
    checks = []
    def require(value,name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    try:
        terminology = SnapshotSources(db)
        candidates,observables,relations,excluded = discover(db,terminology)
        catalog = directory/'catalog'
        graph = Graph().parse(catalog/'source-findings.ttl',format='turtle')
        report = json.loads((catalog/'finding-coverage.json').read_text())
        require({str(node) for node in graph.subjects(RDF.type,OW.ExamFinding)}=={finding_uri(cid) for cid in candidates},
                'all_evidenced_finding_roles_are_projected')
        for cid,method in {'88610006':'37931006','58840004':'37931006','248618001':'37931006',
                           '43478001':'113011001','35611005':'113011001'}.items():
            target = URIRef(finding_uri(cid))
            require(cid in candidates and (target,OW.detectedBy,URIRef(str(OW)+'ExamMethodSnomedCT'+method)) in graph,
                    'previously_missing_finding_and_exact_method:'+cid)
        require(all(cid not in terminology.diseases for cid in candidates),'source_exam_findings_are_non_disorder_findings')
        require(excluded['patient_history_method']>0 and excluded['laboratory_or_imaging_method']>0,
                'history_and_test_acquisition_are_excluded_from_exam_candidates')
        for subject,_,method in graph.triples((None,OW.detectedBy,None)):
            cid = str(subject).removeprefix(str(OW)+'ExamFindingSnomedCT')
            method_id = str(method).removeprefix(str(OW)+'ExamMethodSnomedCT')
            if not any(row['destination_id']==method_id and row['type_id']==METHOD for row in relations[cid]):
                raise AssertionError('invented_detection_method')
        require(True,'every_detection_link_is_an_exact_finding_method_relationship')
        require(not list(graph.triples((None,OW.examRequestText,None))),'no_unreviewed_exam_request_is_invented')
        metadata = json.loads((catalog/'observable-metadata.json').read_text())
        require(set(metadata)==observables,'all_supplied_clinical_observable_dimensions_are_retained')
        for cid,item in metadata.items():
            expected = {row['id'] for row in relations[cid] if row['type_id'] in OBSERVABLE_METADATA}
            if set(item['relationships'])!=expected or item['numeric_limits']!='not_inferred':
                raise AssertionError('observable_metadata_not_preserved')
        require(True,'observable_units_scale_technique_and_other_metadata_preserve_source_relationships')
        bindings = json.loads((catalog/'finding-bindings.json').read_text())
        for binding in bindings:
            cid = binding['target'].removeprefix(str(OW)+'ExamFindingSnomedCT')
            rows = {row['id']:row for row in relations[cid]}
            members = [rows[ref.removeprefix('rf2:')] for ref in binding['source_refs']]
            if {row['relationship_group'] for row in members}!={binding['group']}:
                raise AssertionError('binding_crosses_source_groups')
            if binding['role']=='defining_attribute':
                row, = members
                if binding['attribute']!=str(OW[AXES[row['type_id']]]) or binding['value']!=str(OW)+'SnomedCT'+row['destination_id']:
                    raise AssertionError('defining_attribute_or_value_changed')
            else:
                interpreted,value = members
                scoped = [row for row in relations[cid] if row['relationship_group']==binding['group']]
                if (interpreted['type_id']!=INTERPRETS or value['type_id']!=INTERPRETATION
                        or sum(row['type_id']==INTERPRETS and row['destination_id'] in observables for row in scoped)!=1
                        or sum(row['type_id']==INTERPRETATION for row in scoped)!=1
                        or binding['attribute']!=observable_uri(interpreted['destination_id'])
                        or binding['value']!=str(OW)+'SnomedCT'+value['destination_id']):
                    raise AssertionError('ambiguous_or_changed_interpretation_pair')
        require(True,'all_attribute_value_bindings_preserve_exact_types_values_and_group_scope')
        domains = report['observable_domains']
        for cid in ('363820009','363870007','363926002','363989006','364048003','364066008',
                    '364142000','364178005','364561008','364528001','364319003','364673002'):
            require(cid in domains and domains[cid]['comparison_dimensions']>0,'clinical_observable_domain:'+cid)
        source_specialties = {row['id'] for _,_,row in db.bodhi_rows('nodes_speciality.csv')}
        require(set(report['specialties'])==source_specialties and len(source_specialties)==39,
                'all_thirty_nine_specialties_have_source_coverage_and_gap_reports')
        require(all(row['gap'] and row['executable_exam_requests']==0 for row in report['specialties'].values()),
                'source_coverage_does_not_claim_executable_or_clinically_sufficient_exams')
        require(report['numeric_thresholds_inferred']==0 and report['runtime_admission']=='not_run',
                'no_numeric_threshold_or_clinical_admission_is_inferred')
        for row in db.connection.execute('SELECT payload FROM catalog_assertions'):
            assertion = json.loads(row[0])
            if assertion['relation_basis'] in {'due_to','associated_with'}:
                raw = assertion['raw']
                expected = {member['id'] for member in relations[raw['source_concept_id']]}
                if raw['identity_scope']!='exact_precoordinated_finding_not_generalized' or set(raw['definition_relationship_ids'])!=expected:
                    raise AssertionError('partial_source_definition_was_generalized')
        require(True,'source_disease_links_keep_the_complete_precoordinated_finding_identity')
        pool = EvidenceSets.load(catalog/'evidence.json')
        workset_path = directory/'korean-workset.json'
        workset = json.loads(workset_path.read_text())
        require('source_refs' not in workset_path.read_text(),'workset_never_embeds_expanded_evidence_lists')
        require(workset['evidence_sha256']==file_hash(catalog/'evidence.json'),'workset_pins_shared_evidence')
        entries = {entry['uri']:entry for entry in workset['entries']}
        links = {}
        with (catalog/'relations.jsonl').open() as stream:
            for line in stream:
                row = json.loads(line)
                if row['predicate']==str(OW.hasAttribute) and 'n3' in row['object']:
                    links[row['subject'],str(from_n3(row['object']['n3']))] = row['evidence']['evidence_id']
        jobs = workset['label_jobs']+workset['question_jobs']
        for job in jobs:
            for key in job['evidence_ids']:
                pool.resolve(key)
        for job in workset['question_jobs']:
            expected = {entries[job['target']]['evidence_id']}
            if job['attribute']:
                expected.add(links[job['target'],job['attribute']])
            if set(job['evidence_ids'])!=expected:
                raise AssertionError('question_copies_global_attribute_proof')
        require(True,'each_question_uses_only_target_and_target_specific_attribute_link_proof')
        require(len({job['job_id'] for job in jobs})==len(jobs),'compact_workset_keeps_distinct_job_identity')
        l,q = len(workset['label_jobs']),len(workset['question_jobs'])
        require(workset['max_calls']==2*((l+19)//20+(q+19)//20),'compact_workset_preserves_full_finite_budget')
        audit = json.loads((directory/'preview/sources.json').read_text())
        require(audit['format']=='sqlite-source-audit-v1' and audit['build_id']==db.meta('build_id'),
                'preview_references_the_canonical_sqlite_audit')
        missing = db.connection.execute("""SELECT COUNT(*) FROM dispositions d LEFT JOIN source_expressions e
            ON e.id=json_extract(d.payload,'$.expression_id')
            WHERE json_extract(d.payload,'$.dataset')='SNOMED_CT' AND (e.id IS NULL
            OR json_type(d.payload,'$.qualifiers') IS NOT NULL OR json_type(d.payload,'$.relationships') IS NOT NULL)""").fetchone()[0]
        require(missing==0,'rf2_decisions_reference_shared_complete_expressions_without_copying_them')
        require(not list(directory.glob('interrupted-preview-*')),'new_build_does_not_accumulate_automatic_preview_copies')
        result = {'status':'pass','check_count':len(checks),'checks':checks,'exam_findings':len(candidates),
            'clinical_observables':len(observables),'attribute_value_bindings':len(bindings),
            'specialties_with_source_findings':sum(item['source_exam_findings']>0 for item in report['specialties'].values()),
            'workset_bytes':workset_path.stat().st_size,'labels':l,'questions':q,'max_calls':workset['max_calls'],
            'real_model_calls':0,'korean_execution':'deferred','clinical_validation':'not_run','runtime_admission':'not_run'}
        write(directory/'finding-verification.json',result)
        return result
    finally:
        db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    result=verify(parser.parse_args().directory)
    print(json.dumps({key:value for key,value in result.items() if key!='checks'},indent=2))
