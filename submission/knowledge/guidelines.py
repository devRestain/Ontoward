import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re


def relative_document(value):
    if not isinstance(value, str):
        raise ValueError("Invalid guideline path")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts or "\\" in value
            or ":" in value or path.suffix != ".md"):
        raise ValueError("Invalid guideline path")
    return path


class GuidelineLibrary:
    def __init__(self, entries):
        self.entries = entries

    @classmethod
    def load(cls, raw, build_id, disease_ids):
        index = json.loads(raw)
        if index.get("version") != "guideline-runtime-1" or index.get("build_id") != build_id:
            raise ValueError("Guideline index differs from the admitted build")
        rows = index["diseases"]
        entries = {row["disease_id"]: row["selections"] for row in rows}
        if len(entries) != len(rows) or set(entries) != set(disease_ids):
            raise ValueError("Guideline index must cover exactly the admitted Diseases")
        for selections in entries.values():
            if len({s["document_id"] for s in selections}) != len(selections):
                raise ValueError("Require distinct mapped guideline documents")
            for source in selections:
                relative_document(source["path"])
                if (not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
                        or source["relation"] not in {"exact", "broader", "narrower", "related"}
                        or source["evidence_use"] not in {"care_navigation", "background_only"}
                        or not source["scope"].strip()):
                    raise ValueError("Invalid guideline source custody or scope")
        return cls(entries)

    def read(self, disease_id):
        root = Path(os.environ.get("NOVA_GUIDELINES_DIR", "/opt/nova/guidelines")).resolve()
        documents, failures = [], []
        seen = set()
        for source in self.entries.get(disease_id, []):
            if source["path"] in seen:
                continue
            seen.add(source["path"])
            try:
                path = (root / relative_document(source["path"])).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("path_outside_corpus")
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                    raise ValueError("hash_mismatch")
                documents.append({**source, "text": raw.decode("utf-8")})
            except (OSError, UnicodeError, ValueError) as error:
                failures.append({"document_id": source["document_id"], "path": source["path"],
                                 "status": "unavailable", "error": str(error)})
        return documents, failures
