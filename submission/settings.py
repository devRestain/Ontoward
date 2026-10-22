"""Read packaged public settings without replacing runner credentials."""

import os
import json
from pathlib import Path

ALGORITHM_VERSION = "d50.19"
ROOT = Path(__file__).resolve().parent
SETTING = "ONTOWARD_KNOWLEDGE_MANIFEST"
SETTINGS = {SETTING, 'ONTOWARD_PROMPTS', 'ONTOWARD_TEXTS', 'ONTOWARD_EDUCATION_ENABLED'}
PROMPT_ROUTES = {
    'chief.select',
    'input.initial', 'input.reply', 'input.exam', 'input.repair', 'input.rows_repair', 'input.chief_repair',
    'mapping.select', 'mapping.repair',
    'clinical.rank', 'clinical.decision', 'clinical.action', 'clinical.select', 'clinical.repair',
    'session.Initiation', 'session.ChiefComplaint', 'session.ContextFactor', 'session.DifferentialDiagnosis',
    'plan.tests_treatment', 'plan.disposition_follow_up_education', 'plan.repair',
    'mouth.plan', 'mouth.announcement.disease', 'mouth.announcement.symptom',
    'mouth.response_repair', 'mouth.text_repair',
}


def packaged_settings() -> dict[str, str]:
    settings = {}
    for number, raw in enumerate((ROOT / ".env").read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in SETTINGS or key in settings or not value:
            raise ValueError(f"Invalid or duplicate packaged setting on line {number}")
        settings[key] = value
    if settings.keys() != SETTINGS:
        raise ValueError(f"Packaged .env must define {sorted(SETTINGS)}")
    return settings


def contained_path(value: str, directory: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Asset path must be relative to the submission directory")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT / directory):
        raise ValueError(f"Asset must stay inside submission/{directory}")
    return path


def knowledge_path(value: str) -> Path:
    return contained_path(value, "knowledge")


def configured_path(key: str, directory: str) -> Path:
    return contained_path(os.environ.get(key, packaged_settings()[key]), directory)


def prompt_paths(manifest: Path) -> dict[str, list[Path]]:
    routes = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(routes, dict) or routes.keys() != PROMPT_ROUTES:
        raise ValueError('Prompt manifest must define the runtime task routes')
    result = {}
    for route, parts in routes.items():
        if not isinstance(parts, list) or not parts or any(not isinstance(p, str) for p in parts):
            raise ValueError(f'Invalid prompt modules: {route}')
        result[route] = [contained_path(part, 'config') for part in parts]
    return result


def knowledge_manifest() -> Path:
    return configured_path(SETTING, "knowledge")


def education_enabled() -> bool:
    value = os.environ.get("ONTOWARD_EDUCATION_ENABLED", packaged_settings()["ONTOWARD_EDUCATION_ENABLED"])
    if value not in {"true", "false"}:
        raise ValueError("ONTOWARD_EDUCATION_ENABLED must be true or false")
    return value == "true"
