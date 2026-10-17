from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import urllib.error
import uuid

from Dev.education.prepare import (
    CATALOG_FIELDS, GUIDANCE, ROOT, document, inside, json_bytes,
    normalized, runtime_inputs, sha256, source_path, write,
)
from Dev.ontology.database import SourceDatabase
from Dev.ontology.source_projection import SnapshotSources


VERSION = "guideline-mapping-1"
MODEL = "openai/gpt-6-luna"
ORIGIN = "https://nova.snubhai.org"
FIELDS = ("tests", "treatment", "disposition", "follow_up", "education")
RELATIONS = {"exact", "broader", "narrower", "related"}
ROLES = {"clinical_guidance", "clinician_textbook", "evidence_review", "patient_information", "clinical_summary"}
STOP = set("a an the of to and or in on for with without disease diseases disorder disorders syndrome clinical practice guideline guidelines treatment management diagnosis unspecified other associated complication complications".split())
SEARCH_STOP = STOP | set("care adult adults evaluation evaluate assessment diagnostic emergency suspected evidence guidance recommendations clinician general population".split())
HEADINGS = {
    "tests": r"evaluat|diagnos|investigat|work.?up|assessment|검사|평가|진단",
    "treatment": r"treat|manage|therap|intervention|치료|관리|처치",
    "disposition": r"refer|admi[st]|hospital|emergen|triage|disposition|surg|의뢰|입원|응급|수술",
    "follow_up": r"follow|monitor|prognos|complication|warning|추적|예후|경과|합병|주의",
    "education": r"educat|patient.*inform|prevention|deterren|counsel|self.?care|교육|예방|상담|자가",
}
DATABASE = "data/preparation/v5/competition-graph-2026-10-16/ontology.sqlite3"
GUIDANCE_FILES = {"README.md", "AGENTS.md", "PROJECT_STATE.md"}


def output_directory(root: Path, value: str | Path) -> Path:
    path = inside(root, value)
    if not any(path.is_relative_to(root / base) for base in ("data/preparation/guideline-mapping", "Tmp")):
        raise ValueError("Mapping output must stay in data/preparation/guideline-mapping or Tmp")
    return path


def load(path):
    return json.loads(path.read_bytes())


def save(path, value):
    write(path, json_bytes(value))


def read_lines(root, source):
    raw = source_path(root, source["path"]).read_bytes()
    if sha256(raw) != source["sha256"]:
        raise ValueError(f"Source changed: {source['path']}")
    return raw, raw.decode("utf-8").splitlines()


def excluded(source):
    title = source["title"].casefold()
    return (any(s in title for s in ("(nursing)", "(archived)", "[archived]", "veterinary", "in dogs", "in cats"))
            or bool(re.match(r"^(?:anatomy|physiology|embryology|histology|neuroanatomy)[,:]", title)))


def source_role(source):
    if source["document_type"] in GUIDANCE:
        return "guidance_catalog_candidate"
    if source["document_type"] == "질환 개요(교과서)":
        return "clinician_textbook"
    if source["document_type"] == "근거 리뷰":
        return "evidence_review"
    if "일반인" in source["document_type"]:
        return "patient_information"
    return "summary_or_other"


def sections(raw):
    try:
        metadata, lines, headings = document(raw)
        return metadata, headings, None
    except (ValueError, json.JSONDecodeError) as error:
        return {}, [], str(error)


def aliases_from_database(root, diseases, database):
    db = SourceDatabase(inside(root, database), readonly=True)
    try:
        identity = {"path": str(Path(database)), "build_id": db.meta("build_id"),
                    "source_custody": db.meta("source_custody")}
        registry = {r["uri"]: json.loads(r["payload"]) for r in db.connection.execute("SELECT uri,payload FROM registry")}
        if {u for u, r in registry.items() if r.get("kind") == "Disease"} != {d["id"] for d in diseases}:
            raise ValueError("Database and admitted Disease sets differ")
        for disease in diseases:
            entry = registry.get(disease["id"], {})
            snomed = entry.get("snomed_id") or disease["id"].removeprefix("urn:ontoward:SnomedCT")
            rows = sorted((dict(r) for r in db.connection.execute(
                "SELECT id,term,language,row_id FROM rf2_components WHERE kind='description' AND active='1' AND concept_id=? AND language IN ('en','ko')", (snomed,))), key=lambda r: r["id"])
            disease["source_aliases"] = rows
            disease["aliases"] = sorted(set(disease["aliases"]) | {
                re.sub(r"\s*\((?:disorder|finding)\)$", "", r["term"]) for r in rows})
        return identity
    finally:
        db.close()


def create_index(root, sources, index_path):
    db = sqlite3.connect(index_path)
    db.execute("CREATE VIRTUAL TABLE search USING fts5(title,body,content='',tokenize='unicode61')")
    for i, source in enumerate(sources, 1):
        raw = source_path(root, source["path"]).read_bytes()
        if sha256(raw) != source["sha256"]:
            raise ValueError("Source changed while indexing")
        db.execute("INSERT INTO search(rowid,title,body) VALUES (?,?,?)",
                   (i, normalized(source["title"]), normalized(raw.decode("utf-8"))))
    db.commit()
    return db


