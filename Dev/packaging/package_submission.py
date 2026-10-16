"""Archive the submission runtime while excluding local guidance and caches."""

import hashlib
import json
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


SOURCE = Path("/submission")
OUTPUT = Path("/output/ontoward-submission.zip")
REQUIRED = {
    "run.py", "settings.py", "nova_sdk.py", "requirements.txt", ".env",
    'workflow/__init__.py',
    'workflow/clinical_reasoner.py',
    'workflow/consultation.py',
    'workflow/doctor.py',
    'workflow/graph.py',
    'workflow/input_interpreter.py',
    'workflow/interview_planner.py',
    'workflow/io/__init__.py',
    'workflow/io/model_client.py',
    'workflow/io/nova_session.py',
    'workflow/io/request_executor.py',
    'workflow/rules/__init__.py',
    'workflow/rules/action.py',
    'workflow/rules/budget.py',
    'workflow/rules/input.py',
    'workflow/rules/limits.py',
    'workflow/rules/submission.py',
    'workflow/runtime.py',
    'workflow/state/__init__.py',
    'workflow/state/interactions.py',
    'workflow/state/models.py',
    'workflow/state/questions.py',
    'workflow/state/usage.py',
    'workflow/submission_writer.py',
    'workflow/text_config.py',
    "knowledge/__init__.py", "knowledge/graph.py", "knowledge/conditions.py", "knowledge/scoring_policy.json", "knowledge/schema.ttl",
}
EXCLUDED = {"AGENTS.md", "README.md", "PROJECT_STATE.md", ".DS_Store"}


def main() -> None:
    sys.path.insert(0, str(SOURCE))
    from settings import SETTING, contained_path, knowledge_path, packaged_settings

    settings = packaged_settings()
    text_files = {contained_path(settings[key], "config").relative_to(SOURCE).as_posix()
                  for key in ("ONTOWARD_PARSER_PROMPT", "ONTOWARD_TEXTS")}
    manifest_path = knowledge_path(settings[SETTING])
    knowledge_files = {manifest_path.relative_to(SOURCE).as_posix()}
    if manifest_path.is_file():
        manifest_data = json.loads(manifest_path.read_text())
        assets = [manifest_data[key] for key in ("schema", "vocabulary", "scoring_policy", "reasoning_policy", "questions", "labels", "plans")
                  if key in manifest_data] + manifest_data.get("bundles", [])
        knowledge_files.update(knowledge_path(asset["path"]).relative_to(SOURCE).as_posix() for asset in assets)
    required = REQUIRED | text_files | knowledge_files
    files = []
    for path in sorted(SOURCE.rglob("*")):
        relative = path.relative_to(SOURCE)
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed: {relative}")
        if not path.is_file():
            continue
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"} or path.name in EXCLUDED:
            continue
        if "\\" in relative.as_posix() or ":" in relative.as_posix():
            raise ValueError(f"Unsafe submission path: {relative}")
        runtime = relative.as_posix() in required or (
            relative.parts[0] in {"workflow", "knowledge"} and path.suffix == ".py"
        )
        knowledge = relative.parts[0] == "knowledge" and path.suffix in {".ttl", ".json"}
        if knowledge and relative.as_posix() not in required:
            continue
        if not (runtime or knowledge):
            raise ValueError(f"Unapproved submission file: {relative}")
        files.append((path, relative.as_posix()))
    names = {name for _, name in files}
    if required - names:
        raise ValueError(f"Missing runtime files: {sorted(required - names)}")
    manifest = knowledge_path(settings[SETTING]).relative_to(SOURCE).as_posix()
    if any(name.startswith("knowledge/") and Path(name).suffix in {".ttl", ".json"}
           and name not in {"knowledge/scoring_policy.json", "knowledge/schema.ttl"} for name in names) and manifest not in names:
        raise ValueError("Knowledge assets require their configured manifest inside submission/knowledge")
    for line in (SOURCE / "requirements.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#") and not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", line):
            raise ValueError("Submission dependencies must use name==version")
    expanded = sum(path.stat().st_size for path, _ in files)
    if len(files) > 5000 or expanded > 500_000_000:
        raise ValueError("Submission exceeds the file-count or expanded-size limit")
    OUTPUT.parent.mkdir(exist_ok=True)
    temporary = OUTPUT.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for path, name in files:
                archive.write(path, name)
        if temporary.stat().st_size > 50_000_000:
            raise ValueError("Submission exceeds the compressed-size limit")
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(names):
                raise ValueError("Submission archive integrity check failed")
        temporary.replace(OUTPUT)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"source": str(SOURCE), "archive": str(OUTPUT), "files": sorted(names),
                      "file_count": len(files), "expanded_bytes": expanded,
                      "compressed_bytes": OUTPUT.stat().st_size,
                      "sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                      "clinical_workflow": "not_run"}, indent=2))


if __name__ == "__main__":
    main()
