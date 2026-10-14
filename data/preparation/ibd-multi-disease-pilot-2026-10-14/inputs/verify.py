import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from Dev.ontology.vocabulary import ONTOLOGY, digest, encode
from Dev.ontology.workflow import validate_atomic, validate_conversion

out = Path(__file__).resolve().parent
spec = json.loads((out / "experiment.json").read_text())
prepared_raw = (out / "prepared.json").read_bytes()
prepared = json.loads(prepared_raw)
unit = spec["chosen_unit"]
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


check("fixed_two_call_contract", spec["maximum_model_calls"] == 2 and spec["new_document_draws"] == 0)
check("prepared_input_identity", digest(prepared_raw) == spec["prepared_sha256"])
check("runner_identity", digest((out / "run.py").read_bytes()) == spec["runner_sha256"])
check("selection_identity", digest((out / "source-selection.json").read_bytes()) == spec["selection_sha256"])
check("schema_identities", all(digest((ONTOLOGY / name).read_bytes()) == sha for name, sha in spec["schema_sha256"].items()))
check("offline_verification_bundle", all(json.loads((out / folder / "verification.json").read_text())["result"] == "pass"
                                        for folder in ("schema-check", "workflow-check")))
directories = sorted((out / "case-ibd").glob("call-*"))
check("exactly_two_sequential_calls", len(directories) == 2)
records = []
for index, directory in enumerate(directories):
    record = json.loads((directory / "execution.json").read_text())
    check(f"call_{index + 1}_complete_boundary", record["status"] == "completed" and record["returncode"] == 0
          and record["boundary_status"] == record["validation_status"] == "pass")
    check(f"call_{index + 1}_fixed_route_no_retries", record["model"] == "gpt-6-luna"
          and record["reasoning"] == "medium" and record["speed"] == "Standard"
          and record["invocations"] == 1 and record["automatic_retries"] == 0)
    check(f"call_{index + 1}_exact_response_and_prompt", digest((directory / "response.json").read_bytes()) == record["response_sha256"]
          and digest((directory / "prompt.txt").read_bytes()) == record["prompt_sha256"])
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    completions = [e for e in events if e["type"] == "turn.completed"]
    messages = [e["item"]["text"] for e in events if e["type"] == "item.completed" and e["item"]["type"] == "agent_message"]
    tools = [e for e in events if e["type"].startswith("item.") and e.get("item", {}).get("type") not in {"agent_message", "reasoning"}]
    check(f"call_{index + 1}_one_completion_zero_tools", len(completions) == 1 and not tools and record["model_tool_events"] == 0)
    check(f"call_{index + 1}_saved_response_matches_event", json.loads(messages[-1]) == json.loads((directory / "response.json").read_text()))
    try:
        os.killpg(record["process_group"], 0)
    except ProcessLookupError:
        check(f"call_{index + 1}_process_group_terminated", True)
    else:
        raise AssertionError("Pilot process group still exists")
    records.append(record)
check("stage_order_and_no_overlap", records[0]["stage"] == "atomic" and records[1]["stage"] == "conversion"
      and records[0]["finished_at"] <= records[1]["started_at"])
atomic_raw = (directories[0] / "response.json").read_bytes()
conversion_raw = (directories[1] / "response.json").read_bytes()
atomic = validate_atomic(prepared, unit["unit_id"], atomic_raw)
converted = validate_conversion(prepared, unit["unit_id"], atomic_raw, conversion_raw)
check("atomic_validation_replay", atomic == json.loads((directories[0] / "validated.json").read_text()))
check("conversion_validation_replay", converted == json.loads((directories[1] / "validated.json").read_text()))
check("group_context_in_review_packet", converted["group_context"] == prepared["selection"]["group_context"])
check("final_output_schema_unchanged", digest((ONTOLOGY / "extraction.schema.json").read_bytes())
      == json.loads((out / "before.sha256.json").read_text())["data/ontology/extraction.schema.json"])
patterns = converted["candidates"]["patterns"]
old = json.loads((out.parent / "statpearls-two-stage-pilot-10-2026-10-13/document-8/call-02-conversion/response.json").read_text())
old_pairs = {(p["disease"], p["target"]["term"]) for p in old["candidates"]["patterns"]}
new_pairs = {(p["disease"], p["target"]["term"]) for p in patterns}
definition = prepared["selection"]["group_context"]["evidence"][0]


def has_core_and_definition(evidence):
    return (any(e["start_line"] <= unit["start_line"] <= e["end_line"] for e in evidence)
            and any(e["start_line"] == definition["start_line"] and definition["quote"] in e["quote"] for e in evidence))


summary = {
    "result": "pass", "check_count": len(checks), "checks": checks,
    "model_calls": 2, "automatic_retries": 0, "model_tool_events": 0,
    "atomic_claim_count": len(atomic["claims"]),
    "relation_counts": {kind: len(items) for kind, items in converted["candidates"].items()},
    "patterns_by_disease": dict(Counter(p["disease"] for p in patterns)),
    "targets_by_disease": {d: sorted({p["target"]["term"] for p in patterns if p["disease"] == d}) for d in spec["topic_diseases"]},
    "conversion_exclusions": converted["excluded_claims"],
    "core_and_definition_quoted": {"atomic": sum(has_core_and_definition(c["evidence"]) for c in atomic["claims"]),
                                   "patterns": sum(has_core_and_definition(p["evidence"]) for p in patterns)},
    "zero_feature_pattern_count": sum(not p["features"] for p in patterns),
    "comparison": {"prior_pairs": sorted(old_pairs), "current_pairs": sorted(new_pairs),
                   "retained_prior_pairs": sorted(old_pairs & new_pairs), "added_pairs": sorted(new_pairs - old_pairs),
                   "missing_prior_pairs": sorted(old_pairs - new_pairs),
                   "interpretation": "Coverage observation for one fixed paragraph; no causal accuracy or corpus-performance claim"},
    "elapsed_seconds": round(sum(r["elapsed_seconds"] for r in records), 3),
    "usage": dict(sum((Counter(r["usage"]) for r in records), Counter())),
    "user_review": "not_run", "separate_agent_source_meaning_audit": "excluded_by_user",
    "clinical_accuracy": "not_run", "gold_recall": "not_run", "rdf_generation": "not_run",
    "rdf_admission": "not_run", "submission_admission": "not_run",
}
(out / "verification.json").write_text(encode(summary))
(out / "candidates.json").write_text(encode(converted["candidates"]))
(out / "review-packet.json").write_text(encode(converted))
print(encode({k: v for k, v in summary.items() if k not in {"checks", "comparison", "targets_by_disease"}}), end="")