def search_token(word):
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 5 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("ies"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("s"):
        word = word[:-1]
    return '"' + word + '"' + ('*' if len(word) >= 4 else '')


def retrieve(db, sources, disease, *, search_terms=(), limit=10):
    names = {normalized(n) for n in [*disease["aliases"], *search_terms] if len(normalized(n)) >= 4}
    names = sorted(names, key=lambda s: (len(s.split()), s))[:35]
    scores = {}
    queries = [" OR ".join('"' + n + '"' for n in names)]
    tokens = sorted({t for n in names for t in n.split() if t not in STOP and len(t) > 2})
    if tokens:
        queries.append(" OR ".join(search_token(t) for t in tokens))
    for term in [*disease["aliases"], *search_terms]:
        words = [w for w in normalized(term).split() if len(w) > 2 and w not in SEARCH_STOP][:6]
        if words:
            queries.append(" AND ".join(search_token(w) for w in words))
    for qi, query in enumerate(queries):
        if not query:
            continue
        for rowid, rank in db.execute("SELECT rowid,bm25(search,10.0,1.0) AS rank FROM search WHERE search MATCH ? ORDER BY rank,rowid LIMIT 100", (query,)):
            source = sources[rowid - 1]
            if excluded(source):
                continue
            score = -rank + (30 if qi == 0 else 45 if qi >= 2 else 0)
            title = normalized(source["title"])
            if title in names:
                score += 200
            elif any(len(n) > 4 and f" {n} " in f" {title} " for n in names):
                score += 80
            scores[rowid] = max(scores.get(rowid, 0), score)
    ranked = sorted(scores, key=lambda i: (-scores[i], sources[i - 1]["path"]))
    # Reserve space for guidance without displacing all high-identity textbooks.
    guidance = [i for i in ranked if sources[i - 1]["document_type"] in GUIDANCE][:4]
    chosen = list(dict.fromkeys([*ranked[:limit - 4], *guidance, *ranked]))[:limit]
    return [(sources[i - 1], round(scores[i], 5)) for i in chosen]


def packet(root, disease, matches, *, search_terms=()):
    candidates = []
    names = [normalized(n) for n in [*disease["aliases"], *search_terms] if len(normalized(n)) >= 4]
    generic = SEARCH_STOP | {"congenital", "internal", "protein", "deficiency", "left", "right", "proper", "region", "type"}
    tokens = {w for n in names for w in n.split() if len(w) >= 3 and w not in generic}
    for source, score in matches:
        raw, lines = read_lines(root, source)
        meta, headings, parse_error = sections(raw)
        evidence = []
        for number, line in enumerate(lines, 1):
            if number <= 9 or not line.strip() or line.lstrip().startswith("#"):
                continue
            text = normalized(line)
            exact = any(f" {n} " in f" {text} " for n in names)
            overlap = len(tokens & set(text.split()))
            if exact or overlap:
                # References are not disease-care evidence; rank early body above citations.
                reference = bool(re.match(r"^\s*(?:\d+\.|\[\d+\])", line)) or 'pubmed' in line.casefold()
                care = bool(re.search(r"treat|manag|therap|diagnos|evaluat|surg|치료|진단|검사|관리", line, re.I))
                distinctive = sum(3 if len(w) >= 10 or any(c.isdigit() for c in w) else 1 for w in tokens & set(text.split()))
                evidence.append(((not exact, reference, not care, -distinctive, -overlap, number), number, line))
        best = sorted(evidence)[:2]
        chosen = {n: text for _, n, text in best}
        intro = next(((n, text) for n, text in enumerate(lines, 1)
                      if n > 10 and len(text.strip()) > 80 and not text.lstrip().startswith("#")), None)
        if intro and intro[0] not in chosen:
            chosen[intro[0]] = intro[1]
        evidence_lines = []
        for n, text in sorted(chosen.items()):
            positions = [text.casefold().find(a.casefold()) for a in disease["aliases"] if len(a) >= 4]
            position = min((p for p in positions if p >= 0), default=0)
            anchors = [(3 if len(w) >= 10 or any(c.isdigit() for c in w) else 1, text.casefold().find(w))
                       for w in tokens if text.casefold().find(w) >= 0]
            if not any(p >= 0 for p in positions) and anchors:
                position = min(anchors, key=lambda pair: (-pair[0], pair[1]))[1]
            start = max(0, position - 180)
            evidence_lines.append({"line": n, "column_start": start, "text": text[start:start + 800]})
        relevant = [{"title": h["title"], "start_line": h["start_line"], "candidate_fields": [field for field, pattern in HEADINGS.items()
                     if re.search(pattern, h["title"], re.I)]} for h in headings]
        relevant = [h for h in relevant if h["candidate_fields"]][:10]
        candidates.append({"document_id": source["document_id"], "path": source["path"],
                           "title": source["title"], "organization": source["organization"],
                           "year": source["year"], "document_type": source["document_type"],
                           "role": source_role(source), "retrieval_score": score,
                           "language": meta.get("language"), "parse_error": parse_error,
                           "evidence": evidence_lines, "plan_sections": relevant})
    return {"disease_id": disease["id"], "labels": disease["labels"],
            "aliases": disease["aliases"], "candidates": candidates}


def prepare(root, output, *, database=DATABASE, candidate_count=10):
    output = output_directory(root, output)
    output.mkdir(parents=True, exist_ok=False)
    runtime, diseases = runtime_inputs(root)
    source_database = aliases_from_database(root, diseases, database)
    manifest = load(root / runtime["path"])
    if source_database["build_id"] != manifest["build_id"]:
        raise ValueError("Alias database does not match the admitted graph build")
    catalog = root / "assets/guidelines/catalog.csv"
    raw = catalog.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != list(CATALOG_FIELDS):
        raise ValueError("Unexpected catalog columns")
    sources, seen = [], set()
    for i, row in enumerate(reader, 1):
        source = {name: row[key] for key, name in CATALOG_FIELDS.items()}
        if source["path"] in seen:
            raise ValueError("Duplicate catalog source")
        seen.add(source["path"])
        source.update(document_id=f"G{i:05d}", sha256=sha256(source_path(root, source["path"]).read_bytes()))
        sources.append(source)
    protected = {p.relative_to(root).as_posix(): sha256(p.read_bytes())
                 for p in sorted((root / "submission").rglob("*"))
                 if p.is_file() and "__pycache__" not in p.parts and p.name not in GUIDANCE_FILES}
    inventory = {"version": VERSION, "runtime": runtime, "source_database": source_database,
                 "catalog": {"path": "assets/guidelines/catalog.csv", "sha256": sha256(raw)},
                 "diseases": diseases, "sources": sources, "protected_submission": protected,
                 "candidate_count": candidate_count, "status": "preparation_only"}
    save(output / "inventory.json", inventory)
    index_path = output_directory(root, root / f"Tmp/guideline-mapping/{output.name}-index.sqlite3")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        raise ValueError("Use a fresh Tmp/guideline-mapping index path")
    db = create_index(root, sources, index_path)
    try:
        with (output / "candidates.jsonl").open("w", encoding="utf-8") as stream:
            for i, disease in enumerate(diseases, 1):
                entry = packet(root, disease, retrieve(db, sources, disease, limit=candidate_count))
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if i % 100 == 0:
                    print(json.dumps({"prepared": i, "total": len(diseases)}), flush=True)
    finally:
        db.close()
    summary = {"diseases": len(diseases), "documents": len(sources),
               "groups": dict(Counter(s["path"].split('/')[0] for s in sources)),
               "types": dict(Counter(s["document_type"] for s in sources)),
               "inventory_sha256": sha256((output / "inventory.json").read_bytes()),
               "index_path": index_path.relative_to(root).as_posix(),
               "candidates_sha256": sha256((output / "candidates.jsonl").read_bytes())}
    save(output / "preparation.json", summary)
    return summary


def validate_response(content, packets):
    value = json.loads(content)
    entries = value.get("items") if isinstance(value, dict) else None
    expected = {p["disease_id"]: p for p in packets}
    pool = {}
    for packet in packets:
        for source in packet["candidates"]:
            pool.setdefault(source["document_id"], []).append(source)
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ValueError("Response must contain every supplied disease")
    seen = set()
    for entry in entries:
        disease_id = entry.get("disease_id")
        if disease_id not in expected or disease_id in seen:
            raise ValueError("Duplicate or foreign disease ID")
        seen.add(disease_id)
        selections = entry.get("selections")
        if not isinstance(selections, list) or len(selections) > 3:
            raise ValueError("Select at most three documents")
        preferred = {d["document_id"]: d for d in expected[disease_id]["candidates"]}
        selected = set()
        for selection in selections:
            key = selection.get("document_id")
            if key not in pool or key in selected:
                raise ValueError("Duplicate or unprovided document ID")
            selected.add(key)
            if selection.get("relation") not in RELATIONS:
                raise ValueError("Invalid coverage relation")
            if selection.get("document_role") not in ROLES:
                raise ValueError("Invalid assessed document role")
            if "evidence_id" in selection:
                evidence = [line for source in pool[key] for line in source["evidence"]
                            if line.get("evidence_id") == selection["evidence_id"]]
                if not evidence:
                    raise ValueError("Unprovided body evidence ID")
                if len({line["text"] for line in evidence}) > 1:
                    evidence = [line for line in preferred.get(key, {}).get("evidence", [])
                                if line.get("evidence_id") == selection["evidence_id"]]
                    if len({line["text"] for line in evidence}) != 1:
                        raise ValueError("Ambiguous legacy evidence ID")
                selection["identity_quote"] = evidence[0]["text"]
            for field in ("identity_quote", "scope", "rationale"):
                if not isinstance(selection.get(field), str) or not selection[field].strip():
                    raise ValueError(f"Missing {field}")
            quote = selection["identity_quote"]
            if len(quote) < 8 or not any(quote in line["text"] for source in pool[key] for line in source["evidence"]):
                raise ValueError(f"Quote is not exact supplied body evidence: {disease_id} {key}")
            fields = selection.get("plan_fields")
            if not isinstance(fields, list) or len(set(fields)) != len(fields) or not set(fields) <= set(FIELDS):
                raise ValueError("Invalid SOAP P navigation fields")
            use = selection.get("evidence_use", "care_navigation")
            if use not in {"care_navigation", "background_only"} or use == "background_only" and fields:
                raise ValueError("Background-only references cannot supply SOAP P fields")
        terms = entry.get("search_terms", [])
        if not isinstance(terms, list) or len(terms) > 5 or any(not isinstance(t, str) or not 1 <= len(t) <= 100 for t in terms):
            raise ValueError("Invalid bounded search terms")
        if not selections and not entry.get("gap_reason"):
            raise ValueError("An unmapped disease requires a concrete gap reason")
    return entries


def request_packets(request):
    return [packet for message in request["messages"] if message["role"] == "user"
            for packet in json.loads(message["content"])["items"]]


def result_entries(output):
    ledger = [json.loads(line) for line in (output / "requests.jsonl").read_text().splitlines()]
    order = {r["request_id"]: i for i, r in enumerate(ledger) if r["event"] == "reserved"}
    entries = [json.loads(line) for path in output.glob("*-results.jsonl") for line in path.read_text().splitlines()]
    return sorted(entries, key=lambda entry: (order[entry["request_id"]], entry["disease_id"]))


def wire_batches(packets, batch_size, *, context_chars=300, document_count=6):
    batches, batch, size = [], [], 0
    for packet in packets:
        compact = {"disease_id": packet["disease_id"], "labels": packet["labels"],
                   "aliases": packet["aliases"][:20], "candidates": []}
        ranked = packet["candidates"]
        guidance = [c for c in ranked if c["document_type"] in GUIDANCE]
        chosen = list({c["document_id"]: c for c in [*ranked[:document_count - 2], *guidance[:2], *ranked]}.values())[:document_count]
        for candidate in chosen:
            compact["candidates"].append({key: candidate[key] for key in
                ("document_id", "title", "organization", "year", "document_type", "role", "language")})
            compact["candidates"][-1].update(
                evidence=[{**line, "evidence_id": f"E{i}", "text": line["text"][:context_chars]}
                          for i, line in enumerate(candidate["evidence"][:2], 1)],
                plan_sections=[{"title": section["title"][:120], "candidate_fields": section["candidate_fields"]}
                               for section in candidate["plan_sections"][:4]])
        if packet.get("recovery_search_terms"):
            compact["recovery_search_terms"] = packet["recovery_search_terms"]
        if packet.get("source_family_links"):
            compact["source_family_links"] = packet["source_family_links"]
        amount = len(json.dumps({"items": [compact]}, ensure_ascii=False).encode()) + 100
        if amount > 60000:
            raise ValueError("One disease exceeds the bounded wire packet size")
        if batch and (len(batch) >= batch_size or size + amount > 60000):
            batches.append(batch)
            batch, size = [], 0
        batch.append(compact)
        size += amount
    if batch:
        batches.append(batch)
    for batch in batches:
        evidence_ids = {}
        for packet in batch:
            for source in packet["candidates"]:
                for line in source["evidence"]:
                    key = (source["document_id"], line["line"], line["column_start"], line["text"])
                    evidence_ids.setdefault(key, f"E{len(evidence_ids) + 1}")
                    line["evidence_id"] = evidence_ids[key]
    return batches


def run(root, output, *, max_calls, batch_size=8, client=None, candidates_file="candidates.jsonl", stage="initial"):
    output = output_directory(root, output)
    if not re.fullmatch(r"[a-z][a-z0-9-]*", stage):
        raise ValueError("Stage must be a simple lowercase identifier")
    preparation = load(output / "preparation.json")
    for name in ("inventory", "candidates"):
        extension = "json" if name == "inventory" else "jsonl"
        if sha256((output / f"{name}.{extension}").read_bytes()) != preparation[f"{name}_sha256"]:
            raise ValueError("Pinned preparation changed")
    packets = [json.loads(line) for line in inside(output, candidates_file).read_text().splitlines()]
    if not packets or len({p["disease_id"] for p in packets}) != len(packets):
        raise ValueError("Require distinct nonempty disease packets")
    if not 1 <= max_calls <= 200 or not 1 <= batch_size <= 12:
        raise ValueError("Use a finite ceiling up to 200 requests and batches up to 12")
    focused = stage.startswith("recovery-")
    final_focus = focused and stage != "recovery-2"
    batches = wire_batches(packets, batch_size, context_chars=650 if focused else 300,
                           document_count=12 if final_focus else 6)
    needed = len(batches)
    if needed > max_calls:
        raise ValueError("Insufficient request ceiling")
    ledger = output / "requests.jsonl"
    previous = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    if any(e.get("stage") == stage for e in previous):
        raise ValueError("Stage already attempted; do not automatically resume or retry")
    if len([e for e in previous if e["event"] == "reserved"]) + needed > max_calls:
        raise ValueError("Total request ceiling exceeded")
    if client is None:
        if os.environ.get("NOVA_API_BASE", "").rstrip('/') != ORIGIN or not os.environ.get("NOVA_DEV_KEY") or os.environ.get("NOVA_SESSION_ID"):
            raise ValueError("Require the configured session-free NOVA development route")
        sys.path.insert(0, str(root / "submission"))
        from nova_sdk import Client
        class AuditedClient(Client):
            def _open(self, request):
                try:
                    return super()._open(request)
                except urllib.error.HTTPError as error:
                    raw = error.read()
                    write(self.audit_directory / "http-error-body.json", raw)
                    raise urllib.error.HTTPError(error.url, error.code, error.msg, error.hdrs, io.BytesIO(raw)) from error
        client = AuditedClient(api_base=ORIGIN, token=os.environ["NOVA_DEV_KEY"], session_id="", timeout=240)
    prompt_path = Path(__file__).with_name("prompt.txt")
    prompt = prompt_path.read_text()
    day = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    policy_path = output / "run-policy.json"
    policy = {"model": MODEL, "origin": ORIGIN, "session": "none", "max_calls": max_calls,
              "kst_day": day, "automatic_retries": 0, "prompt_sha256": sha256(prompt.encode()),
              "code_sha256": sha256(Path(__file__).read_bytes())}
    if policy_path.exists():
        previous_policy = load(policy_path)
        mutable_pins = {"code_sha256", "prompt_sha256"}
        if {k: v for k, v in previous_policy.items() if k not in mutable_pins} != {k: v for k, v in policy.items() if k not in mutable_pins}:
            raise ValueError("Run policy or day changed")
    else:
        save(policy_path, policy)
    replay = output / "replay"
    replay.mkdir(exist_ok=True)
    write(replay / (policy["code_sha256"] + "-map.py"), Path(__file__).read_bytes())
    if not (replay / "prompt.txt").exists():
        write(replay / "prompt.txt", prompt.encode())
    write(replay / (policy["prompt_sha256"] + "-prompt.txt"), prompt.encode())
    results_path = output / f"{stage}-results.jsonl"
    if results_path.exists():
        raise ValueError("Results already exist")
    results_path.touch()
    processed = 0
    for batch in batches:
        if datetime.now(timezone(timedelta(hours=9))).date().isoformat() != day:
            raise ValueError("KST day changed; stop without resumption")
        request_id = str(uuid.uuid4())
        directory = output / "calls" / request_id
        directory.mkdir(parents=True, exist_ok=False)
        system = prompt + "\nItems are supplied across multiple user messages. Return one items array covering every supplied disease."
        if stage.startswith("recovery"):
            system += ("\nsource_family_links are active source-backed SNOMED is-a paths, not synonyms. "
                       "For broad database categories, a documented subtype's care document is a valid narrower navigation link. "
                       "Do not reject it solely because it does not cover the whole category; preserve that scope limitation.")
        if focused:
            system += ("\nThis is document navigation. Broader clinical evaluation or management sources can be selected "
                       "when their actual care topic relates to the target; use broader or related and qualify scope. "
                       "Disease-specific treatment is not required for such a navigation link. Incidental references alone remain insufficient.")
        if final_focus:
            system += ("\nPrefer care content. If no care source is supported, a genuine clinical body discussion or differential-context "
                       "source may be linked as related with evidence_use=background_only and plan_fields=[]. "
                       "State explicitly that it supplies no P support. A bibliography citation alone is insufficient. "
                       "For care references use evidence_use=care_navigation. Never invent disease-specific management.")
        request = {"model": MODEL, "reasoning_effort": "medium" if final_focus else "low", "max_tokens": 6000,
                   "request_id": request_id, "messages": [{"role": "system", "content": system},
                   *[{"role": "user", "content": json.dumps({"items": [p]}, ensure_ascii=False)} for p in batch]]}
        save(directory / "request.json", request)
        record = {"event": "reserved", "stage": stage, "request_id": request_id,
                  "disease_ids": [p["disease_id"] for p in batch], "model": MODEL,
                  "code_sha256": policy["code_sha256"],
                  "prompt_sha256": policy["prompt_sha256"],
                  "packets_sha256": sha256(json_bytes(batch)),
                  "request_sha256": sha256((directory / "request.json").read_bytes())}
        with ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if len(json.dumps(request["messages"], ensure_ascii=False).encode()) > 70000:
                raise ValueError("Request exceeds the conservative input byte ceiling")
            client.audit_directory = directory
            response = client.chat(**request)
            save(directory / "response.json", response)
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("Incomplete model response")
            entries = validate_response(choice["message"]["content"], batch)
            with ledger.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"event": "completed", "stage": stage, "request_id": request_id,
                                        "response_sha256": sha256((directory / "response.json").read_bytes())}) + "\n")
            with results_path.open("a", encoding="utf-8") as stream:
                for entry in entries:
                    stream.write(json.dumps({**entry, "request_id": request_id, "stage": stage}, ensure_ascii=False) + "\n")
        except Exception as error:
            save(directory / "failure.json", {"type": type(error).__name__, "error": str(error),
                 "automatic_retries": 0, "request_id": request_id})
            raise
        processed += len(batch)
        print(json.dumps({"stage": stage, "processed": processed,
                          "total": len(packets), "request_id": request_id,
                          "unmapped": sum(not e["selections"] for e in entries)}), flush=True)
    return {"stage": stage, "processed": len(packets), "requests": needed}


