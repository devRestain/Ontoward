from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import sqlite3
import unicodedata
from uuid import uuid4

from rdflib import Graph, RDF, URIRef
from rdflib.util import from_n3

from .database import file_hash, json_text
from .provenance import EvidenceSets
from .v5 import OW, ROOT, digest, workspace_path, write

MODEL = "gpt-6-luna"
BATCH_SIZE = 20
PROMPTS = Path(__file__).parent / "prompts"


def load_graph(catalog, *, runtime_only=False):
    graph = Graph()
    for name in ("vocabulary.ttl", "clinical.ttl"):
        graph.parse(catalog.parent / "preview" / name, format="turtle")
    if runtime_only:
        return graph
    with (catalog / "relations.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if "n3" in item["object"]:
                graph.add((URIRef(item["subject"]), URIRef(item["predicate"]), from_n3(item["object"]["n3"])))
    return graph


def check_catalog(catalog):
    manifest = json.loads((catalog / "manifest.json").read_text())
    for name, sha in manifest["files"].items():
        if file_hash(catalog / name) != sha:
            raise ValueError("Catalog pin changed: " + name)
    return manifest


def freeze(catalog, output):
    catalog, output = workspace_path(catalog), workspace_path(output)
    if output.exists() or not output.is_relative_to(ROOT / "data/preparation/v5"):
        raise ValueError("Freeze into a new data-owned workset path")
    manifest = check_catalog(catalog)
    for name, sha in manifest["generator_files"].items():
        if file_hash(Path(__file__).parent / name) != sha:
            raise ValueError("Cannot freeze a workset from a different generator: " + name)
    entries = json.loads((catalog / "lexical.json").read_text())
    evidence = EvidenceSets.load(catalog / 'evidence.json')
    by_id = {entry["uri"]:entry for entry in entries}
    graph = load_graph(catalog, runtime_only=True)
    runtime_targets = {str(node) for node in graph.subjects(RDF.type, OW.Symptom)}
    links = {}
    with (catalog/'relations.jsonl').open() as stream:
        for line in stream:
            record = json.loads(line)
            if record['predicate']==str(OW.hasAttribute) and 'n3' in record['object']:
                pair = (record['subject'],str(from_n3(record['object']['n3'])))
                links[pair] = record['evidence']['evidence_id']
    labels, questions = {}, {}
    for entry in entries:
        evidence.resolve(entry['evidence_id'])
        if not entry["korean_label"]:
            key = digest(["label", entry.get("snomed_id"), entry["label"]])
            job = labels.setdefault(key, {"job_id":key, "kind":"label", "english_label":entry["label"],
                "role":entry["kind"], "uris":[], "evidence_ids":[]})
            job["uris"].append(entry["uri"])
            job["evidence_ids"] = sorted(set(job["evidence_ids"]) | {entry['evidence_id']})
        if entry["kind"] not in {"Symptom", "ContextFactor"} or entry["question_status"] != "pending_clinical_question":
            continue
        def add(attribute=None):
            key = entry["uri"] + ("|" + attribute if attribute else "")
            purpose = "attribute" if attribute else "history" if entry["kind"] == "ContextFactor" else "presence"
            proofs = {entry['evidence_id']}
            if attribute:
                proofs.add(links[(entry['uri'],attribute)])
            job = {"kind":"question", "key":key, "target":entry["uri"], "attribute":attribute,
                "purpose":purpose, "english_label":entry["label"],
                "attribute_label":by_id[attribute]["label"] if attribute else None,
                "evidence_ids":sorted(proofs), "runtime_candidate":entry["uri"] in runtime_targets}
            job["job_id"] = digest(job)
            questions[key] = job
        add()
        for attribute in sorted(str(node) for node in graph.objects(URIRef(entry["uri"]), OW.hasAttribute)):
            add(attribute)
    label_jobs, question_jobs = sorted(labels.values(), key=lambda job:job["job_id"]), sorted(questions.values(), key=lambda job:job["key"])
    l, q = len(label_jobs), len(question_jobs)
    workset = {"version":"d19.1", "scope":"competition_source_dependency_closure", "model":MODEL,
        "build_id":manifest["build_id"], "catalog":catalog.relative_to(ROOT).as_posix(),
        "catalog_manifest_sha256":file_hash(catalog / "manifest.json"), "entries":entries,
        "evidence_file":"evidence.json", "evidence_sha256":file_hash(catalog/'evidence.json'),
        "label_jobs":label_jobs, "question_jobs":question_jobs, "batch_size":BATCH_SIZE,
        "label_count":l, "question_count":q, "max_calls":2 * (math.ceil(l / BATCH_SIZE) + math.ceil(q / BATCH_SIZE)),
        "prompt_files":{path.name:file_hash(path) for path in sorted(PROMPTS.glob("korean-*.txt"))},
        "generator_files":{path.name:file_hash(path) for path in sorted(Path(__file__).parent.glob("*.py"))},
        "runtime_admission":"not_run", "independent_clinical_validation":"not_run"}
    write(output, workset)
    return {"status":"frozen", "workset":output.relative_to(ROOT).as_posix(), "sha256":file_hash(output),
            "labels":l, "questions":q, "max_calls":workset["max_calls"]}


def response_schema(review=False):
    fields = {"job_id":{"type":"string"}, "decision":{"type":"string", "enum":["accept", "reject"] if review else ["candidate", "unresolved"]},
              "reason":{"type":"string"}}
    if not review:
        fields["text"] = {"type":["string", "null"]}
    return {"type":"object", "additionalProperties":False, "properties":{"items":{"type":"array", "items":{
        "type":"object", "additionalProperties":False, "properties":fields, "required":list(fields)}}}, "required":["items"]}


def validate(response, jobs, *, review=False):
    if not isinstance(response, dict) or set(response) != {"items"} or not isinstance(response["items"], list):
        raise ValueError("Invalid whole-response object")
    expected = {job["job_id"]:job for job in jobs}
    found = {}
    for item in response["items"]:
        fields = {"job_id", "decision", "reason"} | (set() if review else {"text"})
        if not isinstance(item, dict) or set(item) != fields or item["job_id"] not in expected or item["job_id"] in found:
            raise ValueError("Missing repeated or foreign response item")
        if not isinstance(item["reason"], str) or item["decision"] != ("accept" if review else "candidate"):
            raise ValueError("Whole batch contains an unresolved or rejected item: " + json_text(item))
        if not review:
            text = item["text"]
            if not isinstance(text, str) or not text.strip() or unicodedata.normalize("NFC", text) != text or any(c in text for c in "\r\n"):
                raise ValueError("Generated wording must be nonempty single-line NFC")
            if expected[item["job_id"]]["kind"] == "question" and (not 1 <= len(text) <= 30 or not any("가" <= c <= "힣" for c in text)):
                raise ValueError("Clinical question must contain Korean and 1 to 30 code points")
        found[item["job_id"]] = item
    if set(found) != set(expected):
        raise ValueError("Incomplete whole response")
    return found


def model_packet(job, labels):
    packet = {key:job[key] for key in ("job_id", "kind", "english_label", "purpose", "attribute_label", "role") if key in job}
    packet["source_proof_sha256"] = digest(job["evidence_ids"])
    if job["kind"] == "question":
        packet["korean_target"] = labels[job["target"]]
        packet["korean_attribute"] = labels.get(job["attribute"])
    return packet


def structural_labels(graph, labels):
    output = dict(labels)
    for node in graph.subjects(RDF.type, OW.ExpectedValue):
        payload = json.loads(str(graph.value(node, OW.valueJSON)))
        if payload["kind"] == "concept":
            text = labels[payload["concept"]]
        elif payload["kind"] == "concept_set":
            text = (" 또는 " if payload["selection"] == "any_of" else " 및 ").join(labels[key] for key in payload["concepts"])
        else:
            text = {"quantity":"수량 조건: ", "interval":"범위 조건: "}[payload["kind"]] + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        output[str(node)] = text
    for node in graph.subjects(RDF.type, OW.ClinicalFeature):
        attribute, expected = graph.value(node, OW.onAttribute), graph.value(node, OW.expected)
        output[str(node)] = (labels[str(attribute)] + ": " + output[str(expected)]) if attribute else {
            "present":"존재", "absent":"부재"}[str(graph.value(node, OW.expectedStatus))]
    for node in graph.subjects(RDF.type, OW.ClinicalPattern):
        output[str(node)] = labels[str(graph.value(node, OW.targets))] + " [" + "; ".join(
            output[str(feature)] for feature in sorted(graph.objects(node, OW.hasFeature), key=str)) + "]"
    for node in graph.subjects(RDF.type, OW.DiseasePatternAssociation):
        disease = next(graph.subjects(OW.hasAssociation, node))
        output[str(node)] = labels[str(disease)] + " → " + output[str(graph.value(node, OW.pattern))]
    for node in graph.subjects(RDF.type, OW.ValueMatch):
        output[str(node)] = labels[str(graph.value(node, OW.observedConcept))] + " → " + labels[str(graph.value(node, OW.expectedConcept))]
    return output


def run(workset_path, output, *, resume=False, client=None):
    workset_path, output = workspace_path(workset_path), workspace_path(output)
    workset = json.loads(workset_path.read_text())
    if not output.is_relative_to(ROOT / "data/preparation/v5"):
        raise ValueError("Korean results must remain in data-owned preparation")
    if output.exists() and not resume:
        raise ValueError("Use a new result directory or explicitly select the current workset with --resume")
    catalog = ROOT / workset["catalog"]
    check_catalog(catalog)
    if file_hash(catalog / "manifest.json") != workset["catalog_manifest_sha256"]:
        raise ValueError("Workset catalog identity changed")
    if workset.get('version')!='d19.1' or file_hash(catalog/workset['evidence_file'])!=workset['evidence_sha256']:
        raise ValueError('Workset evidence identity changed; freeze a new workset')
    evidence = EvidenceSets.load(catalog/workset['evidence_file'])
    for item in workset['entries']:
        evidence.resolve(item['evidence_id'])
    for job in workset['label_jobs'] + workset['question_jobs']:
        if not job.get('evidence_ids'):
            raise ValueError('Job has no source evidence')
        for key in job['evidence_ids']:
            evidence.resolve(key)
    for name, sha in workset["generator_files"].items():
        if file_hash(Path(__file__).parent / name) != sha:
            raise ValueError("Workset generator changed: " + name)
    for name, sha in workset["prompt_files"].items():
        if file_hash(PROMPTS / name) != sha:
            raise ValueError("Workset prompt changed")
    expected_budget = 2 * (math.ceil(len(workset["label_jobs"]) / BATCH_SIZE) + math.ceil(len(workset["question_jobs"]) / BATCH_SIZE))
    if (workset["max_calls"] != expected_budget or workset["batch_size"] != BATCH_SIZE or workset["model"] != MODEL
            or workset["label_count"] != len(workset["label_jobs"]) or workset["question_count"] != len(workset["question_jobs"])):
        raise ValueError("Workset budget differs from the approved formula")
    jobs = workset["label_jobs"] + workset["question_jobs"]
    if len({job["job_id"] for job in jobs}) != len(jobs) or len({job["key"] for job in workset["question_jobs"]}) != len(workset["question_jobs"]):
        raise ValueError("Frozen workset contains duplicate job identities")
    output.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output / "requests.sqlite3")
    connection.executescript("""PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,stage TEXT NOT NULL,batch TEXT NOT NULL,
            state TEXT NOT NULL,request TEXT NOT NULL,response TEXT,error TEXT,UNIQUE(stage,batch));
        CREATE TABLE IF NOT EXISTS results(job_id TEXT PRIMARY KEY,kind TEXT NOT NULL,text TEXT NOT NULL);
    """)
    workset_sha = file_hash(workset_path)
    previous = connection.execute("SELECT value FROM metadata WHERE key='workset'").fetchone()
    if previous and previous[0] != workset_sha:
        connection.close()
        raise ValueError("Never mix results from different worksets")
    connection.execute("INSERT OR REPLACE INTO metadata VALUES('workset',?)", (workset_sha,))
    connection.commit()
    labels = {entry["uri"]:entry["korean_label"] for entry in workset["entries"] if entry["korean_label"]}
    before_calls = connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    def call(stage, jobs, packets, review):
        batch_id = digest([job["job_id"] for job in jobs])
        prior = connection.execute("SELECT state,response FROM calls WHERE stage=? AND batch=?", (stage, batch_id)).fetchone()
        if prior:
            if prior[0] != "completed":
                raise RuntimeError("Previous failed or unknown request cannot be retransmitted")
            return validate(json.loads(prior[1]), jobs, review=review)
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] >= expected_budget:
            connection.rollback()
            raise RuntimeError("Frozen call budget exhausted")
        request_id = str(uuid4())
        connection.execute("INSERT INTO calls VALUES(?,?,?,?,?,NULL,NULL)",
            (request_id, stage, batch_id, "reserved", json_text(packets)))
        connection.commit()
        prompt = (PROMPTS / ("korean-review.txt" if review else "korean-label.txt" if stage.startswith("label") else "korean-question.txt")).read_text()
        try:
            raw = client.chat([{"role":"system", "content":prompt}, {"role":"user", "content":json_text({"items":packets})}],
                model=MODEL, request_id=request_id, output_schema=response_schema(review), audit_directory=output / "calls" / request_id)
            response = json.loads(raw["choices"][0]["message"]["content"])
            connection.execute("UPDATE calls SET response=? WHERE id=?", (json_text(response), request_id))
            connection.commit()
            found = validate(response, jobs, review=review)
            connection.execute("UPDATE calls SET state='completed' WHERE id=?", (request_id,))
            connection.commit()
            print(json_text({"stage":stage, "items":len(jobs), "calls_used":connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0], "max_calls":expected_budget}), flush=True)
            return found
        except BaseException as error:
            connection.execute("UPDATE calls SET state='failed_or_unknown',error=? WHERE id=?", (str(error), request_id))
            connection.commit()
            raise
    status, failure = "complete", None
    try:
        if client is None and expected_budget:
            from .codex_cli import CodexClient
            client = CodexClient()
        for kind, jobs in (("label", workset["label_jobs"]), ("question", workset["question_jobs"])):
            for offset in range(0, len(jobs), BATCH_SIZE):
                batch = jobs[offset:offset+BATCH_SIZE]
                packets = [model_packet(job, labels) for job in batch]
                generated = call(kind+"_generation", batch, packets, False)
                review_packets = [{**packet, "proposed_text":generated[packet["job_id"]]["text"]} for packet in packets]
                call(kind+"_review", batch, review_packets, True)
                with connection:
                    for job in batch:
                        text = generated[job["job_id"]]["text"]
                        connection.execute("INSERT OR REPLACE INTO results VALUES(?,?,?)", (job["job_id"], kind, text))
                        if kind == "label":
                            labels.update({uri:text for uri in job["uris"]})
        graph = load_graph(catalog)
        all_labels = structural_labels(graph, labels)
        questions = {}
        for job in workset["question_jobs"]:
            text = connection.execute("SELECT text FROM results WHERE job_id=?", (job["job_id"],)).fetchone()[0]
            questions[job["key"]] = {"text":text, "answer_type":"presence" if job["purpose"] in {"presence", "history"}
                else "duration" if job["attribute"] in {str(OW.TimeSinceOnset), str(OW.EpisodeDuration)} else "category",
                "affirmative":job["purpose"] in {"presence", "history"}, "interviewable":True, "reason":None}
        for entry in workset["entries"]:
            if entry["kind"] in {"Symptom", "ContextFactor", "ExamFinding", "ExamMethod"} and entry["question_status"] != "pending_clinical_question":
                questions[entry["uri"]] = {"text":"", "answer_type":"free_text", "affirmative":False,
                    "interviewable":False, "reason":entry["question_status"]}
        write(output / "all-labels.ko.json", all_labels)
        write(output / "all-questions.ko.json", questions)
        write(output / "labels.ko.json", {key:value for key,value in labels.items() if list(graph.objects(URIRef(key), RDF.type))})
        runtime_ids = {str(node) for node in graph.subjects(RDF.type, OW.Symptom)}
        write(output / "questions.ko.json", {key:value for key,value in questions.items() if key.split("|",1)[0] in runtime_ids})
        write(output / "provenance.json", {"workset_sha256":workset_sha, "entries":[{
            "uri":entry["uri"], "kind":entry["kind"], "korean_origin":entry["korean_origin"] or "model_translation",
            "korean_source":entry["korean_source"], "question_status":entry["question_status"],
            "evidence_id":entry["evidence_id"]} for entry in workset["entries"]],
            "catalog_manifest_sha256":workset['catalog_manifest_sha256'],
            "evidence_sha256":workset['evidence_sha256'], "structural_origin":"derived_expression"})
    except Exception as error:
        status, failure = "blocked", str(error)
    total = connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    accepted = dict(connection.execute("SELECT kind,COUNT(*) FROM results GROUP BY kind"))
    completed = dict(connection.execute("SELECT job_id,text FROM results"))
    write(output / "completed-labels.ko.json", labels)
    write(output / "completed-questions.ko.json", {job["key"]:completed[job["job_id"]] for job in workset["question_jobs"] if job["job_id"] in completed})
    coverage = [{"uri":entry["uri"], "kind":entry["kind"],
        "korean_origin":entry["korean_origin"] or ("model_translation" if entry["uri"] in labels else None),
        "korean_status":"complete" if entry["uri"] in labels else "unresolved",
        "question_status":entry["question_status"], "korean_source":entry["korean_source"]} for entry in workset["entries"]]
    write(output / "coverage.json", coverage)
    report = {"status":status, "failure":failure, "workset_sha256":workset_sha,
        "build_id":workset["build_id"], "model":MODEL, "provider":"docker_codex_cli",
        "label_jobs":len(workset["label_jobs"]), "question_jobs":len(workset["question_jobs"]),
        "accepted_jobs":accepted, "calls_this_run":total-before_calls, "calls_total":total, "max_calls":expected_budget,
        "official_source_labels":sum(entry["korean_origin"] == "Korean_SNOMED_CT" for entry in workset["entries"]),
        "model_translation_labels":sum(entry["korean_origin"] is None and entry["uri"] in labels for entry in workset["entries"]),
        "unresolved_lexical_labels":sum(entry["uri"] not in labels for entry in workset["entries"]),
        "unresolved_question_jobs":len(workset["question_jobs"])-accepted.get("question",0),
        "runtime_admission":"not_run", "independent_clinical_validation":"not_run",
        "automatic_retries":0, "next_day_auto_resume":False}
    write(output / "calls-summary.json", [{"request_id":row[0], "stage":row[1], "batch_sha256":row[2],
        "state":row[3], "request_sha256":digest(row[4]), "response_sha256":digest(row[5]) if row[5] else None,
        "error":row[6]} for row in connection.execute("SELECT * FROM calls ORDER BY rowid")])
    write(output / "report.json", report)
    connection.close()
    return report
