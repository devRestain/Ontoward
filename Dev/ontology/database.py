from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .v5 import ROOT, digest, workspace_path


def source_rows(path, *, rf2=False):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t" if rf2 else ",",
                                quoting=csv.QUOTE_NONE if rf2 else csv.QUOTE_MINIMAL)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"Invalid source header: {path}")
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed source row: {path}:{line}")
            yield line, row


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_hash(path):
    path = workspace_path(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def component_kind(path, columns):
    if "definitionStatusId" in columns:
        return "concept"
    if "relationshipGroup" in columns:
        return "relationship"
    if "term" in columns:
        return "text_definition" if "TextDefinition" in path.name else "description"
    if "acceptabilityId" in columns:
        return "language"
    if "sourceEffectiveTime" in columns:
        return "module_dependency"
    if "owlExpression" in columns:
        return "owl"
    return "identifier" if "alternateIdentifier" in columns else "refset"


class DispositionRecords:
    def __init__(self, database):
        self.database = database

    def append(self, record):
        self.database.disposition(record)
        self.database.connection.commit()

    def __iter__(self):
        for row in self.database.connection.execute("SELECT payload FROM dispositions ORDER BY id"):
            yield json.loads(row[0])


class SourceDatabase:
    def __init__(self, path, *, readonly=False):
        self.path = workspace_path(path)
        if readonly:
            self.connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path)
            self.connection.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                PRAGMA cache_size=-32768;
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_files(
                    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, sha256 TEXT NOT NULL,
                    dataset TEXT NOT NULL, release_date TEXT, kind TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0, complete INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS source_rows(
                    id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES source_files(id),
                    line INTEGER NOT NULL, entity_id TEXT NOT NULL, payload TEXT NOT NULL,
                    disposition TEXT NOT NULL DEFAULT 'not_projected',
                    reason TEXT NOT NULL DEFAULT 'source_reference_retained', UNIQUE(file_id,line));
                CREATE TABLE IF NOT EXISTS rf2_components(
                    kind TEXT NOT NULL, id TEXT NOT NULL, effective_time TEXT NOT NULL,
                    active TEXT NOT NULL, module_id TEXT NOT NULL,
                    source_id TEXT, destination_id TEXT, type_id TEXT, characteristic TEXT,
                    relationship_group TEXT, concept_id TEXT, language TEXT, term TEXT,
                    refset_id TEXT, acceptability TEXT, concrete_value TEXT,
                    row_id INTEGER NOT NULL REFERENCES source_rows(id), PRIMARY KEY(kind,id));
                CREATE TRIGGER IF NOT EXISTS reject_same_version_conflict
                    BEFORE UPDATE ON rf2_components
                    WHEN OLD.effective_time=NEW.effective_time AND
                        (SELECT payload FROM source_rows WHERE id=OLD.row_id)<>
                        (SELECT payload FROM source_rows WHERE id=NEW.row_id)
                    BEGIN SELECT RAISE(ABORT,'Conflicting same-version RF2 component'); END;
                CREATE TABLE IF NOT EXISTS registry(uri TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS normalizations(
                    packet_id TEXT PRIMARY KEY, payload TEXT NOT NULL, decision TEXT NOT NULL,
                    reason TEXT, result TEXT, method TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS triples(
                    graph TEXT NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL,
                    object TEXT NOT NULL, PRIMARY KEY(graph,subject,predicate,object));
                CREATE TABLE IF NOT EXISTS patterns(
                    id TEXT PRIMARY KEY, target TEXT NOT NULL, features TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS associations(
                    id TEXT PRIMARY KEY, disease TEXT NOT NULL, pattern TEXT NOT NULL,
                    assessment TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_assertions(
                    association_id TEXT NOT NULL, assertion_index INTEGER NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(association_id,assertion_index));
                CREATE TABLE IF NOT EXISTS dispositions(
                    id INTEGER PRIMARY KEY, row_id INTEGER REFERENCES source_rows(id),
                    decision TEXT NOT NULL, reason TEXT, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_expressions(
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_batches(
                    receipt_sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)
        self.connection.row_factory = sqlite3.Row
        custody = self.meta("source_custody")
        if custody:
            source = workspace_path(ROOT / custody["path"])
            if source == self.path:
                raise ValueError("Source custody cannot reference itself")
            self.connection.execute("ATTACH DATABASE ? AS custody", (source.as_uri() + "?mode=ro",))
            row = self.connection.execute("SELECT value FROM custody.metadata WHERE key='build_id'").fetchone()
            if row is None or json.loads(row[0]) != custody["build_id"]:
                raise ValueError("Shared source custody build changed")
            for table in ("source_files", "source_rows", "rf2_components", "source_expressions", "inactive_rf2_rows"):
                self.connection.execute(f"CREATE TEMP VIEW {table} AS SELECT * FROM custody.{table}")

    def close(self):
        self.connection.close()

    def meta(self, key, default=None):
        row = self.connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.connection.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, json_text(value)))
        self.connection.commit()

    def inventory(self):
        return [dict(row) for row in self.connection.execute("SELECT * FROM source_files ORDER BY path")]

    def import_file(self, path, *, dataset, release_date=None, versions=None):
        path = workspace_path(path)
        relative, sha = path.relative_to(ROOT).as_posix(), file_hash(path)
        prior = self.connection.execute("SELECT * FROM source_files WHERE path=?", (relative,)).fetchone()
        if prior and prior["sha256"] != sha:
            raise ValueError(f"Source changed during build: {relative}")
        if prior and prior["complete"]:
            return
        rf2 = dataset == "SNOMED_CT" and path.suffix == ".txt"
        if path.suffix == ".json":
            records = [(1, json.loads(path.read_text(encoding="utf-8")))]
        elif not rf2 and path.suffix != ".csv":
            records = [(1, {"text":path.read_text(encoding="utf-8")})]
        else:
            records = source_rows(path, rf2=rf2)
        sql = """INSERT INTO rf2_components VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(kind,id) DO UPDATE SET
                    effective_time=excluded.effective_time, active=excluded.active,
                    module_id=excluded.module_id, source_id=excluded.source_id,
                    destination_id=excluded.destination_id, type_id=excluded.type_id,
                    characteristic=excluded.characteristic, relationship_group=excluded.relationship_group,
                    concept_id=excluded.concept_id, language=excluded.language, term=excluded.term,
                    refset_id=excluded.refset_id, acceptability=excluded.acceptability,
                    concrete_value=excluded.concrete_value, row_id=excluded.row_id
                 WHERE excluded.effective_time>=rf2_components.effective_time"""
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO source_files(path,sha256,dataset,release_date,kind) VALUES(?,?,?,?,?)",
                (relative, sha, dataset, release_date, "rf2" if rf2 else path.suffix.lstrip(".")))
            file_id = cursor.lastrowid
            next_id = self.connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM source_rows").fetchone()[0]
            raw_batch, component_batch, count = [], [], 0
            for line, row in records:
                entity = str(row.get("id", row.get("uuid", row.get("snomed_id", row.get("alternateIdentifier", line)))))
                raw_batch.append((next_id, file_id, line, entity, json_text(row)))
                if rf2:
                    date, module, active = row["effectiveTime"], row["moduleId"], row["active"]
                    if (active not in {"0", "1"} or not re.fullmatch(r"\d{8}", date)
                            or module not in versions or date > versions[module] or date > release_date):
                        raise ValueError(f"RF2 row differs from pinned module versions: {relative}:{line}")
                    kind = component_kind(path, row)
                    component_batch.append((kind, entity, date, active, module, row.get("sourceId", row.get("referencedComponentId")),
                        row.get("destinationId"), row.get("typeId"), row.get("characteristicTypeId"),
                        row.get("relationshipGroup"), row.get("conceptId"), row.get("languageCode"),
                        row.get("term"), row.get("refsetId"), row.get("acceptabilityId"), row.get("value"), next_id))
                count += 1
                next_id += 1
                if len(raw_batch) == 5000:
                    self.connection.executemany(
                        "INSERT INTO source_rows(id,file_id,line,entity_id,payload) VALUES(?,?,?,?,?)", raw_batch)
                    self.connection.executemany(sql, component_batch)
                    raw_batch, component_batch = [], []
            self.connection.executemany(
                "INSERT INTO source_rows(id,file_id,line,entity_id,payload) VALUES(?,?,?,?,?)", raw_batch)
            self.connection.executemany(sql, component_batch)
            self.connection.execute("UPDATE source_files SET row_count=?,complete=1 WHERE id=?", (count, file_id))
        print(json_text({"stage": "ingest", "file": relative, "rows": count}), flush=True)

    def index_sources(self):
        self.connection.executescript("""
            CREATE INDEX IF NOT EXISTS rf2_source ON rf2_components(kind,active,source_id,type_id);
            CREATE INDEX IF NOT EXISTS rf2_destination ON rf2_components(kind,active,destination_id,type_id);
            CREATE INDEX IF NOT EXISTS rf2_description ON rf2_components(kind,active,concept_id,language,type_id);
            CREATE INDEX IF NOT EXISTS rf2_term ON rf2_components(kind,active,term);
            CREATE INDEX IF NOT EXISTS source_entity ON source_rows(file_id,entity_id);
            CREATE INDEX IF NOT EXISTS pattern_target ON patterns(target);
            CREATE INDEX IF NOT EXISTS association_disease ON associations(disease);
            CREATE VIEW IF NOT EXISTS inactive_rf2_rows AS
                SELECT row_id,'excluded' AS disposition,'inactive_latest_component' AS reason
                FROM rf2_components WHERE active='0';
        """)
        self.connection.commit()

    def bodhi_rows(self, filename):
        query = """SELECT r.id,r.line,r.payload FROM source_rows r JOIN source_files f ON f.id=r.file_id
                   WHERE f.dataset='bodhi-s' AND f.path LIKE ? ORDER BY r.line"""
        return [(r["id"], r["line"], json.loads(r["payload"]))
                for r in self.connection.execute(query, ("%/" + filename,))]

    def disposition(self, payload, *, row_id=None):
        decision, reason = payload["decision"], payload.get("reason") or ",".join(payload.get("reasons", [])) or None
        self.connection.execute("INSERT INTO dispositions(row_id,decision,reason,payload) VALUES(?,?,?,?)",
                                (row_id, decision, reason, json_text(payload)))
        if row_id:
            state = "projected" if decision == "accepted_preview" else decision
            self.connection.execute("""UPDATE source_rows SET disposition=?,reason=? WHERE id=?
                                       AND disposition<>'projected'""", (state, reason or "v5_source_projection", row_id))

    def expression(self, payload):
        key = digest(payload)
        self.connection.execute('INSERT OR IGNORE INTO source_expressions VALUES(?,?)', (key,json_text(payload)))
        return key

    def audit_reference(self):
        tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        return {"format":"sqlite-source-audit-v1", "database":self.path.relative_to(ROOT).as_posix(),
            "source_custody":self.meta("source_custody"),
            "build_id":self.meta('build_id'), "tables":{name:self.connection.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]
                for name in ('source_files','source_rows','source_expressions','source_assertions','dispositions',
                             'catalog_assertions','schema_nodes','schema_edges','evidence_refs','evidence_sets','inactive_rf2_rows') if name in tables},
            "source_snapshots":self.source_snapshots()}

    def source_snapshots(self):
        composition = self.meta("composition")
        files = self.inventory()
        return [{"dataset": "SNOMED_CT", **composition,
                 "dataset_id": digest([f for f in files if f["dataset"] == "SNOMED_CT"]),
                 "files": [{"path":f["path"],"sha256":f["sha256"],"rows":f["row_count"],
                            "release_date":f["release_date"]} for f in files if f["dataset"]=="SNOMED_CT"]},
                {"dataset":"bodhi-s", "dataset_id":digest([f for f in files if f["dataset"]=="bodhi-s"]),
                 "files":[{"path":f["path"],"sha256":f["sha256"],"rows":f["row_count"]}
                          for f in files if f["dataset"]=="bodhi-s"],
                 "attribution":"Eka Care", "license":"CC BY-NC 4.0"}]

    def save_builder(self, builder):
        from rdflib import RDF
        from .v5 import OW
        with self.connection:
            for table in ("registry", "triples", "patterns", "associations", "source_assertions"):
                self.connection.execute("DELETE FROM " + table)
            self.connection.executemany("INSERT INTO registry VALUES(?,?)",
                [(key,json_text(value)) for key,value in builder.registry.items()])
            for name, graph in (("vocabulary",builder.vocabulary),("clinical",builder.graph)):
                self.connection.executemany("INSERT INTO triples VALUES(?,?,?,?)",
                    ((name,s.n3(),p.n3(),o.n3()) for s,p,o in graph))
            for node in builder.graph.subjects(RDF.type,OW.ClinicalPattern):
                features = sorted(str(f) for f in builder.graph.objects(node,OW.hasFeature))
                self.connection.execute("INSERT INTO patterns VALUES(?,?,?)",
                    (str(node),str(builder.graph.value(node,OW.targets)),json_text(features)))
            for node in builder.graph.subjects(RDF.type,OW.DiseasePatternAssociation):
                disease = next(builder.graph.subjects(OW.hasAssociation,node))
                self.connection.execute("INSERT INTO associations VALUES(?,?,?,?)",
                    (str(node),str(disease),str(builder.graph.value(node,OW.pattern)),json_text(builder.selected[str(node)])))
            self.connection.executemany("INSERT INTO source_assertions VALUES(?,?,?)",
                ((key,index,json_text(value)) for key,values in builder.assertions.items() for index,value in enumerate(values)))

    def builder(self):
        from rdflib.util import from_n3
        from .v5 import PreviewBuilder
        builder = PreviewBuilder()
        builder.conflicts = set(self.meta("projection_conflicts", []))
        builder.registry = {r["uri"]:json.loads(r["payload"]) for r in self.connection.execute("SELECT * FROM registry ORDER BY uri")}
        for row in self.connection.execute("SELECT * FROM triples"):
            graph = builder.vocabulary if row["graph"]=="vocabulary" else builder.graph
            graph.add(tuple(from_n3(row[k]) for k in ("subject","predicate","object")))
        builder.selected = {r["id"]:json.loads(r["assessment"]) for r in self.connection.execute("SELECT * FROM associations")}
        for row in self.connection.execute("SELECT * FROM source_assertions ORDER BY association_id,assertion_index"):
            builder.assertions.setdefault(row["association_id"],[]).append(json.loads(row["payload"]))
        return builder