def export(root, output, *, verify_only=False):
    output = output_directory(root, output)
    def emit(name, payload):
        if verify_only:
            if (output / name).read_bytes() != payload:
                raise ValueError(f"Artifact differs from replay: {name}")
        else:
            write(output / name, payload)
    inventory = load(output / "inventory.json")
    diseases = {d["id"]: d for d in inventory["diseases"]}
    sources = {s["document_id"]: s for s in inventory["sources"]}
    results = {}
    for entry in result_entries(output):
        if entry["disease_id"] in results:
            previous = results[entry["disease_id"]]
            if previous["selections"] or not entry["stage"].startswith("recovery"):
                raise ValueError("Only unresolved results can be replaced by an explicit recovery stage")
        results[entry["disease_id"]] = entry
    rows, mappings = [], []
    for disease_id, disease in diseases.items():
        entry = results.get(disease_id, {"selections": [], "gap_reason": "not_processed"})
        selections = []
        for selection in entry["selections"]:
            source = sources[selection["document_id"]]
            raw, lines = read_lines(root, source)
            byte_lines = raw.splitlines(keepends=True)
            quote = selection["identity_quote"]
            evidence_lines = [i for i, line in enumerate(lines, 1) if quote in line]
            if not evidence_lines:
                raise ValueError("Source quote no longer resolves")
            metadata, headings, parse_error = sections(raw)
            pointers = []
            for heading in headings:
                if selection.get("evidence_use") == "background_only":
                    break
                fields = [field for field, pattern in HEADINGS.items() if re.search(pattern, heading["title"], re.I)]
                if not fields:
                    continue
                block = b"".join(byte_lines[heading["start_line"] - 1:heading["end_line"]])
                pointers.append({**heading, "candidate_fields": fields, "section_sha256": sha256(block),
                                 "status": "navigation_only_requires_context_review"})
            result = {**selection, "source": source, "source_metadata": metadata,
                      "evidence_use": selection.get("evidence_use", "care_navigation"),
                      "identity_lines": evidence_lines, "plan_sections": pointers, "parse_error": parse_error,
                      "plan_extraction": "not_run", "runtime_admission": "not_run",
                      "unconditional_disease_plan": False}
            selections.append(result)
            rows.append({"disease_id": disease_id, "disease_en": disease["labels"].get("en", ""),
                         "disease_ko": disease["labels"].get("ko", ""), "path": source["path"],
                         "title": source["title"], "document_type": source["document_type"],
                         "relation": selection["relation"], "role": selection["document_role"],
                         "evidence_use": selection.get("evidence_use", "care_navigation"),
                         "year": source["year"], "organization": source["organization"],
                         "identity_lines": ",".join(map(str, evidence_lines)), "identity_quote": quote,
                         "scope": selection["scope"], "rationale": selection["rationale"],
                         "candidate_plan_fields": ",".join(selection["plan_fields"]),
                         "sha256": source["sha256"], "source_url": source["source_url"], "license": source["license"],
                         "request_id": entry["request_id"]})
        mappings.append({"disease_id": disease_id, "labels": disease["labels"], "aliases": disease["aliases"],
                         "selections": selections, "gap_reason": entry.get("gap_reason") if not selections else None})
        if entry.get("stage", "").startswith("recovery"):
            request = load(output / "calls" / entry["request_id"] / "request.json")
            supplied = next(p for p in request_packets(request) if p["disease_id"] == disease_id)
            mappings[-1]["source_family_links"] = supplied.get("source_family_links", [])
    emit("mappings.json", json_bytes({"version": VERSION, "status": "source_mapping_only", "diseases": mappings}))
    if rows:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        emit("mappings.csv", stream.getvalue().encode("utf-8-sig"))
    summary = {"diseases": len(diseases), "mapped": sum(bool(m["selections"]) for m in mappings),
               "unmapped": [m["disease_id"] for m in mappings if not m["selections"]],
               "links": len(rows), "selected_documents": len({r["path"] for r in rows}),
               "relations": dict(Counter(r["relation"] for r in rows)),
               "document_roles": dict(Counter(r["role"] for r in rows)),
               "diseases_with_exact_coverage": sum(any(s["relation"] == "exact" for s in m["selections"]) for m in mappings),
               "diseases_with_guidance": sum(any(s["document_role"] == "clinical_guidance" for s in m["selections"]) for m in mappings),
               "background_only_diseases": [m["disease_id"] for m in mappings if m["selections"] and
                                            all(s["evidence_use"] == "background_only" for s in m["selections"])],
               "partial_scope_only": [m["disease_id"] for m in mappings if m["selections"] and
                                      all(s["relation"] in {"narrower", "related"} for s in m["selections"])],
               "no_plan_section_headings": [m["disease_id"] for m in mappings if m["selections"] and
                                           not any(s["plan_sections"] for s in m["selections"])],
               "plan_extraction": "not_run", "runtime_admission": "not_run",
               "independent_clinical_validation": "not_run", "external_guideline_currentness": "not_run"}
    summary["care_navigation_without_section_headings"] = sorted(set(summary["no_plan_section_headings"]) -
                                                                set(summary["background_only_diseases"]))
    emit("summary.json", json_bytes(summary))
    report = ["# 질환별 SOAP P 근거 문서 매핑", "", f"질환 {len(diseases)}개 중 {summary['mapped']}개 연결, 문서 연결 {len(rows)}개.", "",
              f"관리 내용 탐색 연결: {summary['mapped'] - len(summary['background_only_diseases'])}개 질환. "
              f"배경 전용 연결: {len(summary['background_only_diseases'])}개 질환이며 P 근거로 선택하지 않았습니다.",
              f"동일 질환 명시 연결을 가진 질환: {summary['diseases_with_exact_coverage']}개. "
              f"하위 질환·관련 주제 연결만 가진 질환: {len(summary['partial_scope_only'])}개.",
              f"관리 탐색 문서는 있지만 제목 기반 P 절 탐색 위치가 없는 질환: {len(summary['care_navigation_without_section_headings'])}개. "
              "이 항목은 후속 추출에서 원문의 구조를 직접 확인해야 합니다.", "",
              "원본 문서와 현재 데이터베이스를 연결한 사전 준비 결과입니다. P 내용 추출·환자별 적용·런타임 편입은 수행하지 않았습니다.",
              "exact는 동일 질환, broader는 더 넓은 질환군, narrower는 일부 하위 질환, related는 관련 주제입니다. "
              "부분 범위 문서의 치료를 상위 질환 전체에 적용할 수 없습니다. plan_sections는 제목 기반 탐색 위치이며 권고 검증이 아닙니다.", "",
              "[전체 CSV](mappings.csv) · [전체 JSON](mappings.json) · [검증 결과](verification.json)", ""]
    for mapping in mappings:
        label = mapping["labels"].get("ko") or mapping["labels"].get("en") or mapping["disease_id"]
        report += [f"## {label}", "", f"`{mapping['disease_id']}`", ""]
        if not mapping["selections"]:
            report += [f"미연결: {mapping['gap_reason']}", ""]
        for selection in mapping["selections"]:
            s = selection["source"]
            relative = os.path.relpath(source_path(root, s["path"]), output)
            report += [f"- [{s['title']}]({relative}) — `{selection['relation']}`; {s['document_type']}; {s['year']}",
                       f"- 근거 용도: `{selection['evidence_use']}`",
                       f"- 원문 위치: 줄 {', '.join(map(str, selection['identity_lines']))}; `{s['sha256']}`",
                       f"- 적용 범위: {selection['scope']}", f"- 관련 근거: {selection['rationale']}",
                       f"- P 탐색 필드: {', '.join(selection['plan_fields']) or 'none'}", ""]
    emit("review.md", ("\n".join(report) + "\n").encode())
    return summary


