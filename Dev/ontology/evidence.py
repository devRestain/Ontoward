from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

from .database import file_hash
from .v5 import ROOT, write, workspace_path


def package(directory):
    directory = workspace_path(directory)
    if (directory / "text-assets.json").is_file():
        return package_patient_text(directory)
    manifest = json.loads((directory / "catalog/manifest.json").read_text())
    for name, sha in manifest["generator_files"].items():
        if file_hash(ROOT / "Dev/ontology" / name) != sha:
            raise ValueError("Generator differs from the executed build: " + name)
    files = sorted((ROOT / "Dev/ontology").glob("*.py"))
    files += sorted((ROOT / "Dev/ontology/prompts").glob("*.txt"))
    files += [ROOT / name for name in ("compose.yaml", "Dockerfile", "Dev/codex/Dockerfile", "Dev/codex/environment.py",
        "submission/requirements.txt", "data/ontology/schema.ttl", "submission/knowledge/scoring_policy.json",
        "submission/knowledge/reasoning_policy.json", "Dev/tests/ontology/compose.build.yaml", "Dev/tests/workflow/compose.offline.yaml")]
    files += sorted((ROOT / "Dev/tests/ontology").glob("*.py"))
    files += sorted((ROOT / "submission").rglob("*.py"))
    files += sorted((ROOT / "Dev/tests/workflow").glob("*.py"))
    files += sorted((ROOT / "submission/config").glob("*.txt"))
    files += sorted((ROOT / "submission/config").glob("*.json"))
    files += [ROOT / "submission/.env", ROOT / "DECISION_STATE.md", ROOT / "PRD.md"]
    files += [ROOT / name for name in ("Dev/ontology/README.md", "data/ontology/README.md")]
    files += [directory / name for name in ("report.json", "verification.json", "catalog-verification.json",
        "korean-verification.json", "finding-verification.json", "storage-verification.json", "candidate-workflow.json", "workset-identity.json", "execution-environment.json", "catalog/manifest.json", "catalog/coverage.json",
        "catalog/finding-coverage.json", "catalog/audit.json", "catalog/unresolved-finding-groups.json",
        "korean/report.json", "korean/calls-summary.json") if (directory / name).is_file()]
    reset = directory.parent
    files += [reset / name for name in ("reset.json", "reset-verification.json", "deletion-receipt.json", "base/manifest.json")
              if (reset / name).is_file()]
    files += [reset/'build/storage-compaction.json'] if (reset/'build/storage-compaction.json').is_file() else []
    files += [ROOT/name for name in ('Tmp/d19-verification/tooling/verification.json',
        'Tmp/d19-verification/findings/verification.json','Tmp/d19-verification/workflow/verification.json') if (ROOT/name).is_file()]
    return package_files(directory, files, manifest["build_id"])


def package_patient_text(directory):
    assets = json.loads((directory / "text-assets.json").read_text())
    verification = json.loads((directory / "verification.json").read_text())
    if assets["status"] != "generated_text_ready" or verification["status"] != "pass":
        raise ValueError("Package only completed verified patient text")
    files = sorted((ROOT / "Dev/ontology").glob("*.py"))
    files += sorted((ROOT / "Dev/ontology/prompts").glob("*.txt"))
    files += sorted((ROOT / "Dev/tests/ontology").glob("*.py"))
    files += sorted((ROOT / "submission").rglob("*.py"))
    files += [ROOT / name for name in ("compose.yaml", "Dockerfile", "Dev/codex/Dockerfile",
        "Dev/codex/environment.py", "submission/requirements.txt", "Dev/tests/workflow/compose.offline.yaml",
        "AGENTS.md", "Dev/AGENTS.md", "data/AGENTS.md", "submission/AGENTS.md", "PRD.md", "DECISION_STATE.md")]
    files += [directory / name for name in ("workset.json", "workset-identity.json", "text-assets.json",
        "questions.ko.json", "exam-requests.ko.json", "accepted-review.json", "execution-summary.json",
        "failed-requests.json", "verification.json", "offline-verification.json", "code-custody.json")]
    custody = json.loads((directory / "code-custody.json").read_text())
    for entry in custody["worksets"]:
        path = workspace_path(ROOT / entry["workset"])
        workset = json.loads(path.read_text())
        files.extend(workspace_path(ROOT / name) for name in workset["files"])
        files.extend(workspace_path(ROOT / item["snapshot"]) for item in entry["files"])
        files += [path.parent / name for name in ("workset.json", "workset-identity.json", "authorization.json",
                  "caller-correction.json") if (path.parent / name).is_file()]
        output = directory / "nova" if path == directory / "workset.json" else path.parent / "results"
        files += sorted(output.glob("*.json"))
        files.append(output / "requests.sqlite3")
        with sqlite3.connect(f"file:{output}/requests.sqlite3?mode=ro", uri=True) as ledger:
            requests = [row[0] for row in ledger.execute("SELECT id FROM calls")]
        for ident in requests:
            files += sorted((output / "calls" / ident).glob("*.json"))
    return package_files(directory, files, assets["build_id"])


def package_files(directory, files, build_id):
    files = sorted(set(files))
    hashes = {p.relative_to(ROOT).as_posix():file_hash(p) for p in files if p.is_file() and p.name not in {"evidence.json", "evidence-files.json"}}
    write(directory / "evidence-files.json", {"files":hashes, "build_id":build_id,
          "source_data_included":False, "credentials_included":False, "runtime_admission":"not_run"})
    output = directory / "generation-evidence.zip"
    temporary = output.with_suffix(".zip.tmp")
    with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
        for relative in hashes:
            archive.write(ROOT / relative, relative)
        archive.write(directory / "evidence-files.json", "evidence-files.json")
    temporary.replace(output)
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Evidence archive failed integrity verification")
        if set(archive.namelist()) != set(hashes) | {"evidence-files.json"}:
            raise ValueError("Evidence archive contains unexpected files")
        scratch = ROOT / "Tmp/ontology-v5"
        scratch.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="evidence-verify-", dir=scratch) as extracted:
            archive.extractall(extracted)
            for relative, sha in hashes.items():
                if file_hash(Path(extracted) / relative) != sha:
                    raise ValueError("Extracted evidence differs from source")
            if file_hash(Path(extracted) / "evidence-files.json") != file_hash(directory / "evidence-files.json"):
                raise ValueError("Extracted evidence inventory differs from source")
    result = {"status":"pass", "path":str(output.relative_to(ROOT)), "sha256":file_hash(output),
              "bytes":output.stat().st_size, "files":len(hashes) + 1, "build_id":build_id,
              "verification":"extracted_file_set_and_all_sha256",
              "raw_source_packages":"excluded", "runtime_submission":"not_created"}
    write(directory / "evidence.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    print(json.dumps(package(parser.parse_args().directory), indent=2))
