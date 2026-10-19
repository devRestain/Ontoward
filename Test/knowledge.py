from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import parse_qs, urlsplit

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import SKOS


ONTO = Namespace("urn:ontoward:")
DATABASES = {
    "competition": ("Competition mappings", "data/preparation/v5/competition-graph-2026-10-16/ontology.sqlite3"),
    "source": ("Source custody", "data/preparation/v5/source-only-2026-10-16/findings-2026-10-16/ontology.sqlite3"),
}
TYPE_NAMES = {
    "Disease": "질환", "Symptom": "증상", "ExamFinding": "진찰 소견",
    "ClinicalPattern": "임상 패턴", "ClinicalFeature": "패턴 조건",
    "DiseasePatternAssociation": "질환–패턴 연결", "ExpectedValue": "기대값",
    "FindingAttribute": "속성", "AttributeValue": "속성값", "ContextFactor": "맥락 요인",
    "BodySystem": "신체 계통", "ExamMethod": "진찰 방법", "Test": "검사", "ValueMatch": "값 비교 경로",
    "Class": "스키마 클래스", "Property": "관계 정의",
}
RELATION_NAMES = {
    "hasAssociation": "질환의 연결", "pattern": "연결된 패턴", "targets": "대상 소견",
    "hasFeature": "필요한 조건", "onAttribute": "비교 속성", "expected": "기대값",
    "expectedStatus": "기대 상태", "hasAttribute": "관찰 속성", "canHaveValue": "가능한 값",
    "inSystem": "문진 계통", "targetScope": "적용 주체와 시점", "diagnosticEffect": "정성 효과", "applicability": "적용 조건",
    "refinesPattern": "정교화 기준", "detectedBy": "획득 방법", "sourceRef": "원천 참조",
    "valueJSON": "타입이 있는 값",
    "examRequestText": "진찰 요청문",
}


def short(value):
    return str(value).removeprefix(str(ONTO)).rsplit("#", 1)[-1]


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def number(params, key, default=0, maximum=1_000_000):
    value = int(params.get(key, default))
    if not 0 <= value <= maximum:
        raise ValueError(f"Invalid {key}")
    return value


