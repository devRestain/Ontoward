import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "submission"))

from rdflib import Graph
from Dev.ontology.database import file_hash
from Dev.ontology.v5 import write


def verify(directory):
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT / "data/preparation/v5"):
        raise ValueError("Verify only a project-owned source-only base")
    receipt = json.loads((directory / "deletion-receipt.json").read_text())
    reset = json.loads((directory / "reset.json").read_text())
    checks = []
    def require(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
    remaining, replacements = [], []
    for entry in receipt["files"]:
        path = ROOT / entry["path"]
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError("Deletion receipt path leaves the project")
        if path.exists() or path.is_symlink():
            withdrawn = entry["path"] == "submission/knowledge/manifest.json" and path.is_file()
            if (withdrawn and file_hash(path) != entry.get("sha256")
                    and json.loads(path.read_text())["preparation_status"] == "withdrawn_by_D18"):
                replacements.append(entry["path"])
            else:
                remaining.append(entry["path"])
    require(not remaining, "all_receipted_old_data_is_absent_or_explicitly_withdrawn:" + json.dumps(remaining))
    require(len(receipt["files"]) == reset["removed_files"], "deletion_receipt_count_matches_reset")
    require(set(p.name for p in (ROOT / "data/ontology").iterdir()) <= {"schema.ttl", "AGENTS.md", "README.md"},
            "old_schemas_seed_vocabulary_and_approval_receipts_are_absent")
    require(set(p.name for p in (ROOT / "data/preparation").iterdir()) == {"v5"}, "old_preparation_pilots_are_absent")
    require(set(p.name for p in directory.parent.iterdir()) == {directory.name}, "old_v5_previews_batches_texts_and_ledgers_are_absent")
    assets = {p.name for p in (ROOT / "submission/knowledge").iterdir() if p.suffix in {".ttl", ".json"}}
    require(assets == {"schema.ttl", "scoring_policy.json", "reasoning_policy.json", "manifest.json"},
            "previous_runtime_rdf_labels_and_questions_are_absent")
    base = directory / "base"
    require(file_hash(base / "manifest.json") == reset["base_manifest_sha256"], "clean_base_manifest_pin_is_unchanged")
    manifest = json.loads((base / "manifest.json").read_text())
    for name, sha in manifest["assets"].items():
        require(file_hash(base / name) == sha, "unchanged_clean_base_asset:" + name)
    require(manifest["clinical_nodes"] == manifest["clinical_relations"] == len(Graph().parse(base / "vocabulary.ttl")) == 0,
            "saved_v5_base_contains_zero_clinical_nodes_and_relations")
    connection = sqlite3.connect((directory / "ontology.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        counts = {table:connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in
            ("registry", "normalizations", "triples", "patterns", "associations", "source_assertions", "dispositions", "review_batches")}
        require(all(count == 0 for count in counts.values()), "all_eight_old_projection_normalization_and_approval_tables_are_empty")
        require(connection.execute("PRAGMA freelist_count").fetchone()[0] == 0, "sqlite_compaction_leaves_no_free_pages")
        inventory = [dict(row) for row in connection.execute("SELECT * FROM source_files ORDER BY path")]
        require(inventory == receipt["preserved_sources"] == manifest["source_files"], "source_inventory_matches_both_saved_receipts")
        source_rows = connection.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0]
        require(source_rows == sum(source["row_count"] for source in inventory) == reset["source_rows"], "all_preserved_source_rows_are_accounted")
        for source in inventory:
            require(source["complete"] == 1 and file_hash(ROOT / source["path"]) == source["sha256"],
                    "unchanged_source:" + source["path"])
        require(len(inventory) == reset["source_files"] == 109, "all_109_source_files_are_preserved")
    finally:
        connection.close()
    runtime = json.loads((ROOT / "submission/knowledge/manifest.json").read_text())
    require(runtime["preparation_status"] == "withdrawn_by_D18", "old_runtime_admission_is_withdrawn")
    from knowledge.graph import ClinicalKnowledge
    try:
        ClinicalKnowledge.load(ROOT / "submission/knowledge/manifest.json")
    except ValueError as error:
        require("D18" in str(error), "runtime_reader_explicitly_rejects_the_withdrawn_batch")
    else:
        raise AssertionError("Runtime unexpectedly accepted withdrawn knowledge")
    result = {"status":"pass", "checks":checks, "check_count":len(checks), "deleted_files":len(receipt["files"]),
              "remaining_old_files":remaining, "withdrawal_replacements":replacements,
              "absent_receipted_paths":len(receipt["files"])-len(replacements), "cleared_table_rows":counts, "source_files":len(inventory),
              "source_rows":source_rows, "source_hashes":"all_verified", "saved_base_clinical_nodes":0,
              "saved_base_clinical_relations":0, "runtime_admission":"withdrawn_by_D18", "network":"none",
              "sqlite_full_integrity_check":"not_run", "git_history_rewrite":"not_run"}
    write(directory / "reset-verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    print(json.dumps(verify(parser.parse_args().directory), indent=2))
