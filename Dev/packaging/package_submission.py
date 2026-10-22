"""Archive the submission runtime while excluding local guidance and caches."""

import ast
import hashlib
from importlib.util import resolve_name
import json
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


SOURCE = Path("/submission")
OUTPUT = Path("/output/ontoward-submission.zip")
REQUIRED = {
    "run.py", "settings.py", "nova_sdk.py", "requirements.txt", ".env",
    "workflow/__init__.py", "workflow/runtime.py",
    "knowledge/__init__.py", "knowledge/graph.py",
}
EXCLUDED = {"AGENTS.md", "README.md", "PROJECT_STATE.md", ".DS_Store", ".install.lock"}


def validate_runtime(files) -> None:
    """Check current local imports instead of maintaining a stale module inventory."""
    modules = {}
    for path, name in files:
        if path.suffix == ".py":
            parts = list(Path(name).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            modules[".".join(parts)] = (path, name)
    roots = {module.split(".")[0] for module in modules}
    for module, (path, name) in modules.items():
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        parent = module.rpartition(".")[0]
        while parent:
            if parent not in modules or modules[parent][0].name != "__init__.py":
                raise ValueError(f"Missing runtime package: {parent} imported by {name}")
            parent = parent.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=name)):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = "." * node.level + (node.module or "")
                imports = [resolve_name(imported, package) if node.level else imported]
            else:
                continue
            for imported in imports:
                if imported.split(".")[0] in roots and imported not in modules:
                    raise ValueError(f"Missing runtime module: {imported} imported by {name}")


def main(source: Path = SOURCE, output: Path = OUTPUT) -> None:
    sys.path.insert(0, str(source))
    from settings import ALGORITHM_VERSION, SETTING, contained_path, knowledge_path, packaged_settings, prompt_paths

    settings = packaged_settings()
    text_files = {contained_path(settings[key], "config").relative_to(source).as_posix()
                  for key in ('ONTOWARD_PROMPTS', 'ONTOWARD_TEXTS')}
    modules = prompt_paths(contained_path(settings['ONTOWARD_PROMPTS'], 'config'))
    text_files.update(path.relative_to(source).as_posix() for parts in modules.values() for path in parts)
    manifest_path = knowledge_path(settings[SETTING])
    knowledge_files = {manifest_path.relative_to(source).as_posix()}
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
        knowledge_files.add(path.relative_to(source).as_posix())
    required = REQUIRED | text_files | knowledge_files
    files = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
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
    validate_runtime(files)
    for line in (source / "requirements.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#") and not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", line):
            raise ValueError("Submission dependencies must use name==version")
    expanded = sum(path.stat().st_size for path, _ in files)
    if len(files) > 5000 or expanded > 500_000_000:
        raise ValueError("Submission exceeds the file-count or expanded-size limit")
    file_hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for path, name in files}
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for path, name in files:
                archive.write(path, name)
        if temporary.stat().st_size > 50_000_000:
            raise ValueError("Submission exceeds the compressed-size limit")
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(names):
                raise ValueError("Submission archive integrity check failed")
            if any(hashlib.sha256(archive.read(name)).hexdigest() != digest
                   for name, digest in file_hashes.items()):
                raise ValueError("Submission source changed during packaging")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"source": str(source), "archive": str(output), "files": sorted(names),
                      "algorithm_version": ALGORITHM_VERSION, "knowledge_build_id": manifest_data["build_id"],
                      "file_sha256": file_hashes,
                      "file_count": len(files), "expanded_bytes": expanded,
                      "compressed_bytes": output.stat().st_size,
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "clinical_workflow": "not_run"}, indent=2))


if __name__ == "__main__":
    main()
