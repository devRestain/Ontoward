"""Read packaged application settings without replacing runner credentials."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SETTING = "ONTOWARD_KNOWLEDGE_MANIFEST"


def packaged_settings() -> dict[str, str]:
    settings = {}
    for number, raw in enumerate((ROOT / ".env").read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key.strip() != SETTING or key.strip() in settings:
            raise ValueError(f"Invalid or duplicate packaged setting on line {number}")
        value = value.strip()
        if not value:
            raise ValueError(f"Empty packaged setting on line {number}")
        settings[key.strip()] = value
    if SETTING not in settings:
        raise ValueError(f"Packaged .env must define {SETTING}")
    return settings


def knowledge_path(value: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{SETTING} must be relative to the submission directory")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT / "knowledge"):
        raise ValueError(f"{SETTING} must stay inside submission/knowledge")
    return path


def knowledge_manifest() -> Path:
    return knowledge_path(os.environ.get(SETTING, packaged_settings()[SETTING]))