def title_key(text):
    words = [w[:-3] + "y" if len(w) > 4 and w.endswith("ies") else w[:-1] if len(w) > 4 and w.endswith("s") else w for w in normalized(text).split()
             if w not in {"a", "an", "the", "of", "and"}]
    if "fracture" in words:
        words = [w for w in words if w != "bone"]
    if "dislocation" in words:
        words = [w for w in words if w != "joint"]
    return tuple(sorted(words))


def source_family_links(root, inventory, wanted):
    db = SourceDatabase(inside(root, inventory["source_database"]["path"]), readonly=True)
    try:
        snapshot = SnapshotSources(db)
        diseases = {d["id"].removeprefix("urn:ontoward:SnomedCT"): d for d in inventory["diseases"]}
        targets = {d.removeprefix("urn:ontoward:SnomedCT") for d in wanted}
        titles = {normalized(s["title"]) for s in inventory["sources"] if not excluded(s)}
        suitable = {cid: d for cid, d in diseases.items() if any(normalized(a) in titles for a in d["aliases"])}
        title_lookup = {}
        for source in inventory["sources"]:
            if not excluded(source):
                title_lookup.setdefault(title_key(source["title"]), set()).add(source["title"])
        for row in db.connection.execute("SELECT id,concept_id,term,row_id FROM rf2_components "
                                         "WHERE kind='description' AND active='1' AND language='en'"):
            cid = row["concept_id"]
            if cid not in snapshot.findings:
                continue
            term = re.sub(r"\s*\((?:disorder|finding)\)$", "", row["term"])
            matching = title_lookup.get(title_key(term), ())
            if not matching:
                continue
            label = re.sub(r"\s*\((?:disorder|finding)\)$", "", snapshot.fsns.get(cid, term))
            member = suitable.setdefault(cid, {"id": "urn:ontoward:SnomedCT" + cid,
                                               "labels": {"en": label}, "aliases": [label]})
            for title in sorted(matching):
                proof = {"catalog_title": title, "description_id": row["id"], "source_row_id": row["row_id"],
                         "term": row["term"], "method": "lexical_title_navigation_only"}
                old = member.setdefault("title_matches", {}).get(title)
                if old is None or proof["description_id"] < old["description_id"]:
                    member["title_matches"][title] = proof
        paths = {cid: snapshot.ancestor_paths(cid) for cid in set(suitable) | targets}
        links = {d: [] for d in wanted}
        for target in sorted(targets):
            for cid, member in suitable.items():
                if cid == target:
                    continue
                if target in paths[cid]:
                    relation, path, child, parent = "narrower", paths[cid][target], cid, target
                elif cid in paths[target]:
                    relation, path, child, parent = "broader", paths[target][cid], target, cid
                else:
                    continue
                links[diseases[target]["id"]].append({"disease_id": member["id"], "labels": member["labels"],
                     "relation": relation, "source_child": child, "source_parent": parent,
                     "rf2_relationship_ids": path,
                     "search_aliases": sorted(set(member.get("title_matches", {})) |
                                              {a for a in member["aliases"] if normalized(a) in titles})[:2],
                     "title_navigation": [member["title_matches"][title] for title in sorted(member.get("title_matches", {}))[:2]]})
            links[diseases[target]["id"]].sort(key=lambda x: (len(x["rf2_relationship_ids"]), x["disease_id"]))
            links[diseases[target]["id"]] = links[diseases[target]["id"]][:6]
        return links
    finally:
        db.close()