class Knowledge:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.loaded = datetime.now(timezone.utc).isoformat()
        self.graph = Graph()
        self.manifest_path = self.root / "submission/knowledge/manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.is_file() else None
        self.pins = []
        self.questions = {}
        if self.manifest is not None:
            if self.manifest.get("knowledge_contract") != "v5-enum-1":
                raise ValueError("Unsupported knowledge contract")
            for role in ("schema", "vocabulary", "clinical", "questions", "guidelines"):
                self.verify_pin(role, self.manifest[role])
            for pin in self.pins:
                if pin["role"] in {"schema", "vocabulary", "clinical"}:
                    self.graph.parse(self.pinned_path(pin), format="turtle")
            self.questions = json.loads(self.pinned_path(self.manifest["questions"]).read_text())["questions"]
        self.nodes = sorted({str(s) for s in self.graph.subjects() if isinstance(s, URIRef)})
        self.types = {node: sorted(short(t) for t in self.graph.objects(URIRef(node), RDF.type)) for node in self.nodes}
        self.incoming_features = {str(f): str(p) for p, f in self.graph.subject_objects(ONTO.hasFeature)}
        self.association_owners = {str(a): str(d) for d, a in self.graph.subject_objects(ONTO.hasAssociation)}
        self.records = {node: self.brief(node) for node in self.nodes}
        self.search_text = {}
        for node, item in self.records.items():
            labels = [str(v) for predicate in (RDFS.label, SKOS.altLabel) for v in self.graph.objects(URIRef(node), predicate)]
            self.search_text[node] = " ".join([node, item["label"], *labels]).casefold()
        self.type_counts = Counter(t for types in self.types.values() for t in types)
        for kind in TYPE_NAMES:
            self.type_counts.setdefault(kind, 0)

    def pinned_path(self, entry):
        path = (self.manifest_path.parent / entry["path"]).resolve()
        if not path.is_relative_to(self.root / "submission/knowledge"):
            raise ValueError("Manifest path is outside knowledge")
        return path

    def verify_pin(self, role, entry):
        path = self.pinned_path(entry)
        actual = file_hash(path)
        if actual != entry["sha256"]:
            raise ValueError(f"Manifest hash mismatch: {entry['path']}")
        self.pins.append({"role": role, "path": entry["path"], "sha256": actual, "bytes": path.stat().st_size})

    def objects(self, node, predicate):
        return sorted(self.graph.objects(URIRef(node), ONTO[predicate]), key=str)

    @lru_cache(maxsize=None)
    def label(self, node):
        node = str(node)
        labels = list(self.graph.objects(URIRef(node), RDFS.label))
        if labels:
            return str(min(labels, key=lambda x: (0 if x.language == "ko" else 1 if x.language == "en" else 2, str(x))))
        types = self.types.get(node, [])
        if "ExpectedValue" in types:
            values = self.objects(node, "valueJSON")
            return self.expected(json.loads(str(values[0]))) if values else "기대값 (값 없음)"
        if "ClinicalFeature" in types:
            parent = self.incoming_features.get(node)
            targets = self.objects(parent, "targets") if parent else []
            target = self.label(str(targets[0])) if targets else "대상 없음"
            return f"{target} · {self.feature_condition(node)}"
        if "ClinicalPattern" in types:
            targets = self.objects(node, "targets")
            features = self.objects(node, "hasFeature")
            target = self.label(str(targets[0])) if targets else "대상 없음"
            return f"{target} · " + " AND ".join(self.feature_condition(str(f)) for f in features)
        if "DiseasePatternAssociation" in types:
            disease = self.association_owners.get(node)
            patterns = self.objects(node, "pattern")
            return f"{self.label(disease) if disease else '질환 없음'} ↔ {self.label(str(patterns[0])) if patterns else '패턴 없음'}"
        local = short(node)
        if re.search(r"[0-9a-f]{20,}$", local):
            return f"{TYPE_NAMES.get(types[0], types[0]) if types else '이름 없는 항목'} · {local[-8:]}"
        return local

    def feature_condition(self, node):
        attributes = self.objects(node, "onAttribute")
        values = self.objects(node, "expected")
        statuses = self.objects(node, "expectedStatus")
        if attributes and values:
            return f"{self.label(str(attributes[0]))}: {self.label(str(values[0]))}"
        if statuses:
            return "존재" if str(statuses[0]) == "present" else "부재" if str(statuses[0]) == "absent" else str(statuses[0])
        return "조건 없음"

    def expected(self, value):
        kind = value["kind"]
        if kind == "concept":
            text = self.label(value["concept"])
        elif kind == "concept_set":
            join = " OR " if value.get("selection") == "any_of" else " AND "
            text = "(" + join.join(self.label(c) for c in value["concepts"]) + ")"
        elif kind == "quantity":
            operators = {"eq": "=", "ne": "≠", "gt": ">", "ge": "≥", "gte": "≥", "lt": "<", "le": "≤", "lte": "≤"}
            text = f"{operators.get(value.get('operator'), value.get('operator', '='))} {value.get('value')} {value.get('unit', '')}".strip()
        elif kind == "interval":
            lower = value.get("lower") if value.get("lower") is not None else "−∞"
            upper = value.get("upper") if value.get("upper") is not None else "∞"
            text = f"{'[' if value.get('lower_inclusive') else '('}{lower}, {upper}{']' if value.get('upper_inclusive') else ')'} {value.get('unit', '')}".strip()
        else:
            return json.dumps(value, ensure_ascii=False)
        if value.get("match") == "subsumption":
            text += " (하위 개념 포함)"
        return text

    def brief(self, node):
        return {"id": node, "label": self.label(node), "types": self.types.get(node, []),
                "derived_label": not any(self.graph.objects(URIRef(node), RDFS.label))}

    def overview(self):
        return {
            "loaded_at": self.loaded, "build_id": self.manifest["build_id"] if self.manifest else "not_installed",
            "manifest_sha256": file_hash(self.manifest_path) if self.manifest else "not_installed", "status": "installed" if self.manifest else "knowledge_bundle_not_installed",
            "triples": len(self.graph), "nodes": len(self.nodes),
            "types": [{"id": k, "label": TYPE_NAMES.get(k, k), "count": v} for k, v in sorted(self.type_counts.items())],
            "pins": self.pins,
            "databases": [{"id": key, "label": label, "path": path,
                           "available": (self.root / path).is_file(),
                           "bytes": (self.root / path).stat().st_size if (self.root / path).is_file() else None}
                          for key, (label, path) in DATABASES.items()],
        }

    def search(self, params):
        query = params.get("q", "").strip().casefold()
        kind = params.get("type", "")
        tokens = query.split()
        matches = [node for node in self.nodes if (not kind or kind in self.types[node]) and
                   all(token in self.search_text[node] for token in tokens)]
        matches.sort(key=lambda node: (self.label(node).casefold() != query,
                                     not self.label(node).casefold().startswith(query), self.label(node).casefold(), node))
        offset = number(params, "offset")
        return {"total": len(matches), "items": [self.records[n] for n in matches[offset:offset + 50]]}

    def node(self, params):
        node = params.get("id", "")
        if node not in self.records:
            raise ValueError("Unknown graph node")
        uri = URIRef(node)
        labels = [{"text": str(v), "language": v.language, "kind": short(p)}
                  for p in (RDFS.label, SKOS.altLabel) for v in self.graph.objects(uri, p)]
        literals = [{"predicate": str(p), "relation": RELATION_NAMES.get(short(p), short(p)),
                     "value": str(v), "language": v.language, "datatype": str(v.datatype) if v.datatype else None}
                    for p, v in sorted(self.graph.predicate_objects(uri), key=lambda x: (str(x[0]), str(x[1])))
                    if isinstance(v, Literal) and p not in (RDFS.label, SKOS.altLabel)]
        outgoing = [(str(p), str(v)) for p, v in self.graph.predicate_objects(uri) if isinstance(v, URIRef)]
        incoming = [(str(p), str(s)) for s, p in self.graph.subject_predicates(uri)]
        direction = params.get("direction", "out")
        if direction not in {"in", "out"}:
            raise ValueError("Invalid direction")
        all_links = outgoing if direction == "out" else incoming
        predicate = params.get("predicate", "")
        links = sorted((p, n) for p, n in all_links if not predicate or p == predicate)
        offset = number(params, "offset")
        return {**self.records[node], "labels": labels, "literals": literals,
                "question": self.questions.get(node), "outgoing": len(outgoing), "incoming": len(incoming),
                "predicates": [{"id": p, "label": RELATION_NAMES.get(short(p), short(p)), "count": count}
                               for p, count in sorted(Counter(p for p, _ in all_links).items())],
                "total": len(links), "items": [{"predicate": p, "relation": RELATION_NAMES.get(short(p), short(p)),
                                               "node": self.records.get(n, self.brief(n))} for p, n in links[offset:offset + 50]]}

    def neighborhood(self, params):
        node = params.get("id", "")
        if node not in self.records:
            raise ValueError("Unknown graph node")
        predicates = {ONTO[x] for x in ("hasAssociation", "pattern", "targets", "hasFeature", "expected", "onAttribute",
                                      "hasAttribute", "canHaveValue", "inSystem", "refinesPattern", "detectedBy")}
        edges = set()
        seen = {node}
        frontier = [(node, "both")]
        truncated = False
        for _ in range(3):
            following = []
            for current, direction in frontier:
                candidates = []
                if direction in {"both", "in"}:
                    candidates += [(str(p), str(s), current) for s, p in self.graph.subject_predicates(URIRef(current)) if p in predicates]
                if direction in {"both", "out"}:
                    candidates += [(str(p), current, str(v)) for p, v in self.graph.predicate_objects(URIRef(current)) if p in predicates and isinstance(v, URIRef)]
                candidates.sort(key=lambda x: (x[0], self.label(x[1]), self.label(x[2]), x))
                # Keep each neighborhood readable; complete relationships remain paginated in the inspector.
                if len(candidates) > 10:
                    truncated = True
                for predicate, source, target in candidates[:10]:
                    other = target if source == current else source
                    if other not in seen and len(seen) >= 35:
                        truncated = True
                        continue
                    edges.add((source, predicate, target))
                    if other not in seen:
                        seen.add(other)
                        following.append((other, "out" if source == current else "in"))
            frontier = following
        return {"nodes": [self.records.get(n, self.brief(n)) for n in sorted(seen)],
                "edges": [{"source": s, "target": t, "label": RELATION_NAMES.get(short(p), short(p))} for s, p, t in sorted(edges)],
                "truncated": truncated, "focus": node}

    @contextmanager
    def database(self, key):
        if key not in DATABASES:
            raise ValueError("Unknown database")
        path = (self.root / DATABASES[key][1]).resolve()
        if not path.is_file():
            raise ValueError("Database is unavailable")
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        try:
            yield connection
        finally:
            connection.close()

    def tables(self, params):
        key = params.get("db", "competition")
        with self.database(key) as connection:
            tables = []
            for name, sql in connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                quoted = '"' + name.replace('"', '""') + '"'
                columns = [dict(row) for row in connection.execute(f"PRAGMA table_info({quoted})")]
                foreign_keys = [dict(row) for row in connection.execute(f"PRAGMA foreign_key_list({quoted})")]
                tables.append({"name": name, "columns": columns, "foreign_keys": foreign_keys, "sql": sql})
            metadata = {row[0]: json.loads(row[1]) for row in connection.execute("SELECT key,value FROM metadata WHERE key IN ('build_id','source_custody','schema_version','normalization_version')")}
            return {"tables": tables, "metadata": metadata}

    def rows(self, params):
        key = params.get("db", "competition")
        table = params.get("table", "registry")
        with self.database(key) as connection:
            allowed = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if table not in allowed:
                raise ValueError("Unknown table")
            quoted = '"' + table.replace('"', '""') + '"'
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quoted})")]
            column, query = params.get("column", ""), params.get("q", "")
            where, arguments = "", []
            if query:
                if column not in columns:
                    raise ValueError("Select a search column")
                field = '"' + column.replace('"', '""') + '"'
                mode = params.get("mode", "exact")
                if mode == "exact":
                    where, arguments = f" WHERE {field} = ?", [query]
                elif mode == "contains":
                    where, arguments = f" WHERE instr(CAST({field} AS TEXT), ?) > 0", [query]
                else:
                    raise ValueError("Invalid search mode")
            offset = number(params, "offset")
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {quoted}{where} LIMIT 51 OFFSET ?", [*arguments, offset])]
            count = None
            if not where and offset == 0:
                try:
                    count = connection.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
                except sqlite3.OperationalError:
                    pass
            node_refs = {value: self.records[value] for row in rows[:50] for value in row.values()
                         if isinstance(value, str) and value in self.records}
            return {"columns": columns, "rows": rows[:50], "has_more": len(rows) > 50, "count": count,
                    "offset": offset, "node_refs": node_refs}

    def source_row(self, params):
        row_id = number(params, "id", maximum=100_000_000)
        with self.database("source") as connection:
            row = connection.execute("SELECT r.*, f.path, f.sha256, f.dataset FROM source_rows r JOIN source_files f ON f.id=r.file_id WHERE r.id=?", (row_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown source row")
            return dict(row)

    def provenance(self, params):
        node = params.get("id", "")
        if node not in self.records:
            raise ValueError("Unknown graph node")
        try:
            with self.database("competition") as connection:
                registry = connection.execute("SELECT payload FROM registry WHERE uri=?", (node,)).fetchone()
                assertions = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM source_assertions WHERE association_id=? ORDER BY assertion_index", (node,))]
                return {"registry": json.loads(registry[0]) if registry else None, "assertions": assertions}
        except ValueError:
            return {"registry": None, "assertions": [], "unavailable": True}


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, knowledge):
        self.knowledge = knowledge
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        params = {k: values[-1] for k, values in parse_qs(url.query, keep_blank_values=True).items()}
        routes = {"overview": self.server.knowledge.overview, "search": self.server.knowledge.search,
                  "node": self.server.knowledge.node, "graph": self.server.knowledge.neighborhood,
                  "tables": self.server.knowledge.tables, "rows": self.server.knowledge.rows,
                  "source-row": self.server.knowledge.source_row, "provenance": self.server.knowledge.provenance}
        try:
            if url.path.startswith("/api/"):
                method = routes.get(url.path.removeprefix("/api/"))
                if method is None:
                    self.send(404, b'{"error":"Unknown endpoint"}', "application/json")
                    return
                value = method() if url.path == "/api/overview" else method(params)
                self.send(200, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return
            files = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"),
                     "/app.js": ("app.js", "text/javascript")}
            if url.path not in files:
                self.send(404, b"Not found", "text/plain")
                return
            name, content_type = files[url.path]
            self.send(200, (Path(__file__).with_name("knowledge") / name).read_bytes(), content_type + "; charset=utf-8")
        except (ValueError, sqlite3.OperationalError) as error:
            message = "조회 시간이 2초를 넘었습니다. ID나 원천 파일 번호로 범위를 좁혀 주세요." if "interrupted" in str(error) else str(error)
            self.send(400, json.dumps({"error": message}, ensure_ascii=False).encode(), "application/json; charset=utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    knowledge = Knowledge(args.root)
    print(f"Read-only knowledge viewer: {len(knowledge.graph)} triples; {len(knowledge.nodes)} nodes", flush=True)
    ViewerServer((args.host, args.port), knowledge).serve_forever()


if __name__ == "__main__":
    main()
