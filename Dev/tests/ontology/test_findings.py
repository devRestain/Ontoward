from collections import defaultdict
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

from rdflib import RDF, URIRef
from Dev.ontology.findings import project, finding_uri, observable_uri, METHOD, INTERPRETS, INTERPRETATION
from Dev.ontology.provenance import EvidenceSets
from Dev.ontology.storage import archive_file
from Dev.ontology.v5 import OW, PreviewBuilder, write


def run():
    checks=[]
    def require(value,name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    class Sources:
        def __init__(self):
            self.connection=sqlite3.connect(':memory:')
            self.connection.row_factory=sqlite3.Row
            self.connection.execute('CREATE TABLE rf2_components(id,source_id,destination_id,type_id,relationship_group,row_id,concrete_value,kind,active,characteristic)')
        def bodhi_rows(self,name):
            return []
    class Terminology:
        findings={'physical','ambiguous','history','lab','morphology','sign'}
        diseases={'disorder'}
        signs={'sign'}
        children=defaultdict(list)
        fsns={cid:cid for cid in findings|diseases|{'observable1','observable2'}}
        def active(self,cid):
            return bool(cid)
        def descendants(self,seeds):
            groups={'363788007':{'observable1','observable2'},'84100007':{'84100007'},
                    '37931006':{'37931006'},'108252007':{'108252007'}}
            return set().union(*(groups.get(cid,set()) for cid in seeds))
    database=Sources()
    relationships=[('physical','37931006',METHOD,'0'),('physical','observable1',INTERPRETS,'1'),
        ('physical','value',INTERPRETATION,'1'),('physical','disorder','42752001','1'),
        ('ambiguous','observable1',INTERPRETS,'1'),('ambiguous','observable2',INTERPRETS,'1'),
        ('ambiguous','value',INTERPRETATION,'1'),('history','84100007',METHOD,'0'),
        ('history','observable1',INTERPRETS,'1'),('lab','108252007',METHOD,'0'),
        ('lab','observable1',INTERPRETS,'1'),('morphology','shape','116676008','2'),
        ('morphology','site','363698007','2'),('observable1','unit','246514001','0')]
    database.connection.executemany('INSERT INTO rf2_components VALUES(?,?,?,?,?,?,NULL,?,?,?)',
        ((str(n),source,target,kind,group,n,'relationship','1','900000000000011006')
         for n,(source,target,kind,group) in enumerate(relationships)))
    source,proofs,details=project(database,Terminology(),PreviewBuilder())
    require(set(details['candidates'])=={'physical','ambiguous','morphology','sign'},
            'physical_observable_morphologic_and_sign_roles_are_discovered')
    require(details['candidates']['physical']['acquisition']=='physical_exam_evidenced' and
            details['candidates']['ambiguous']['acquisition']=='acquisition_unresolved',
            'observed_dimension_does_not_imply_a_physical_acquisition_method')
    require(details['excluded']['patient_history_method']==1 and details['excluded']['laboratory_or_imaging_method']==1,
            'patient_history_and_laboratory_methods_are_not_physical_exams')
    paired=[binding for binding in details['bindings'] if binding['role']=='same_group_observable_interpretation']
    require(len(paired)==1 and paired[0]['target']==finding_uri('physical') and paired[0]['group']=='1',
            'only_unique_same_group_interpretation_becomes_a_value_binding')
    require(len(details['unresolved_groups'])==1 and details['unresolved_groups'][0]['target']==finding_uri('ambiguous'),
            'ambiguous_interpretations_are_retained_without_cartesian_values')
    require((URIRef(finding_uri('physical')),OW.detectedBy,URIRef(str(OW)+'ExamMethodSnomedCT37931006')) in proofs,
            'detection_link_has_exact_method_relationship_proof')
    require(not list(source.vocabulary.triples((None,OW.examRequestText,None))),'missing_clinical_request_text_is_not_invented')
    require(details['observable_metadata']['observable1']['units_specified'] and
            details['observable_metadata']['observable1']['numeric_limits']=='not_inferred',
            'source_unit_metadata_does_not_invent_a_numeric_threshold')
    require((URIRef(observable_uri('observable1')),RDF.type,OW.FindingAttribute) in source.vocabulary,
            'clinical_observables_are_explicit_comparison_dimensions')
    assertion=next(iter(source.assertions.values()))[0]
    require(assertion['raw']['identity_scope']=='exact_precoordinated_finding_not_generalized' and
            len(assertion['raw']['definition_relationship_ids'])==4,
            'disease_association_retains_the_complete_source_finding_definition')
    database.connection.close()
    scratch=ROOT/'Tmp/d19-verification/findings'
    scratch.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=scratch) as temporary:
        directory=Path(temporary)
        pool=EvidenceSets()
        common=pool.intern(['rf2:1','rf2:2','rf2:1'])
        require(common==pool.intern(['rf2:2','rf2:1']),'shared_evidence_is_order_independent_and_deduplicated')
        pool.save(directory/'evidence.json')
        require(EvidenceSets.load(directory/'evidence.json').resolve(common)==('rf2:1','rf2:2'),
                'shared_evidence_roundtrip_preserves_exact_references')
        original=directory/'source.json'
        payload=(b'{"evidence":"repeated source reference"}\n'*1000)
        original.write_bytes(payload)
        first=archive_file(original,directory/'archives')
        second=archive_file(original,directory/'archives')
        require(first==second and len(list((directory/'archives').iterdir()))==1,
                'identical_historical_files_share_one_verified_lossless_archive')
        require(first['archive_bytes']<len(payload) and original.read_bytes()==payload,
                'archival_verification_keeps_original_bytes_until_the_explicit_compaction_step')
        (directory/'archives'/first['archive']).write_bytes(b'corrupt')
        try:
            archive_file(original,directory/'archives')
        except (ValueError,OSError,EOFError):
            require(original.read_bytes()==payload,'corrupt_archive_rejects_compaction_without_losing_original')
        else:
            raise AssertionError('corrupt_archive_was_accepted')
    result={'status':'pass','check_count':len(checks),'checks':checks,'real_model_calls':0,'network':'none'}
    write(scratch/'verification.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    run()
