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
    'workflow/consultation.py',
    'workflow/doctor_mouth.py',
    'workflow/doctor_ear.py',
    'workflow/doctor_brain.py',
    'workflow/io/__init__.py',
    'workflow/model_context.py',
    'workflow/output_types.py',
    'workflow/rules/decision.py',
    'workflow/rules/questions.py',
    'workflow/sessions/__init__.py',
    'workflow/sessions/initiation.py',
    'workflow/sessions/chief_complaint.py',
    'workflow/sessions/context_factor.py',
    'workflow/sessions/differential_diagnosis.py',
    'workflow/sessions/education.py',
    'workflow/io/nova_session.py',
    'workflow/io/request_executor.py',
    'workflow/rules/__init__.py',
    'workflow/rules/action.py',
    'workflow/rules/budget.py',
    'workflow/rules/input.py',
    'workflow/rules/assessment.py',
    'workflow/rules/limits.py',
    'workflow/rules/submission.py',
    'workflow/runtime.py',
    'workflow/state/__init__.py',
    'workflow/state/interactions.py',
    'workflow/state/models.py',
    'workflow/state/evidence.py',
    'workflow/state/questions.py',
    'workflow/state/usage.py',
    'workflow/submission_writer.py',
    'workflow/text_config.py',
    "knowledge/__init__.py", "knowledge/graph.py", "knowledge/conditions.py",
}
EXCLUDED = {"AGENTS.md", "README.md", "PROJECT_STATE.md", ".DS_Store", ".install.lock"}


def main() -> None:
    sys.path.insert(0, str(SOURCE))
    from settings import SETTING, contained_path, knowledge_path, packaged_settings, prompt_paths

    settings = packaged_settings()
    text_files = {contained_path(settings[key], "config").relative_to(SOURCE).as_posix()
                  for key in ('ONTOWARD_PROMPTS', 'ONTOWARD_TEXTS')}
    modules = prompt_paths(contained_path(settings['ONTOWARD_PROMPTS'], 'config'))
    text_files.update(path.relative_to(SOURCE).as_posix() for parts in modules.values() for path in parts)
    manifest_path = knowledge_path(settings[SETTING])
    knowledge_files = {manifest_path.relative_to(SOURCE).as_posix()}
    if not manifest_path.is_file():
        raise ValueError("knowledge_bundle_not_installed")
    manifest_data = json.loads(manifest_path.read_text())
    if set(manifest_data) != {"schema_version", "knowledge_contract", "build_id", "schema", "vocabulary", "clinical", "questions", "guidelines"} or manifest_data["knowledge_contract"] != "v5-enum-1":
        raise ValueError("Invalid knowledge contract")
    for role in ("schema", "vocabulary", "clinical", "questions", "guidelines"):
        asset = manifest_data[role]
        relative = Path(asset["path"])
        path = (manifest_path.parent / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(manifest_path.parent):
            raise ValueError("Knowledge asset escapes its manifest bundle")
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("Knowledge digest mismatch")
        knowledge_files.add(path.relative_to(SOURCE).as_posix())
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
