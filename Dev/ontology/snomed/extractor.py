from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import ROOT, digest, read, workspace_path, write

MODEL = "openai/gpt-6.1-sol"
REASONING = "medium"
MAX_TOKENS = 4000
MAX_BATCH = 5
SDK_SHA256 = "c6238ac466abc5b99b3e80de9ace2c7a54b51f7efc8d8a671d1c08bb0476f00d"
SDK_PATH = Path(os.environ.get("ONTOWARD_NOVA_SDK", "/opt/ontoward-sdk/nova_sdk.py"))
PROMPTS = {"vocabulary": ROOT / "Dev/ontology/snomed/prompts/vocabulary.txt",
           "projection": ROOT / "Dev/ontology/snomed/prompts/projection.txt"}


def kst_day():
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


@contextmanager
def exclusive_lock(path):
    lock = workspace_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class CallLedger:
    def __init__(self, path):
        self.path = workspace_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS attempts (
            request_id TEXT PRIMARY KEY, day TEXT NOT NULL, cache_key TEXT NOT NULL UNIQUE,
            dataset_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
            request_path TEXT NOT NULL, response_path TEXT, usage_json TEXT, error_code TEXT
        )""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS attempts_by_day ON attempts(day)")

    def close(self):
        self.connection.close()

    def count(self, day):
        return self.connection.execute("SELECT COUNT(*) FROM attempts WHERE day=?", (day,)).fetchone()[0]

    def cached(self, cache_key):
        row = self.connection.execute("SELECT status,response_path FROM attempts WHERE cache_key=?", (cache_key,)).fetchone()
        if row is None:
            return None
        status, response_path = row
        if status != "success" or not response_path:
            raise RuntimeError(f"Existing call is {status}; automatic replay is disabled")
        value = read(workspace_path(ROOT / response_path))
        if value.get("response_sha256") != digest(value.get("content", "")):
            raise RuntimeError("Cached NOVA response failed its stored content hash")
        return value["content"]

    def reserve(self, request_id, day, cache_key, dataset_id, stage, request_path):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                                    (request_id, day, cache_key, dataset_id, stage, "pending",
                                     str(request_path.relative_to(ROOT)), None, None, None))
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def finish(self, request_id, status, response_path=None, usage=None, error_code=None):
        self.connection.execute("UPDATE attempts SET status=?,response_path=?,usage_json=?,error_code=? WHERE request_id=?",
                                (status, response_path, json.dumps(usage, sort_keys=True) if usage is not None else None,
                                 error_code, request_id))

    def report(self, day):
        rows = self.connection.execute("SELECT status,COUNT(*) FROM attempts WHERE day=? GROUP BY status ORDER BY status", (day,))
        return {status: count for status, count in rows}


def schema_for(stage):
    from .models import ProjectionResponse, VocabularyResponse
    model = VocabularyResponse if stage == "vocabulary" else ProjectionResponse
    return model.model_json_schema()


def sdk_client():
    with SDK_PATH.open("rb") as stream:
        sdk_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if sdk_hash != SDK_SHA256:
        raise RuntimeError("The read-only NOVA SDK copy does not match its pinned SHA-256")
    if os.getenv("NOVA_SESSION_ID"):
        raise RuntimeError("Preparation calls must not inherit a NOVA session ID")
    token = os.environ.get("NOVA_DEV_KEY", "")
    api_base = os.environ.get("NOVA_API_BASE", "")
    if not token or not api_base:
        raise RuntimeError("Live extraction requires NOVA_DEV_KEY and NOVA_API_BASE")
    sys.path.insert(0, str(SDK_PATH.parent))
    from nova_sdk import Client
    client = create_sessionless_client(Client, token, api_base)
    return client


def create_sessionless_client(client_type, token, api_base):
    client = client_type(token=token, api_base=api_base, sample=False)
    if client.session_id:
        raise RuntimeError("NOVA SDK client unexpectedly has a session")
    return client


def sdk_request(client, messages, request_id):
    return client.chat(messages, model=MODEL, reasoning_effort=REASONING,
                       max_tokens=MAX_TOKENS, request_id=request_id)


def batches(envelope, size=MAX_BATCH):
    if size != MAX_BATCH:
        raise ValueError("The live packet batch size is fixed at five")
    packets = envelope.get("packets")
    if not isinstance(packets, list):
        raise ValueError("Extract requires a packet envelope")
    return [packets[index:index + size] for index in range(0, len(packets), size)]