def verify_family_path(connection, target, link):
    if target not in {link["source_child"], link["source_parent"]}:
        raise ValueError("Family path does not include the target Disease")
    expected_relation = "narrower" if target == link["source_parent"] else "broader"
    reference = link["source_child"] if expected_relation == "narrower" else link["source_parent"]
    if link["relation"] != expected_relation or link["disease_id"] != "urn:ontoward:SnomedCT" + reference:
        raise ValueError("Family relation or reference concept has the wrong direction")
    cursor = link["source_child"]
    if not link["rf2_relationship_ids"]:
        raise ValueError("Family path is empty")
    for relationship in link["rf2_relationship_ids"]:
        row = connection.execute("SELECT source_id,destination_id FROM rf2_components WHERE kind='relationship' "
                                 "AND id=? AND active='1' AND type_id='116680003' AND characteristic='900000000000011006'",
                                 (relationship,)).fetchone()
        if row is None or row["source_id"] != cursor:
            raise ValueError("Family path is not an exact active inferred is-a chain")
        cursor = row["destination_id"]
    if cursor != link["source_parent"]:
        raise ValueError("Family path ends at the wrong parent")
    for proof in link.get("title_navigation", []):
        row = connection.execute("SELECT concept_id,term,row_id FROM rf2_components "
                                 "WHERE kind='description' AND id=? AND active='1'", (proof["description_id"],)).fetchone()
        if row is None or row["concept_id"] != reference or row["term"] != proof["term"] or row["row_id"] != proof["source_row_id"]:
            raise ValueError("Title navigation does not match the active source description")
        term = re.sub(r"\s*\((?:disorder|finding)\)$", "", proof["term"])
        if title_key(term) != title_key(proof["catalog_title"]):
            raise ValueError("Title navigation differs from its recorded lexical rule")


