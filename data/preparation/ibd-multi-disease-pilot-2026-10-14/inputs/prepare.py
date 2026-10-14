import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from Dev.ontology.tools import GUIDELINES
from Dev.ontology.vocabulary import ONTOLOGY, digest, encode, load_vocabulary
from Dev.ontology.workflow import atomic_prompt, prepare

out = Path(__file__).resolve().parent
if (out / "experiment.json").exists():
    raise SystemExit("Preserve the fixed pilot inputs")
for folder in ("schema-check", "workflow-check"):
    if json.loads((out / folder / "verification.json").read_text())["result"] != "pass":
        raise SystemExit("Require the complete offline verification bundle")
selection = json.loads((out / "source-selection.json").read_text())
prepared = prepare(selection)
unit = next(u for u in prepared["units"] if u["start_line"] == u["end_line"] == 59)
previous = out.parent / "statpearls-two-stage-pilot-10-2026-10-13"
old = json.loads((previous / "prepared.json").read_text())
old_unit = next(u for u in old["units"] if u["unit_id"] == unit["unit_id"])
if old["source"] != prepared["source"] or any(old_unit[k] != unit[k] for k in old_unit):
    raise SystemExit("Require the identical prior source and core unit")
(out / "prepared.json").write_text(encode(prepared))
case = out / "case-ibd"
case.mkdir()
prompt = atomic_prompt(prepared, unit["unit_id"]).encode()
(case / "atomic-prompt.txt").write_bytes(prompt)
spec = {
    "decision": "D09", "case_id": "ibd-group-context", "workflow_version": 2,
    "document": selection["document"], "source_sha256": selection["sha256"],
    "chosen_unit": unit, "group_definition_lines": [13],
    "topic_diseases": selection["topic_diseases"], "maximum_model_calls": 2,
    "model": "gpt-6-luna", "reasoning": "medium", "speed": "Standard",
    "timeout_seconds_per_call": 300, "automatic_retries": 0, "automatic_resume": False,
    "web_search": "disabled", "model_tools_allowed": False, "new_document_draws": 0,
    "prepared_sha256": digest((out / "prepared.json").read_bytes()),
    "selection_sha256": digest((out / "source-selection.json").read_bytes()),
    "atomic_prompt_sha256": digest(prompt),
    "vocabulary_sha256": load_vocabulary()["terms_sha256"],
    "catalog_sha256": digest((GUIDELINES / "catalog.csv").read_bytes()),
    "schema_sha256": {p.name: digest(p.read_bytes()) for p in sorted(ONTOLOGY.glob("*.schema.json"))},
    "workflow_input_sha256": {name: digest((Path(__file__).resolve().parents[3] / "Dev/ontology" / name).read_bytes())
        for name in ("workflow.py", "models.py", "tools.py", "vocabulary.py", "atomic_prompt.md", "conversion_prompt.md")},
    "runner_sha256": digest((out / "run.py").read_bytes()),
    "baseline_prepared_sha256": digest((previous / "prepared.json").read_bytes()),
    "separate_agent_source_meaning_audit": "excluded_by_user", "user_review": "not_run",
    "rdf_generation": "not_run", "rdf_admission": "not_run", "submission_admission": "not_run",
}
(out / "experiment.json").write_text(encode(spec))
print(encode({"status": "inputs_fixed", "source": spec["document"], "unit_id": unit["unit_id"],
              "topics": spec["topic_diseases"], "maximum_model_calls": 2}), end="")
