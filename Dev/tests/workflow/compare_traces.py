"""Compare full node states and SDK requests with a preserved pre-refactor checkout."""
import argparse
import copy
from contextlib import ExitStack
from datetime import datetime, timezone
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from uuid import UUID


NODE_NAMES = {
    "gateway": "process_input", "refresh": "refresh_after_input", "enter": "enter_session",
    "budget": "check_budget", "select": "select_question", "render": "frame_action",
    "validate": "validate_action", "action_budget": "recheck_action_budget",
    "execute": "execute_action", "advance": "advance_session", "soap": "build_soap",
    "submit": "submit_diagnosis",
}
SCENARIOS = {
    "normal": {}, "negative_context": {"context": "아니요"},
    "symptom_fallback": {"no_candidate": True}, "exam_refusal": {"refusal": True},
    "unknown_action": {"unknown_action": True}, "unknown_submission": {"submit_status": "pending"},
    "submission_timeout": {"submit_status": "timeout"}, "malformed_input": {"malformed": True},
    "transient_model": {}, "response_format": {}, "soap_repair": {}, "closed": {}, "expired": {},
}


def capture(mode, baseline, output):
    output.mkdir(parents=True, exist_ok=True)
    os.environ["ONTOWARD_TEST_OUTPUT"] = str(output / "fixtures")
    source = baseline / "verify.py" if mode == "baseline" else Path(__file__).with_name("test_workflow.py")
    spec = importlib.util.spec_from_file_location("trace_fixtures", source)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixed = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    traces = {}
    for name, options in SCENARIOS.items():
        ids = itertools.count(1)
        next_uuid = lambda: UUID(int=next(ids))
        wire, delays = [], []
        with ExitStack() as stack:
            stack.enter_context(patch.object(fixture, "datetime", FixedDatetime))
            if mode == "baseline":
                stack.enter_context(patch("agents.state.datetime", FixedDatetime))
                stack.enter_context(patch("agents.transport.time.sleep", delays.append))
                for module in ("interview", "interface", "model", "submission"):
                    stack.enter_context(patch(f"agents.{module}.uuid4", next_uuid))
            client = fixture.FakeSDK(**options)
            if name == "closed":
                client.status = "closed"
            if name == "expired":
                client.deadline = fixed
            injected = {"transient_model": ("chat", "REQUEST_PENDING"),
                        "response_format": ("say", "PATIENT_RESPONSE_INVALID"),
                        "soap_repair": ("diagnose", "INVALID_RECORD_FIELDS")}.get(name)
            for method in ("session", "chat", "say", "exam", "diagnose"):
                original = getattr(client, method)
                def invoke(*args, _method=method, _original=original, **kwargs):
                    entry = {"method": _method, "args": copy.deepcopy(args), "payload": copy.deepcopy(kwargs), "timeout": client.timeout}
                    wire.append(entry)
                    try:
                        if injected and _method == injected[0] and sum(row["method"] == _method for row in wire) == 1:
                            raise fixture.NovaError(injected[1])
                        result = _original(*args, **kwargs)
                        entry["response"] = copy.deepcopy(result)
                        return result
                    except fixture.NovaError as error:
                        entry["error"] = error.code
                        raise
                setattr(client, method, invoke)
            resources = fixture.resources()
            if mode == "baseline":
                coordinator = fixture.ConsultationWorkflow(client, resources)
                state = coordinator.session.initialize_case(client)
                graph = coordinator.compile()
            else:
                coordinator = fixture.assemble_consultation(client, resources, now=lambda: fixed,
                    sleep=delays.append, new_request_id=lambda: str(next_uuid()))
                state = coordinator.nova_session.initialize_case(client)
                graph = fixture.build_graph(coordinator, resources.knowledge)
            updates = []
            for update in graph.stream(state.model_dump(), {"recursion_limit": 1400}, stream_mode="updates"):
                updates.append({NODE_NAMES.get(key, key): value for key, value in update.items()})
            traces[name] = {"initial": state.model_dump(mode="json"), "nodes": updates, "wire": wire, "delays": delays}
    data = {"state_schema": fixture.WorkflowState.model_json_schema(),
            "parser_schema": fixture.ParsedInput.model_json_schema(), "scenarios": traces}
    (output / "traces.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def first_difference(left, right, path="$"):
    if type(left) is not type(right):
        return path
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return path + ".keys"
        for key in left:
            found = first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
    elif isinstance(left, list):
        if len(left) != len(right):
            return path + ".length"
        for index, (a, b) in enumerate(zip(left, right)):
            found = first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
    elif left != right:
        return path
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", choices=("baseline", "current"))
    args = parser.parse_args()
    if args.capture:
        capture(args.capture, args.baseline, args.output)
        return
    for mode in ("baseline", "current"):
        subprocess.run([sys.executable, __file__, "--baseline", str(args.baseline), "--output", str(args.output / mode),
                        "--capture", mode], check=True, env={**os.environ, "PYTHONHASHSEED": "0"})
    left, right = [json.loads((args.output / mode / "traces.json").read_text()) for mode in ("baseline", "current")]
    differences = {key: first_difference(left[key], right[key]) for key in ("state_schema", "parser_schema")}
    differences.update({name: first_difference(left["scenarios"][name], right["scenarios"][name]) for name in SCENARIOS})
    report = {"scenarios": len(SCENARIOS), "differences": {k: v for k, v in differences.items() if v},
              "node_updates": sum(len(value["nodes"]) for value in right["scenarios"].values())}
    (args.output / "comparison.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    if report["differences"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