def extract(rf2, stage, envelope, output_dir, *, live=False, max_calls=None, daily_remaining=None,
            ledger_path=None, call=None, registry=None):
    from .project import project
    from .vocabulary import validate_packets, verify_seal

    if stage not in PROMPTS:
        raise ValueError("Stage must be vocabulary or projection")
    if envelope.get("dataset_id") != rf2.dataset_id:
        raise ValueError("Packets belong to another imported RF2 release")
    verify_seal(envelope)
    validate_packets(rf2, envelope)
    if stage == "vocabulary" and envelope.get("stage") != "vocabulary":
        raise ValueError("Vocabulary calls require vocabulary expansion packets")
    if stage == "projection":
        if registry is None or envelope.get("stage") != "projection" or envelope != project(rf2, registry):
            raise ValueError("Projection calls require canonical packets from the frozen vocabulary")
    output_dir = workspace_path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Extraction output must be a new or empty directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt = PROMPTS[stage].read_text(encoding="utf-8")
    schema = schema_for(stage)
    settings = {"model": MODEL, "reasoning_effort": REASONING, "max_tokens": MAX_TOKENS,
                "temperature": "omitted", "batch_size": MAX_BATCH}
    call_batches = batches(envelope)
    if not live:
        dry = [{"batch": index, "packets": packet_batch, "model_settings": settings}
               for index, packet_batch in enumerate(call_batches)]
        write(output_dir / "dry-run.json", {"mode": "dry_run", "dataset_id": rf2.dataset_id,
                                              "stage": stage, "calls_made": 0, "batches": dry,
                                              "prompt_sha256": digest(prompt), "schema_sha256": digest(schema)})
        return {"mode": "dry_run", "batches": len(dry), "calls_made": 0}
    if max_calls is None or daily_remaining is None or not 0 <= max_calls <= 100 or not 0 <= daily_remaining <= 100:
        raise ValueError("Live extraction requires explicit --max-calls and --daily-remaining values in 0..100")
    effective_cap = min(100, max_calls, daily_remaining)
    ledger_path = workspace_path(ledger_path or ROOT / "data/preparation/snomed/call-ledger.sqlite")
    client = None
    if call is None:
        client = sdk_client()
        call = lambda messages, request_id: sdk_request(client, messages, request_id)
    ledger = CallLedger(ledger_path)
    requests_dir, responses_dir = output_dir / "requests", output_dir / "responses"
    requests_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)
    lock_path = ledger_path.with_suffix(".lock")
    result = []
    calls_made = 0
    try:
        with exclusive_lock(lock_path):
            run_day = kst_day()
            for index, packet_batch in enumerate(call_batches):
                if kst_day() != run_day:
                    raise RuntimeError("KST day changed during extraction; stop instead of resuming automatically")
                day = run_day
                batch_input = {"stage": stage, "dataset_id": rf2.dataset_id,
                               "registry_sha256": envelope.get("registry_sha256"),
                               "input_sha256": envelope.get("sha256"), "packets": packet_batch}
                cache_key = digest({"input": batch_input, "prompt_sha256": digest(prompt),
                                    "schema_sha256": digest(schema), "settings": settings})
                cached = ledger.cached(cache_key)
                if cached is not None:
                    try:
                        result.append(json.loads(cached))
                    except (ValueError, TypeError) as exc:
                        raise RuntimeError("Cached NOVA response is not valid JSON; no retry was made") from exc
                    continue
                if ledger.count(day) >= effective_cap:
                    raise RuntimeError(f"Declared KST daily call allowance exhausted: {ledger.report(day)}")
                request_id = str(uuid.uuid4())
                request_record = {"request_id": request_id, "cache_key": cache_key, "dataset_id": rf2.dataset_id,
                                  "stage": stage, "input": batch_input, "prompt_sha256": digest(prompt),
                                  "schema_sha256": digest(schema), "settings": settings, "status": "prepared"}
                request_path = requests_dir / f"{request_id}.json"
                write(request_path, request_record)
                ledger.reserve(request_id, day, cache_key, rf2.dataset_id, stage, request_path)
                messages = [{"role": "system", "content": prompt + "\nJSON Schema:\n" + json.dumps(schema, ensure_ascii=False)},
                            {"role": "user", "content": json.dumps(batch_input, ensure_ascii=False, sort_keys=True)}]
                try:
                    calls_made += 1
                    reply = call(messages, request_id)
                except BaseException as exc:
                    unknown = getattr(exc, "code", "") in {"API_UNAVAILABLE", "TIMEOUT"}
                    ledger.finish(request_id, "unknown" if unknown else "api_error", error_code=getattr(exc, "code", type(exc).__name__))
                    raise RuntimeError("NOVA call failed; the request is retained and will not be retried") from exc
                raw_content = None
                try:
                    raw_content = reply["choices"][0]["message"]["content"]
                    if not isinstance(raw_content, str):
                        raise TypeError("NOVA content is not text")
                except (KeyError, IndexError, TypeError) as exc:
                    raw_content = json.dumps(reply, ensure_ascii=False, sort_keys=True)
                response_path = responses_dir / f"{request_id}.json"
                write(response_path, {"request_id": request_id, "cache_key": cache_key, "raw_reply": reply,
                                      "content": raw_content, "response_sha256": digest(raw_content),
                                      "usage": reply.get("usage") if isinstance(reply, dict) else None})
                usage = reply.get("usage") if isinstance(reply, dict) else None
                ledger.finish(request_id, "success", str(response_path.relative_to(ROOT)), usage)
                request_record["status"] = "response_received"
                write(request_path, request_record)
                try:
                    parsed = json.loads(raw_content)
                    if not isinstance(parsed, dict) or not isinstance(parsed.get("decisions"), list):
                        raise ValueError("Expected a JSON object with a decisions array")
                    result.append(parsed)
                except (ValueError, TypeError) as exc:
                    raise RuntimeError("NOVA response was preserved but is not valid JSON; no retry was made") from exc
    finally:
        ledger.close()
    combined = {"decisions": [decision for part in result for decision in part.get("decisions", [])]}
    write(output_dir / "response.json", combined)
    return {"mode": "live", "batches": len(call_batches), "calls_made": calls_made,
            "daily_ledger": str(ledger_path.relative_to(ROOT)), "call_statuses": ledger_report(ledger_path)}


def ledger_report(path):
    ledger = CallLedger(path)
    try:
        return ledger.report(kst_day())
    finally:
        ledger.close()
