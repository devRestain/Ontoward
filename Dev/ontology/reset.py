from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3

from .database import SourceDatabase, file_hash
from .v5 import ROOT, digest, workspace_path, write


def reset(output, reuse_database=None):
    """Remove derived knowledge while retaining only hash-verified source custody."""
    output = workspace_path(output)
    if output.parent != ROOT / "data/preparation/v5" or output.exists():
        raise ValueError("Reset requires a new direct child of data/preparation/v5")
    database_path = workspace_path(reuse_database) if reuse_database else None
    inventory = []
    if database_path:
        database = SourceDatabase(database_path, readonly=True)
        try:
            inventory = database.inventory()
            if not inventory or any(not f["complete"] or file_hash(ROOT / f["path"]) != f["sha256"] for f in inventory):
                raise ValueError("Existing custody differs from supplied source files")
            if database.connection.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0] != sum(f["row_count"] for f in inventory):
                raise ValueError("Existing source custody is incomplete")
        finally:
            database.close()
    targets = [p for p in (ROOT / "data/preparation").iterdir() if p.name != "v5"]
    targets += [p for p in (ROOT / "data/preparation/v5").iterdir()]
    targets += [p for p in (ROOT / "data/ontology").iterdir() if p.name not in {"schema.ttl", "AGENTS.md", "README.md"}]
    targets += [p for p in (ROOT / "submission/knowledge").iterdir()
                if p.suffix in {".ttl", ".json"} and p.name not in {"schema.ttl", "scoring_policy.json", "reasoning_policy.json"}]
    targets += [p for p in (ROOT / "Tmp").iterdir() if p.is_dir()]
    deleted = []
    for target in targets:
        files = sorted(target.rglob("*")) if target.is_dir() else [target]
        for path in files:
            if path.is_symlink():
                deleted.append({"path":path.relative_to(ROOT).as_posix(), "kind":"symlink"})
            elif path.is_file() and path != database_path and not (database_path and str(path).startswith(str(database_path) + "-")):
                deleted.append({"path":path.relative_to(ROOT).as_posix(), "sha256":file_hash(path), "bytes":path.stat().st_size})
    output.mkdir(parents=True)
    write(output / "deletion-receipt.json", {"decision":"D18", "authorization":"user_requested_legacy_and_non_source_derived_data_deletion",
          "files":deleted, "preserved_sources":inventory, "source_packages_modified":False})
    if database_path:
        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.close()
        clean = output / "ontology.sqlite3"
        database_path.rename(clean)
        for suffix in ("-wal", "-shm"):
            companion = Path(str(database_path) + suffix)
            if companion.exists():
                companion.unlink()
        database = SourceDatabase(clean)
        try:
            with database.connection:
                for table in ("metadata", "registry", "normalizations", "triples", "patterns", "associations", "source_assertions", "dispositions", "review_batches"):
                    database.connection.execute("DELETE FROM " + table)
                database.connection.execute("UPDATE source_rows SET disposition='not_projected',reason='source_reference_retained'")
            database.set_meta("reset_decision", "D18")
            database.set_meta("stage", "source_only")
            database.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            # Remove deleted assertions from SQLite free pages as well as active tables.
            database.connection.execute("VACUUM")
            database.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            database.close()
    for target in targets:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
    baseline = output / "base"
    baseline.mkdir()
    for source in (ROOT / "data/ontology/schema.ttl", ROOT / "submission/knowledge/scoring_policy.json", ROOT / "submission/knowledge/reasoning_policy.json"):
        shutil.copyfile(source, baseline / source.name)
    (baseline / "vocabulary.ttl").write_text("@prefix ow: <urn:ontoward:> .\n", encoding="utf-8")
    write(baseline / "manifest.json", {"schema_version":"5.0", "status":"clean_source_only_base", "clinical_nodes":0,
          "clinical_relations":0, "runtime_admission":"not_run", "source_files":inventory,
          "replay":"python -B -m Dev.ontology.source_projection build", "assets":{
              p.name:file_hash(p) for p in sorted(baseline.iterdir()) if p.is_file()}})
    write(ROOT / "submission/knowledge/manifest.json", {"schema_version":"5.0", "preparation_status":"withdrawn_by_D18",
          "reason":"Rebuild source-only knowledge; require new pinned candidate admission before consultation"})
    write(output / "reset.json", {"status":"clean_source_only_base", "removed_files":len(deleted),
          "source_files":len(inventory), "source_rows":sum(f["row_count"] for f in inventory),
          "base_manifest_sha256":file_hash(baseline / "manifest.json"), "runtime_admission":"withdrawn_by_D18"})
    return json.loads((output / "reset.json").read_text())


def main():
    parser = argparse.ArgumentParser(description="Apply the D18 source-only reset inside the project dev container")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-database", type=Path)
    args = parser.parse_args()
    print(json.dumps(reset(args.output, args.reuse_database), indent=2))


if __name__ == "__main__":
    main()
