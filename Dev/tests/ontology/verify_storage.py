import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

from Dev.ontology.database import SourceDatabase, file_hash
from Dev.ontology.source_projection import INFERRED
from Dev.ontology.storage import verify_archive
from Dev.ontology.v5 import digest, write


def verify(directory):
    directory=directory.resolve()
    db=SourceDatabase(directory/'ontology.sqlite3',readonly=True)
    old=directory.parent/'build'
    checks=[]
    def require(value,name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    try:
        require(db.meta('stage')=='complete','completed_source_build')
        for row in db.connection.execute('SELECT id,payload FROM source_expressions'):
            if digest(json.loads(row['payload']))!=row['id']:
                raise AssertionError('shared_source_expression_identity_changed')
        require(True,'every_shared_source_expression_matches_its_content_hash')
        invalid=db.connection.execute("""SELECT COUNT(*) FROM source_expressions e,json_each(e.payload,'$.relationship_ids') j
            LEFT JOIN rf2_components c ON c.kind='relationship' AND c.id=j.value
            WHERE c.id IS NULL OR c.active<>'1' OR c.characteristic<>?
                OR c.source_id<>json_extract(e.payload,'$.source_concept_id')""",(INFERRED,)).fetchone()[0]
        require(invalid==0,'every_expression_relationship_resolves_to_the_exact_active_inferred_source')
        incomplete=db.connection.execute("""SELECT COUNT(*) FROM source_expressions e WHERE
            json_array_length(e.payload,'$.relationship_ids')<>(SELECT COUNT(*) FROM rf2_components c
                WHERE c.kind='relationship' AND c.active='1' AND c.characteristic=?
                AND c.source_id=json_extract(e.payload,'$.source_concept_id'))""",(INFERRED,)).fetchone()[0]
        require(incomplete==0,'shared_expressions_preserve_the_complete_source_definition')
        require(db.connection.execute("SELECT COUNT(*) FROM source_rows WHERE reason='inactive_latest_component'").fetchone()[0]==0
                and db.connection.execute('SELECT COUNT(*) FROM inactive_rf2_rows').fetchone()[0]>0,
                'inactive_classification_uses_a_view_without_bulk_raw_row_rewrites')
        pool=json.loads((directory/'catalog/evidence.json').read_text())
        require(list(db.connection.execute('SELECT ref FROM evidence_refs ORDER BY id')) and
                [row[0] for row in db.connection.execute('SELECT ref FROM evidence_refs ORDER BY id')]==pool['refs'],
                'portable_evidence_dictionary_matches_the_canonical_database')
        sets={row[0]:json.loads(row[1]) for row in db.connection.execute('SELECT id,members FROM evidence_sets')}
        require(sets==pool['sets'],'portable_shared_sets_match_canonical_memberships')
        receipt=json.loads((old/'storage-compaction.json').read_text())
        unique={}
        for relative,record in receipt['files'].items():
            path=old/'archives'/record['archive']
            require(file_hash(path)==record['archive_sha256'],'archive_hash:'+relative)
            verify_archive(path,record['original_sha256'],record['original_bytes'])
            require(not (old/relative).exists(),'verified_large_original_removed:'+relative)
            unique[record['archive']]=record['archive_bytes']
        old_identity=json.loads((old/'workset-identity.json').read_text())
        require(receipt['files']['korean-workset.json']['original_sha256']==old_identity['sha256'],
                'archived_previous_workset_keeps_its_reserved_request_identity')
        require(sum(unique.values())==receipt['archive_logical_bytes'],'archive_accounting_deduplicates_content')
        old_db=SourceDatabase(old/'ontology.sqlite3',readonly=True)
        try:
            require(old_db.inventory()==db.inventory(),'old_and_new_builds_retain_identical_full_source_inventory')
            old_pages=dict(old_db.connection.execute('SELECT name,SUM(pgsize) FROM dbstat GROUP BY name'))
        finally:
            old_db.close()
        new_pages=dict(db.connection.execute('SELECT name,SUM(pgsize) FROM dbstat GROUP BY name'))
        require(new_pages['dispositions']<old_pages['dispositions'],'shared_expressions_reduce_disposition_storage')
        original=receipt['files']['korean-workset.json']['original_bytes']
        workset=(directory/'korean-workset.json').stat().st_size
        evidence=(directory/'catalog/evidence.json').stat().st_size
        require(workset+evidence<original,'larger_vocabulary_workset_and_shared_evidence_are_smaller_than_old_workset')
        audit=(directory/'preview/sources.json').stat().st_size
        require(audit<100000,'audit_export_is_a_small_database_reference')
        result={'status':'pass','check_count':len(checks),'checks':checks,
            'old_database_bytes':(old/'ontology.sqlite3').stat().st_size,
            'new_database_bytes':(directory/'ontology.sqlite3').stat().st_size,
            'old_table_pages_bytes':old_pages,'new_table_pages_bytes':new_pages,
            'old_workset_bytes':original,'new_workset_bytes':workset,'shared_evidence_bytes':evidence,
            'old_audit_json_bytes':receipt['files']['preview/sources.json']['original_bytes'],'new_audit_json_bytes':audit,
            'old_json_logical_bytes':receipt['original_logical_bytes'],'archive_logical_bytes':receipt['archive_logical_bytes'],
            'reduced_old_json_logical_bytes':receipt['reduced_logical_bytes'],
            'archive_receipt_sha256':file_hash(old/'storage-compaction.json'),'raw_sources_and_saved_base':'preserved',
            'physical_shared_block_occupancy':'not_measured','real_model_calls':0}
        write(directory/'storage-verification.json',result)
        return result
    finally:
        db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    result=verify(parser.parse_args().directory)
    print(json.dumps({key:value for key,value in result.items() if key not in {'checks','old_table_pages_bytes','new_table_pages_bytes'}},indent=2))