def recover(root, output, *, round_number=1):
    output = output_directory(root, output)
    if not 1 <= round_number <= 150:
        raise ValueError("Use a positive explicit recovery round within the frozen request ceiling")
    inventory = load(output / "inventory.json")
    results = {}
    for entry in result_entries(output):
        results[entry["disease_id"]] = entry
    prefix = "recovery" if round_number == 1 else f"recovery-{round_number}"
    target = output / f"{prefix}-candidates.jsonl"
    if target.exists():
        raise ValueError("Recovery candidates already exist; do not resume them automatically")
    preparation = load(output / "preparation.json")
    wanted = {d["id"] for d in inventory["diseases"] if not results.get(d["id"], {}).get("selections")}
    families = source_family_links(root, inventory, wanted)
    index_path = inside(root, preparation.get("index_path", "Tmp/guideline-mapping/index.sqlite3"))
    db = sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)
    packets = []
    try:
        for disease in inventory["diseases"]:
            previous = results.get(disease["id"], {})
            if previous.get("selections"):
                continue
            terms = [*previous.get("search_terms", [])]
            for label in disease["labels"].values():
                broadened = re.sub(r"\b(?:left|right|proper|region)\b", "", label, flags=re.I)
                broadened = " ".join(broadened.split())
                if broadened != label and broadened:
                    terms.append(broadened)
            family_terms = [a for link in families[disease["id"]] for a in link["search_aliases"]]
            base = retrieve(db, inventory["sources"], disease, search_terms=terms, limit=16)
            family = retrieve(db, inventory["sources"], disease, search_terms=family_terms, limit=10)
            combined = [*base[:10], *family[:4], *base, *family]
            matches = list({source["document_id"]: (source, score) for source, score in combined}.values())[:16]
            value = packet(root, disease, matches, search_terms=terms)
            value["recovery_search_terms"] = terms
            value["source_family_links"] = families[disease["id"]]
            value["previous_gap_reason"] = previous.get("gap_reason", "not_processed")
            packets.append(value)
    finally:
        db.close()
    write(target, b"".join(json.dumps(p, ensure_ascii=False).encode() + b"\n" for p in packets))
    save(output / f"{prefix}-manifest.json", {"candidates_sha256": sha256(target.read_bytes()),
         "base_inventory_sha256": preparation["inventory_sha256"],
         "source_family_links": families,
         "previous_results": {p.name: sha256(p.read_bytes()) for p in output.glob("*-results.jsonl")}})
    return {"recovery_diseases": len(packets), "candidates_file": target.name}


