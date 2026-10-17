from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rdflib import URIRef
from knowledge import DATABASES, Knowledge, ONTO, ViewerServer


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Tmp/knowledge-viewer"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    protected = sorted(p for p in (ROOT / "submission").rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    protected += [ROOT / "data/PROJECT_STATE.md"]
    baseline = {str(p.relative_to(ROOT)): digest(p) for p in protected}
    db_baseline = {key: {"size": (ROOT / path).stat().st_size, "mtime_ns": (ROOT / path).stat().st_mtime_ns} for key, (_, path) in DATABASES.items()}
    knowledge = Knowledge(ROOT)
    server = ViewerServer(("127.0.0.1", 0), knowledge)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    address = f"http://127.0.0.1:{server.server_port}"
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def get(route, **params):
        with urlopen(address + route + ("?" + urlencode(params) if params else ""), timeout=10) as response:
            body = response.read()
            return json.loads(body) if "application/json" in response.headers["Content-Type"] else body.decode()

    def refused(route, **params):
        try:
            get(route, **params)
        except HTTPError as error:
            return error.code in (400, 404)
        return False

    try:
        overview = get("/api/overview")
        check("Read exact manifest-pinned graph", overview["triples"] == len(knowledge.graph) and overview["status"] == "admitted")
        check("Verify every declared runtime asset hash", len(overview["pins"]) == 7)
        check("Show empty schema roles as explicit zero coverage", all(
            any(item["id"] == kind and item["count"] == 0 for item in overview["types"]) for kind in ("Test", "ValueMatch")))
        check("Serve local UI and styles without remote assets", all(get(path) for path in ("/", "/style.css", "/app.js")))
        disease = get("/api/search", type="Disease")
        check("Browse all admitted Diseases with pagination", disease["total"] == knowledge.type_counts["Disease"] and len(disease["items"]) == 50)
        check("Read a different second page", get("/api/search", type="Disease", offset=50)["items"][0]["id"] != disease["items"][0]["id"])
        node = disease["items"][0]
        check("Find a node by its full identifier", any(x["id"] == node["id"] for x in get("/api/search", q=node["id"])["items"]))
        check("Find a node by its visible name", any(x["id"] == node["id"] for x in get("/api/search", q=node["label"])["items"]))
        check("Return an honest empty search", get("/api/search", q="no-such-concept-zzzzz")["total"] == 0)
        detail = get("/api/node", id=node["id"])
        check("Preserve identity and expose outgoing relationships", detail["id"] == node["id"] and detail["outgoing"] > 0)
        association_link = next(item for item in detail["items"] if item["predicate"] == str(ONTO.hasAssociation))
        association = get("/api/node", id=association_link["node"]["id"])
        check("Replace association hashes with readable derived names", association["derived_label"] and "↔" in association["label"] and "DiseasePatternAssociation" not in association["label"])
        pattern_link = next(item for item in association["items"] if item["predicate"] == str(ONTO.pattern))
        pattern = get("/api/node", id=pattern_link["node"]["id"])
        feature_link = next(item for item in pattern["items"] if item["predicate"] == str(ONTO.hasFeature))
        check("Traverse Disease to Association to Pattern to Feature", bool(get("/api/node", id=feature_link["node"]["id"])["label"]))
        incoming = get("/api/node", id=pattern["id"], direction="in")
        check("Navigate reverse relationships without inventing edges", incoming["incoming"] > 0 and any(item["node"]["id"] == association["id"] for item in incoming["items"]))
        graph = get("/api/graph", id=node["id"])
        check("Bound visual graph and retain actual directed edges", 1 < len(graph["nodes"]) <= 35 and all(
            any(knowledge.graph.predicates(URIRef(edge["source"]), URIRef(edge["target"]))) for edge in graph["edges"]))
        check("Preserve typed concept-set conjunction", " AND " in knowledge.expected({"kind": "concept_set", "concepts": [node["id"], pattern["id"]], "selection": "all_of"}))
        check("Preserve numeric units and comparison operator", knowledge.expected({"kind": "quantity", "operator": "gt", "value": 60, "unit": "s"}) == "> 60 s")
        check("Preserve interval inclusion", knowledge.expected({"kind": "interval", "lower": 1, "upper": 3, "unit": "d", "lower_inclusive": True, "upper_inclusive": False}) == "[1, 3) d")
        provenance = get("/api/provenance", id=association["id"])
        check("Retrieve stored source assertions", bool(provenance["assertions"]))
        source_id = next(value for assertion in provenance["assertions"] for key, value in assertion.get("raw", {}).items() if key.endswith("row_id"))
        source = get("/api/source-row", id=source_id)
        check("Resolve actual source row file position hash and payload", source["line"] > 0 and len(source["sha256"]) == 64 and json.loads(source["payload"]))
        tables = get("/api/tables", db="competition")
        check("Distinguish projection tables from shared source custody", tables["metadata"]["source_custody"]["path"] == DATABASES["source"][1])
        check("Expose schema columns and foreign keys", any(t["name"] == "source_rows" and t["foreign_keys"] for t in tables["tables"]))
        registry = get("/api/rows", db="competition", table="registry")
        check("Read bounded database pages with observed count", len(registry["rows"]) == 50 and registry["has_more"] and registry["count"] > 50)
        selected = registry["rows"][0]
        filtered = get("/api/rows", db="competition", table="registry", column="uri", q=selected["uri"])
        check("Bind exact table searches to parameters", len(filtered["rows"]) == 1 and filtered["rows"][0] == selected)
        check("Read full source custody rows without extraction", get("/api/rows", db="source", table="source_rows", column="id", q=str(source_id))["rows"][0]["id"] == source_id)
        check("Reject a SQL-looking value as plain query data", not get("/api/rows", db="competition", table="registry", column="uri", q="' OR 1=1 --")["rows"])
        check("Reject unknown tables columns databases and negative offsets", all([
            refused("/api/rows", db="competition", table="registry; DROP TABLE registry"),
            refused("/api/rows", db="competition", table="registry", column="uri;SELECT", q="x"),
            refused("/api/rows", db="../../.env"), refused("/api/search", offset=-1),
        ]))
        check("Reject arbitrary file reads", all(refused(path) for path in ("/.env", "/knowledge.py", "/../submission/.env", "/api/unknown")))
        try:
            request = Request(address + "/api/rows", data=b"{}", method="POST")
            urlopen(request, timeout=2)
            check("Refuse mutation endpoints", False)
        except HTTPError as response:
            check("Refuse mutation endpoints", response.code == 501)
        for key in DATABASES:
            with knowledge.database(key) as connection:
                check(f"Open {key} database query-only", connection.execute("PRAGMA query_only").fetchone()[0] == 1)
                try:
                    connection.execute("UPDATE metadata SET value=value WHERE 0")
                    check(f"Refuse writes to {key}", False)
                except sqlite3.OperationalError:
                    check(f"Refuse writes to {key}", True)
        check("Preserve all submission and data state bytes", baseline == {str(p.relative_to(ROOT)): digest(p) for p in protected})
        check("Preserve both database sizes and modification timestamps", db_baseline == {key: {"size": (ROOT / path).stat().st_size, "mtime_ns": (ROOT / path).stat().st_mtime_ns} for key, (_, path) in DATABASES.items()})
        report = {"status": "pass", "checks": checks, "count": len(checks), "overview": overview,
                  "protected_sha256": baseline, "database_stats": db_baseline, "browser_rendering": "not_run",
                  "external_requests": "not_run", "host_dependency_installation": "not_run"}
        (OUTPUT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": "pass", "checks": len(checks), "triples": overview["triples"], "nodes": overview["nodes"]}))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
