from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from collections import deque
from pathlib import Path

from .models import digest, workspace_path

IS_A = "116680003"
DUE_TO = "42752001"
ASSOCIATED_WITH = "47429007"
INFERRED = "900000000000011006"
FSN = "900000000000003001"
PREFERRED = "900000000000548007"
INTERNATIONAL_MODULES = {"900000000000207008", "900000000000012004"}
ATTRIBUTE_MAP = {"363698007": "Location", "246112005": "Severity", "263502005": "Course",
                 "272741003": "Laterality"}
FINDING_METHOD = "418775008"
HEADERS = {
    "concept": ("id", "effectiveTime", "active", "moduleId", "definitionStatusId"),
    "description": ("id", "effectiveTime", "active", "moduleId", "conceptId", "languageCode", "typeId", "term", "caseSignificanceId"),
    "relationship": ("id", "effectiveTime", "active", "moduleId", "sourceId", "destinationId", "relationshipGroup", "typeId", "characteristicTypeId", "modifierId"),
    "language": ("id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "acceptabilityId"),
    "dependency": ("id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "sourceEffectiveTime", "targetEffectiveTime"),
    "concrete": ("id", "effectiveTime", "active", "moduleId", "sourceId", "value", "relationshipGroup", "typeId", "characteristicTypeId", "modifierId"),
}


def normalize(term):
    return re.sub(r"\s+", " ", term).strip().casefold()


def display_term(description):
    term = description["term"]
    if description["typeId"] == FSN:
        term = re.sub(r"\s*\([^()]+\)$", "", term)
    return term


def normalize_description(description):
    return normalize(display_term(description))


def import_rf2(input_dir, database, release_date, language_refsets):
    source, destination = workspace_path(input_dir), workspace_path(database)
    if not re.fullmatch(r"\d{8}", release_date) or not language_refsets:
        raise ValueError("Require the release date and explicit English language refsets")
    if not source.is_dir() or destination.exists():
        raise ValueError("Require a local RF2 directory and a new database path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".building")
    if temporary.exists():
        raise ValueError("An unfinished import exists; use a new output path")
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("CREATE TABLE provenance (kind TEXT, id TEXT, effectiveTime TEXT, file TEXT, row_json TEXT)")
        connection.execute("CREATE INDEX provenance_identity ON provenance(kind,id,effectiveTime)")
        connection.execute("CREATE TABLE metadata (value TEXT)")
        for kind, header in HEADERS.items():
            columns = ",".join('"' + name + '" TEXT' for name in header)
            connection.execute(f'CREATE TABLE "{kind}" ({columns}, file TEXT, PRIMARY KEY(id))')
        files, found = [], set()
        for path in sorted(source.rglob("*.txt")):
            workspace_path(path)
            if "Snapshot" not in str(path.relative_to(source)):
                continue
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, delimiter="\t")
                kind = next((name for name, header in HEADERS.items() if tuple(reader.fieldnames or ()) == header), None)
                if kind is None:
                    continue
                suffix = re.search(r"_(\d{8})\.txt$", path.name)
                if suffix and suffix[1] != release_date:
                    raise ValueError("Mixed release filenames do not match the pinned date")
                with path.open("rb") as binary:
                    file_hash = hashlib.file_digest(binary, "sha256").hexdigest()
                count = 0
                for row in reader:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("Malformed RF2 row")
                    if row["active"] not in {"0", "1"} or not re.fullmatch(r"\d{8}", row["effectiveTime"]) or row["effectiveTime"] > release_date:
                        raise ValueError("Require released rows at or before the pinned date")
                    if row["moduleId"] not in INTERNATIONAL_MODULES:
                        raise ValueError("Clinical import accepts only International modules")
                    old = connection.execute(f'SELECT effectiveTime FROM "{kind}" WHERE id=?', (row["id"],)).fetchone()
                    duplicates = connection.execute("SELECT row_json FROM provenance WHERE kind=? AND id=? AND effectiveTime=?",
                                                    (kind, row["id"], row["effectiveTime"])).fetchall()
                    encoded = json.dumps(row, sort_keys=True, ensure_ascii=False)
                    if any(item[0] != encoded for item in duplicates):
                        raise ValueError("Conflicting component rows at the same effective time")
                    connection.execute("INSERT INTO provenance VALUES (?,?,?,?,?)", (kind, row["id"], row["effectiveTime"], file_hash, encoded))
                    if old is None or row["effectiveTime"] > old[0]:
                        values = [row[name] for name in HEADERS[kind]] + [file_hash]
                        placeholders = ",".join("?" for _ in values)
                        connection.execute(f'INSERT OR REPLACE INTO "{kind}" VALUES ({placeholders})', values)
                    count += 1
                found.add(kind)
                files.append({"path": path.relative_to(source).as_posix(), "sha256": file_hash, "kind": kind, "rows": count})
        if not {"concept", "description", "relationship", "language", "dependency"} <= found:
            raise ValueError("Missing required RF2 Snapshot components")
        modules = {row[0] for row in connection.execute("SELECT DISTINCT moduleId FROM concept")}
        dependencies = list(connection.execute('SELECT moduleId,referencedComponentId,sourceEffectiveTime,targetEffectiveTime FROM dependency WHERE active="1"'))
        if not dependencies:
            raise ValueError("Missing active module dependency metadata")
        for origin, target, source_time, target_time in dependencies:
            if origin not in modules or target not in modules or source_time > release_date or target_time > release_date:
                raise ValueError("Unsatisfied International module dependency metadata")
        for kind, fields in (("relationship", ("sourceId", "destinationId", "typeId")),
                             ("description", ("conceptId",)), ("concrete", ("sourceId", "typeId"))):
            for field in fields:
                missing = connection.execute(f'SELECT COUNT(*) FROM "{kind}" r LEFT JOIN concept c ON c.id=r."{field}" WHERE r.active="1" AND c.id IS NULL').fetchone()[0]
                if missing:
                    raise ValueError(f"Missing concept references in {kind}.{field}")
        for refset in language_refsets:
            if not connection.execute('SELECT 1 FROM language l JOIN description d ON d.id=l.referencedComponentId WHERE l.active="1" AND d.active="1" AND d.languageCode="en" AND l.refsetId=? LIMIT 1', (refset,)).fetchone():
                raise ValueError("Missing selected English language refset")
        if not connection.execute('SELECT 1 FROM relationship WHERE active="1" AND characteristicTypeId=? LIMIT 1', (INFERRED,)).fetchone():
            raise ValueError("Missing active inferred relationships")
        connection.execute("CREATE INDEX rel_source_type ON relationship(sourceId,typeId)")
        connection.execute("CREATE INDEX rel_destination_type ON relationship(destinationId,typeId)")
        connection.execute("CREATE INDEX description_concept ON description(conceptId,languageCode)")
        connection.execute("CREATE INDEX language_description ON language(referencedComponentId,refsetId)")
        connection.execute("CREATE TABLE terms (concept_id TEXT, normalized TEXT, description_id TEXT)")
        connection.executemany("INSERT INTO terms VALUES (?,?,?)", ((cid, normalized, did) for cid, term, did, type_id in
                               connection.execute('SELECT conceptId,term,id,typeId FROM description WHERE active="1" AND languageCode="en"')
                               for normalized in sorted({normalize(term), normalize_description({"term": term, "typeId": type_id})})))
        connection.execute("CREATE INDEX terms_lookup ON terms(normalized)")
        metadata = {"edition": "international", "release_date": release_date, "language_refsets": sorted(language_refsets),
                    "modules": sorted(modules), "files": files, "dependencies": dependencies}
        metadata["dataset_id"] = digest(metadata)
        connection.execute("INSERT INTO metadata VALUES (?)", (json.dumps(metadata, sort_keys=True),))
        connection.commit()
    except BaseException:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    temporary.replace(destination)
    return metadata


class RF2:
    def __init__(self, path):
        path = workspace_path(path)
        self.connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.metadata = json.loads(self.connection.execute("SELECT value FROM metadata").fetchone()[0])
        self.dataset_id = self.metadata["dataset_id"]
        self._parents = None
        self._preferred = {row[0] for row in self.connection.execute('SELECT referencedComponentId FROM language WHERE active="1" AND acceptabilityId=? AND refsetId IN (' + ",".join("?" for _ in self.metadata["language_refsets"]) + ")", [PREFERRED, *self.metadata["language_refsets"]])}

    def close(self):
        self.connection.close()

    def active(self, sctid):
        return bool(self.connection.execute('SELECT 1 FROM concept WHERE id=? AND active="1"', (sctid,)).fetchone())

    def descriptions(self, sctid):
        return [dict(row) for row in self.connection.execute('SELECT * FROM description WHERE conceptId=? AND active="1" AND languageCode="en" ORDER BY id', (sctid,))]

    def label(self, sctid):
        descriptions = self.descriptions(sctid)
        item = next((d for d in descriptions if d["id"] in self._preferred), next((d for d in descriptions if d["typeId"] == FSN), None))
        return display_term(item) if item else sctid

    def search(self, term, limit=5):
        normalized = normalize(term)
        exact = [row[0] for row in self.connection.execute('SELECT DISTINCT t.concept_id FROM terms t JOIN concept c ON c.id=t.concept_id WHERE normalized=? AND c.active="1" ORDER BY t.concept_id', (normalized,))]
        if exact:
            return exact
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return [row[0] for row in self.connection.execute('SELECT DISTINCT t.concept_id FROM terms t JOIN concept c ON c.id=t.concept_id WHERE normalized LIKE ? ESCAPE "\\" AND c.active="1" ORDER BY t.concept_id LIMIT ?', ("%" + escaped + "%", limit))]

    def relationships(self, sctid):
        return [dict(row) for row in self.connection.execute('SELECT r.* FROM relationship r JOIN concept c ON c.id=r.destinationId WHERE r.sourceId=? AND r.active="1" AND r.characteristicTypeId=? AND c.active="1" ORDER BY r.id', (sctid, INFERRED))]

    def concrete(self, sctid):
        return [dict(row) for row in self.connection.execute('SELECT * FROM concrete WHERE sourceId=? AND active="1" AND characteristicTypeId=? ORDER BY id', (sctid, INFERRED))]

    @property
    def parents(self):
        if self._parents is None:
            self._parents = {}
            for row in self.connection.execute('SELECT r.* FROM relationship r JOIN concept s ON s.id=r.sourceId JOIN concept d ON d.id=r.destinationId WHERE r.active="1" AND s.active="1" AND d.active="1" AND r.typeId=? AND r.characteristicTypeId=? ORDER BY r.id', (IS_A, INFERRED)):
                self._parents.setdefault(row["sourceId"], []).append(dict(row))
        return self._parents

    def path(self, source, ancestor):
        if not self.active(source) or not self.active(ancestor):
            return None
        queue, visited = deque([(source, [])]), {source}
        while queue:
            node, route = queue.popleft()
            if node == ancestor:
                return route
            for row in self.parents.get(node, []):
                if row["destinationId"] not in visited:
                    visited.add(row["destinationId"])
                    queue.append((row["destinationId"], route + [row]))
        return None

    def descendants(self, roots):
        children = {}
        for source, parents in self.parents.items():
            for row in parents:
                children.setdefault(row["destinationId"], set()).add(source)
        visited, queue = set(roots), deque(sorted(roots))
        while queue:
            for child in sorted(children.get(queue.popleft(), [])):
                if child not in visited:
                    visited.add(child)
                    queue.append(child)
        return sorted(node for node in visited if self.active(node))

    def packet(self, sctid):
        return {"sctid": sctid, "label": self.label(sctid), "descriptions": self.descriptions(sctid),
                "relationships": self.relationships(sctid), "concrete": self.concrete(sctid)}

    def evidence(self, evidence, allowed_ids=None):
        table = evidence.kind
        row = self.connection.execute(f'SELECT * FROM "{table}" WHERE id=? AND active="1"', (evidence.id,)).fetchone()
        if row is None or (allowed_ids is not None and (table, evidence.id) not in allowed_ids):
            raise ValueError("Evidence is absent from this input packet")
        if table == "description":
            if evidence.quote is None or evidence.start is None or evidence.end is None or evidence.end <= evidence.start or row["term"][evidence.start:evidence.end] != evidence.quote:
                raise ValueError("Description evidence must be an exact character span")
        elif any(value is not None for value in (evidence.quote, evidence.start, evidence.end)):
            raise ValueError("Relationship evidence uses row IDs rather than text spans")
        return dict(row)