def verify(root, output, *, require_complete=True):
    output = output_directory(root, output)
    inventory = load(output / "inventory.json")
    preparation = load(output / "preparation.json")
    if sha256((output / "inventory.json").read_bytes()) != preparation["inventory_sha256"]:
        raise ValueError("Inventory changed")
    runtime, current = runtime_inputs(root)
    if runtime != inventory["runtime"] or {d["id"] for d in current} != {d["id"] for d in inventory["diseases"]}:
        raise ValueError("Runtime disease set changed")
    if inventory.get("source_database"):
        identity = aliases_from_database(root, current, inventory["source_database"]["path"])
        if identity != inventory["source_database"] or current != inventory["diseases"]:
            raise ValueError("Disease aliases or source database identity changed")
    if sha256((root / inventory["catalog"]["path"]).read_bytes()) != inventory["catalog"]["sha256"]:
        raise ValueError("Catalog changed")
    for source in inventory["sources"]:
        if sha256(source_path(root, source["path"]).read_bytes()) != source["sha256"]:
            raise ValueError(f"Source changed: {source['path']}")
    preserved_submission, guidance_changes = 0, []
    for path, expected in inventory["protected_submission"].items():
        if Path(path).name in GUIDANCE_FILES:
            if sha256(inside(root, path).read_bytes()) != expected:
                guidance_changes.append(path)
            continue
        if sha256(inside(root, path).read_bytes()) != expected:
            raise ValueError(f"Submission changed: {path}")
        preserved_submission += 1
    mappings = load(output / "mappings.json")["diseases"]
    if len(mappings) != len(current) or {m["disease_id"] for m in mappings} != {d["id"] for d in current}:
        raise ValueError("Mapping disease coverage differs")
    if sha256((output / "candidates.jsonl").read_bytes()) != preparation["candidates_sha256"]:
        raise ValueError("Candidates changed")
    records = [json.loads(line) for line in (output / "requests.jsonl").read_text().splitlines()]
    reservations = {r["request_id"]: r for r in records if r["event"] == "reserved"}
    completed = {r["request_id"]: r for r in records if r["event"] == "completed"}
    policy = load(output / "run-policy.json")
    if len(reservations) > policy["max_calls"] or policy["model"] != MODEL or policy["origin"] != ORIGIN:
        raise ValueError("NOVA request policy changed or ceiling exceeded")
    checked = set()
    for result_file in output.glob("*-results.jsonl"):
        for entry in map(json.loads, result_file.read_text().splitlines()):
            directory = output / "calls" / entry["request_id"]
            request = load(directory / "request.json")
            response = load(directory / "response.json")
            if response["choices"][0].get("finish_reason") != "stop":
                raise ValueError("Preserved model response is incomplete")
            if (request["model"] != MODEL or request.get("session_id")
                    or sha256((directory / "request.json").read_bytes()) != reservations[entry["request_id"]]["request_sha256"]
                    or sha256((directory / "response.json").read_bytes()) != completed[entry["request_id"]]["response_sha256"]):
                raise ValueError("Request or response pin changed")
            requested = request_packets(request)
            if sha256(json_bytes(requested)) != reservations[entry["request_id"]]["packets_sha256"]:
                raise ValueError("Request packets changed")
            validated = validate_response(response["choices"][0]["message"]["content"], requested)
            expected = next(e for e in validated if e["disease_id"] == entry["disease_id"])
            if expected != {k: v for k, v in entry.items() if k not in {"request_id", "stage"}}:
                raise ValueError("Result differs from preserved model response")
            checked.add(entry["disease_id"])
    for mapping in mappings:
        if require_complete and not mapping["selections"]:
            raise ValueError(f"Disease has no supported document: {mapping['disease_id']}")
        for selection in mapping["selections"]:
            raw, lines = read_lines(root, selection["source"])
            byte_lines = raw.splitlines(keepends=True)
            if not all(selection["identity_quote"] in lines[i - 1] for i in selection["identity_lines"]):
                raise ValueError("Mapping quote changed")
            for section in selection["plan_sections"]:
                block = b"".join(byte_lines[section["start_line"] - 1:section["end_line"]])
                if sha256(block) != section["section_sha256"]:
                    raise ValueError("Plan section changed")
    family_checks = 0
    if any(m.get("source_family_links") for m in mappings):
        database = SourceDatabase(inside(root, inventory["source_database"]["path"]), readonly=True)
        try:
            for mapping in mappings:
                for link in mapping.get("source_family_links", []):
                    verify_family_path(database.connection, mapping["disease_id"].removeprefix("urn:ontoward:SnomedCT"), link)
                    family_checks += 1
        finally:
            database.close()
    export(root, output, verify_only=True)
    result = {"result": "pass", "diseases": len(current), "mapped": sum(bool(m["selections"]) for m in mappings),
              "catalog_documents_preserved": len(inventory["sources"]),
              "submission_files_preserved": preserved_submission,
              "unrelated_guidance_baseline_differences": guidance_changes,
              "model_results_replayed": len(checked), "complete_coverage_required": require_complete,
              "model_requests": len(reservations), "model_responses": len(completed),
              "source_family_paths_verified": family_checks,
              "mappings_sha256": sha256((output / "mappings.json").read_bytes()),
              "runtime_admission": "not_run", "independent_clinical_validation": "not_run"}
    save(output / "verification.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Map admitted Diseases to catalog-allowlisted guideline corpus documents")
    parser.add_argument("command", choices=["prepare", "run", "recover", "export", "verify"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--candidates-file", default="candidates.jsonl")
    parser.add_argument("--stage", default="initial")
    parser.add_argument("--recovery-round", type=int, default=1)
    parser.add_argument("--allow-gaps", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(ROOT, args.output)
    elif args.command == "run":
        result = run(ROOT, args.output, max_calls=args.max_calls, batch_size=args.batch_size,
                     candidates_file=args.candidates_file, stage=args.stage)
    elif args.command == "export":
        result = export(ROOT, args.output)
    elif args.command == "recover":
        result = recover(ROOT, args.output, round_number=args.recovery_round)
    else:
        result = verify(ROOT, args.output, require_complete=not args.allow_gaps)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
