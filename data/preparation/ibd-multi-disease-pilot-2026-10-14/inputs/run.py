import json
import os
import signal
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from Dev.ontology.tools import GUIDELINES
from Dev.ontology.vocabulary import ONTOLOGY, digest, encode, load_vocabulary
from Dev.ontology.workflow import conversion_prompt, validate_atomic, validate_conversion


out = Path(__file__).resolve().parent
spec = json.loads((out / "experiment.json").read_text())
prepared_raw = (out / "prepared.json").read_bytes()
prepared = json.loads(prepared_raw)
stage = sys.argv[1]
if stage not in {"atomic", "conversion"}:
    raise SystemExit("Choose atomic or conversion")
settings = tomllib.loads(Path("/opt/ontology/codex-state/config.toml").read_text())
if (os.environ.get("CODEX_HOME") != "/opt/ontology/codex-state"
        or settings.get("forced_login_method") != "chatgpt" or not settings.get("forced_chatgpt_workspace_id")
        or settings.get("model") != "gpt-6-luna" or settings.get("model_reasoning_effort") != "medium"
        or settings.get("web_search") != "disabled" or settings.get("service_tier") not in {None, "default"}):
    raise SystemExit("Stop for account/model/configuration reconciliation; do not change settings")
if (digest(prepared_raw) != spec["prepared_sha256"]
        or load_vocabulary()["terms_sha256"] != spec["vocabulary_sha256"]
        or digest((GUIDELINES / "catalog.csv").read_bytes()) != spec["catalog_sha256"]):
    raise SystemExit("Stop for prepared input, vocabulary, or catalog drift")
for name, sha in spec["schema_sha256"].items():
    if digest((ONTOLOGY / name).read_bytes()) != sha:
        raise SystemExit("Stop for schema drift")
for name, sha in spec["workflow_input_sha256"].items():
    if digest((Path(__file__).resolve().parents[3] / "Dev/ontology" / name).read_bytes()) != sha:
        raise SystemExit("Stop for workflow/prompt drift")
unit_id = spec["chosen_unit"]["unit_id"]
existing = sorted((out / "case-ibd").glob("call-*"))
if len(existing) >= spec["maximum_model_calls"]:
    raise SystemExit("Stop at the fixed call budget")
if stage == "atomic":
    if existing:
        raise SystemExit("Preserve the prior first-stage attempt; no automatic retries")
    prompt = (out / "case-ibd/atomic-prompt.txt").read_bytes()
    if digest(prompt) != spec["atomic_prompt_sha256"]:
        raise SystemExit("Stop for first-stage prompt drift")
else:
    if len(existing) != 1:
        raise SystemExit("Require exactly one completed first-stage invocation")
    previous = json.loads((existing[0] / "execution.json").read_text())
    if previous["stage"] != "atomic" or any(previous[key] != "pass" for key in ("boundary_status", "validation_status")):
        raise SystemExit("Stop after the failed first-stage boundary")
    atomic_raw = (existing[0] / "response.json").read_bytes()
    if digest(atomic_raw) != previous["response_sha256"]:
        raise SystemExit("Stop for saved first-stage response drift")
    prompt = conversion_prompt(prepared, unit_id, atomic_raw).encode()
directory = out / "case-ibd" / f"call-{len(existing) + 1:02d}-{stage}"
directory.mkdir()
(directory / "prompt.txt").write_bytes(prompt)
schema = ONTOLOGY / ("atomic.schema.json" if stage == "atomic" else "conversion.schema.json")
command = ["codex", "exec", "--model", "gpt-6-luna", "--config", 'model_reasoning_effort="medium"',
           "--config", 'web_search="disabled"', "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
           "--cd", str(directory), "--output-schema", str(schema), "--json",
           "--output-last-message", str(directory / "response.json"), "-"]
record = {"call": len(existing) + 1, "case_id": "ibd-group-context", "stage": stage,
          "unit_id": unit_id, "started_at": datetime.now(timezone.utc).isoformat(),
          "status": "started", "boundary_status": "unknown", "validation_status": "not_run",
          "invocations": 1, "automatic_retries": 0, "model": "gpt-6-luna", "reasoning": "medium",
          "speed": "Standard", "timeout_seconds": 300, "command": command,
          "prompt_sha256": digest(prompt), "schema_sha256": digest(schema.read_bytes()),
          "prepared_sha256": spec["prepared_sha256"]}


def save():
    temporary = directory / "execution.tmp"
    temporary.write_text(encode(record))
    temporary.replace(directory / "execution.json")


def interrupt(signum, frame):
    raise InterruptedError("Stop the active pilot call")


signal.signal(signal.SIGTERM, interrupt)
signal.signal(signal.SIGINT, interrupt)
save()
started = time.monotonic()
with (directory / "events.jsonl").open("wb") as events, (directory / "stderr.log").open("wb") as errors:
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events, stderr=errors, start_new_session=True)
    record["process_group"] = process.pid
    save()
    try:
        process.communicate(input=prompt, timeout=300)
        record["status"] = "completed" if process.returncode == 0 else "failed"
    except (subprocess.TimeoutExpired, InterruptedError) as error:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        record["status"] = "timed_out" if isinstance(error, subprocess.TimeoutExpired) else "cancelled"
    record["returncode"] = process.returncode
record["elapsed_seconds"] = round(time.monotonic() - started, 3)
record["finished_at"] = datetime.now(timezone.utc).isoformat()
try:
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines() if line]
    completed = [event for event in events if event["type"] == "turn.completed"]
    messages = [event["item"]["text"] for event in events if event["type"] == "item.completed"
                and event["item"]["type"] == "agent_message"]
    tool_events = [event for event in events if event["type"].startswith("item.")
                   and event.get("item", {}).get("type") not in {"agent_message", "reasoning"}]
    record["model_tool_events"] = len(tool_events)
    if record["status"] != "completed" or len(completed) != 1 or not messages or tool_events:
        raise ValueError("Stop for invocation failure, missing completion, or model tool use")
    raw = (directory / "response.json").read_bytes()
    record["response_sha256"] = digest(raw)
    if json.loads(messages[-1]) != json.loads(raw):
        raise ValueError("Stop for raw-message and saved-response mismatch")
    record["boundary_status"] = "pass"
    record["usage"] = completed[0]["usage"]
    if stage == "atomic":
        validated = validate_atomic(prepared, unit_id, raw)
        record["claim_count"] = len(validated["claims"])
    else:
        validated = validate_conversion(prepared, unit_id, atomic_raw, raw)
        record["relation_counts"] = {key: len(value) for key, value in validated["candidates"].items()}
        record["excluded_claim_count"] = len(validated["excluded_claims"])
    (directory / "validated.json").write_text(encode(validated))
    record["validation_status"] = "pass"
except (ValueError, OSError, KeyError) as error:
    key = "boundary_status" if record["boundary_status"] != "pass" else "validation_status"
    record[key] = "fail"
    record["error"] = str(error)
    (directory / "failure.json").write_text(encode({"error": str(error), "whole_response_rejected": True}))
save()
print(encode({key: value for key, value in record.items() if key != "command"}), end="")
if record["boundary_status"] != "pass" or record["validation_status"] != "pass":
    raise SystemExit(2)
