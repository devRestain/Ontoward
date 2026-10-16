import argparse
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from Dev.ontology.database import SourceDatabase, file_hash
from Dev.ontology.source_catalog import ROLE_RULES
from Dev.ontology.source_projection import SnapshotSources
from Dev.ontology.provenance import EvidenceSets
from Dev.ontology.findings import discover, PHYSICAL_METHOD_ROOTS
from Dev.ontology.v5 import write


def verify(directory):
    directory = directory.resolve()
    database = SourceDatabase(directory / "ontology.sqlite3", readonly=True)
    checks = []
    def require(value, name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    try:
        connection = database.connection
        catalog = directory / "catalog"
        manifest = json.loads((catalog / "manifest.json").read_text())
        report = json.loads((catalog / "coverage.json").read_text())
        require(database.meta("stage")=="complete","completed_source_build")
        require(set(report["classes"])==set(ROLE_RULES),"all_fourteen_classes_have_explicit_coverage_and_rules")
        require(all(item["nodes"] or item["unresolved_reason"] for item in report["classes"].values()),
                "empty_classes_are_explained_without_fabricated_nodes")
        require(manifest["scope"]=="competition_source_dependency_closure","catalog_uses_explicit_source_roles_and_dependencies")
        for name, sha in manifest["files"].items():
            require(file_hash(catalog/name)==sha,"catalog_pin:"+name)
        for name, sha in manifest["generator_files"].items():
            require(file_hash(ROOT/"Dev/ontology"/name)==sha,"generator_pin:"+name)
        for name, sha in manifest.get("prompt_files",{}).items():
            require(file_hash(ROOT/"Dev/ontology/prompts"/name)==sha,"prompt_pin:"+name)
        terminology = SnapshotSources(database)
        roots = {row["root_snomed_id"] for _,_,row in database.bodhi_rows("nodes_symptom.csv")}
        methods = terminology.descendants(PHYSICAL_METHOD_ROOTS)
        tests = terminology.descendants({'108252007','363679005'})
        finding_candidates,_,_,_ = discover(database,terminology)
        labels = json.loads((catalog/"lexical.json").read_text())
        pool = EvidenceSets.load(catalog/'evidence.json')
        assertion_refs = {json.loads(row[0])["source_ref"] for row in connection.execute("SELECT payload FROM source_assertions")}
        def source_ref(ref):
            if ref in assertion_refs:
                return
            if ref.startswith("source_row:"):
                row_id = int(ref.split(":")[1])
                if connection.execute("SELECT 1 FROM source_rows WHERE id=?",(row_id,)).fetchone() is None:
                    raise AssertionError("missing_source_row")
            elif ref.startswith("rf2:concept:"):
                if not terminology.active(ref.removeprefix("rf2:concept:")):
                    raise AssertionError("inactive_source_concept")
            elif ref.startswith("rf2:"):
                row=connection.execute("SELECT active FROM rf2_components WHERE kind='relationship' AND id=?",(ref[4:],)).fetchone()
                if row is None or row[0]!="1":
                    raise AssertionError("unresolved_relationship_reference")
            else:
                raise AssertionError("unrecognized_source_reference")
        for ref in {ref for members in pool.sets.values() for ref in members}:
            source_ref(ref)
        require(True,'all_distinct_shared_source_references_resolve')
        for entry in labels:
            require_refs = pool.resolve(entry["evidence_id"])
            if not require_refs:
                raise AssertionError("empty_lexical_source_proof")
            cid=entry.get("snomed_id")
            if cid and not terminology.active(cid):
                raise AssertionError("inactive_or_unknown_selected_identifier")
            if entry["kind"]=="Symptom":
                if (cid in terminology.signs or not (set(terminology.ancestor_paths(cid)) & roots)
                        or (cid in terminology.diseases and cid not in roots)):
                    raise AssertionError("symptom_role_has_no_bodhi_root_path:"+str(cid)+":"+entry['label'])
                if not any(ref.startswith('source_row:') for ref in require_refs):
                    raise AssertionError('missing_explicit_bodhi_symptom_role_proof')
                role_path=entry['role_path']
                if (role_path['bodhi_root'] not in roots or
                        terminology.ancestor_paths(cid).get(role_path['bodhi_root']) != role_path['relationship_ids']):
                    raise AssertionError('invalid_bodhi_symptom_ancestry_path')
            if entry['kind']=='Disease' and cid not in terminology.diseases:
                raise AssertionError('disease_is_not_a_source_disorder')
            if entry['kind']=='ExamFinding' and cid not in finding_candidates:
                raise AssertionError('examination_finding_has_no_source_acquisition_or_observation_role')
            if entry['kind']=='ExamMethod' and cid not in methods:
                raise AssertionError('examination_method_is_not_a_source_physical_examination')
            if entry['kind']=='Test' and cid not in tests:
                raise AssertionError('test_is_not_a_source_laboratory_or_imaging_procedure')
            if entry['kind']=='ContextFactor':
                ref=require_refs[0]
                raw=json.loads(connection.execute('SELECT payload FROM source_rows WHERE id=?',(int(ref.split(':')[1]),)).fetchone()[0])
                if raw['type_condition']!='medical_history' or cid is not None or raw['snomed_id']!=entry['referenced_snomed_id']:
                    raise AssertionError('history_record_was_converted_to_an_unconditional_disease_or_official_term')
            if entry["kind"]=="BodySystem":
                direct = {parent for parent,_ in terminology.parents.get(cid,())}
                if "91689009" not in direct or "system" not in terminology.fsns[cid].casefold():
                    raise AssertionError("body_part_misclassified_as_interview_system")
            if entry["korean_label"]:
                row=connection.execute("SELECT * FROM selected_terms WHERE row_id=?",(entry["korean_source"]["source_row_id"],)).fetchone()
                if row is None or row["concept_id"]!=cid or row["language"]!="ko" or unicodedata.normalize("NFC",row["term"])!=entry["korean_label"]:
                    raise AssertionError("korean_source_description_identity_mismatch")
        require(True,"every_lexical_source_identifier_role_path_and_korean_description_checked")
        count=0
        for row in connection.execute("SELECT evidence FROM schema_nodes"):
            evidence=json.loads(row[0])
            if not evidence.get("rule") or not pool.resolve(evidence.get("evidence_id")):
                raise AssertionError("missing_node_derivation_or_source")
            count+=1
        require(count==sum(item["nodes"] for item in report["classes"].values()),"every_node_has_a_resolvable_source_or_derived_proof")
        invalid=connection.execute("""SELECT COUNT(*) FROM schema_edges e LEFT JOIN rf2_components c
            ON c.kind='relationship' AND c.id=substr(e.id,5)
            WHERE e.id LIKE 'rf2:%' AND (c.id IS NULL OR c.active<>'1'
              OR c.row_id IS NOT json_extract(e.evidence,'$.source_row_id')
              OR e.subject<>'http://snomed.info/id/'||c.source_id OR e.predicate<>'http://snomed.info/id/'||c.type_id
              OR json_extract(e.object,'$.relationship_group') IS NOT c.relationship_group
              OR json_extract(e.object,'$.characteristic') IS NOT c.characteristic
              OR json_extract(e.object,'$.concrete_value') IS NOT c.concrete_value
              OR json_extract(e.object,'$.concept') IS NOT 'http://snomed.info/id/'||c.destination_id)""").fetchone()[0]
        require(invalid==0,"rf2_edges_preserve_exact_component_group_type_endpoint_and_concrete_value")
        invalid=connection.execute("""SELECT COUNT(*) FROM schema_edges e LEFT JOIN source_rows r
            ON r.id=json_extract(e.evidence,'$.source_row_id')
            WHERE e.id LIKE 'bodhi-s:%' AND (r.id IS NULL OR e.object<>r.payload)""").fetchone()[0]
        require(invalid==0,"bodhi_edges_preserve_exact_original_payload")
        for row in connection.execute("SELECT evidence FROM schema_edges WHERE status='derived_source_candidate'"):
            evidence=json.loads(row[0])
            if not evidence.get('rule') or not pool.resolve(evidence.get('evidence_id')):
                raise AssertionError('projected_edge_has_no_resolvable_derivation_proof')
        require(True,'every_projected_edge_resolves_shared_source_proof')
        require(connection.execute("SELECT COUNT(*) FROM schema_edges WHERE id LIKE 'bodhi-s:%'").fetchone()[0]==13204,
                "all_five_bodhi_edge_roles_are_retained_without_conversion")
        require(json.loads((ROOT/"submission/knowledge/manifest.json").read_text())["preparation_status"]=="withdrawn_by_D18",
                "source_candidates_do_not_reactivate_old_runtime_admission")
        result={"status":"pass","checks":checks,"check_count":len(checks),"nodes":count,
                "lexical_entries":len(labels),"relations":report["relations"],"classes":report["classes"],
                "network":"none","runtime_admission":"not_run","independent_clinical_validation":"not_run"}
        write(directory/"catalog-verification.json",result)
        return result
    finally:
        database.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",type=Path,required=True)
    result=verify(parser.parse_args().directory)
    print(json.dumps({key:value for key,value in result.items() if key!="checks"},indent=2))
