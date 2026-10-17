"""Compare frozen pre-D38 and D38 runtimes in separate offline processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def worker(fixtures, output):
    sys.path.insert(0, str(fixtures))
    import test_workflow as f
    modern = hasattr(f.ClinicalReasoner, "evaluate_delta")
    flows = []
    for label, kwargs in (("positive_context", {}), ("negative_context", {"context": "아니요"}),
                          ("symptom_fallback", {"no_candidate": True})):
        client, resources = f.FakeSDK(**kwargs), f.resources()
        consultation = f.make_consultation(client, resources)
        initial = consultation.nova_session.initialize_case(client)
        started = time.perf_counter()
        invalid, revisions, simulations = [], [], 0
        result = initial
        for update in f.build_graph(consultation, resources.knowledge).stream(initial.model_dump(),
                {"recursion_limit": consultation.budget.graph_step_limit(initial)}, stream_mode="updates"):
            node, value = next(iter(update.items()))
            result = f.WorkflowState.model_validate(value)
            if node == "select_question" and result.interaction.selected:
                q = result.interaction.selected.question
                if q.attribute_id and q.kind == "SAY" and not consultation.planner.has_resolved_evidence(
                        result, q.target_id, observation=q.observation_id, episode=q.episode_id,
                        subject=q.subject, time_context=q.time_context):
                    invalid.append(q.semantic_key())
            if node == "refresh_after_input":
                revisions.append(result.differential.refreshes)
        elapsed = time.perf_counter() - started
        delivered = [e for e in result.interaction.history if e.delivered and e.question
                     and e.question.purpose not in {"chief", "open_inquiry", "empathy", "education", "clarification"}]
        keys = [e.question.semantic_key() for e in delivered]
        if modern:
            simulations = sum(e.question.assessment.get("selection", {}).get("simulations", 0) for e in delivered)
        acquired = {result.case.evidence_key(i.value) for _, i in result.case.current_entries()
                    if i.status == "done" and i.source_refs and i.value
                    and i.value.kind in {"symptom", "finding", "attribute", "context"}
                    and i.value.status in {"present", "absent"}}
        dimensions = {(i.value.kind, tuple(i.value.concept_ids), i.value.attribute_id, i.value.subject,
                       i.value.status, tuple(i.value.values), i.value.measurement.model_dump_json() if i.value.measurement else None)
                      for _, i in result.case.current_entries() if i.status == "done" and i.source_refs and i.value
                      and i.value.kind in {"symptom", "finding", "attribute", "context"}
                      and i.value.status in {"present", "absent"}}
        flows.append({"case": label, "shared_turn_budget": 50, "education": False,
            "actions": len(client.actions), "duplicate_questions": len(keys) - len(set(keys)),
            "attributes_without_presence": len(invalid), "obtained_typed_keys": len(acquired),
            "obtained_information_dimensions": len(dimensions),
            "candidate_count": len(result.differential.hypotheses), "diagnosis": result.case.diagnosis,
            "ranking": [{"disease": h.disease_id, "score": h.score,
                         "eligible": h in consultation.reasoner.supported_hypotheses(result)}
                        for h in result.differential.hypotheses],
            "elapsed_seconds": elapsed, "real_refreshes": result.differential.refreshes,
            "pattern_evaluations": result.differential.pattern_evaluations,
            "counterfactual_evaluations": simulations, "termination": result.interaction.termination})
        assert result.interaction.termination == "submitted"

    probes = []
    for status in ("absent", "unknown", "present"):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        f.add_v5_pattern(k, "conditionalProbe", f.OW.Other, [], applicability=[{
            "concept_id": str(f.OW.Context), "status": "present", "subject": "patient", "time_context": "current"}])
        f.record(state)
        f.record(state, "context", f.OW.Context, "context", status, "S.pmh")
        reasoner, planner = f.ClinicalReasoner(k), f.make_planner(k, f.CONFIG)
        reasoner.retrieve_candidates(state)
        spec = planner._spec(state, str(f.OW.Other), episode="episode1")
        before = {h.disease_id: h.score for h in state.differential.hypotheses}
        if modern:
            from workflow.rules.selection import answer_patch, QuestionEvaluation, question_key, QuestionPath
            from workflow.state.evidence import EvidenceIndex
            snapshot = reasoner.evaluate(EvidenceIndex.from_case(state.case), reasoner.anchor(state.case))
            path = QuestionPath((spec,), None, str(f.OW.Alpha), None, ("chief",))
            engine = QuestionEvaluation(reasoner, snapshot, list(before))
            assessment = engine.assess({question_key(spec): spec}, [path])[question_key(spec)]
            predicted = reasoner.evaluate_delta(snapshot, (answer_patch(spec),))
            expected = {h.disease_id: h.score - before.get(h.disease_id, 0) for h in predicted.hypotheses}
            utility = assessment["utility"]
        else:
            matches = {}
            for match in state.differential.pattern_matches.values():
                matches.setdefault(match.pattern_id, []).append(match)
            vector = planner._value(state, spec, matches, {})
            utility, expected = vector, None
        f.record(state, "answer", f.OW.Other, field="S.ros")
        state.case.get("answer").value.observation_id = spec["observation_id"]
        reasoner.refresh_hypotheses(state, force=True)
        actual = {h.disease_id: h.score - before.get(h.disease_id, 0) for h in state.differential.hypotheses}
        probes.append({"prerequisite": status, "selection_value": utility,
                       "predicted_positive_delta": expected, "actual_positive_delta": actual})
        if modern:
            assert expected == actual
            if status != "present":
                assert utility == 0 and not any(actual.values())
    output.write_text(json.dumps({"algorithm": "d38.1" if modern else "pre_d38",
        "fixture_ttl_sha256": hashlib.sha256(f.TTL.encode()).hexdigest(),
        "source_scoring_sha256": hashlib.sha256((f.COPY / "knowledge/scoring_policy.json").read_bytes()).hexdigest(),
        "flows": flows, "prerequisite_probes": probes}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-submission", type=Path)
    parser.add_argument("--baseline-fixtures", type=Path)
    parser.add_argument("--submission", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-fixtures", type=Path)
    args = parser.parse_args()
    if args.worker_fixtures:
        worker(args.worker_fixtures, args.output)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    for name, submission, fixtures in (("baseline", args.baseline_submission, args.baseline_fixtures),
            ("d38", args.submission, Path(__file__).resolve().parent)):
        env = {**os.environ, "ONTOWARD_TEST_SUBMISSION": str(submission),
               "ONTOWARD_TEST_OUTPUT": str(args.output / (name + "-fixtures"))}
        subprocess.run([sys.executable, "-B", __file__, "--worker-fixtures", str(fixtures),
            "--output", str(args.output / (name + ".json"))], env=env, check=True, timeout=180)
    old, new = [json.loads((args.output / (name + ".json")).read_text()) for name in ("baseline", "d38")]
    assert old["fixture_ttl_sha256"] == new["fixture_ttl_sha256"]
    assert old["source_scoring_sha256"] == new["source_scoring_sha256"]
    report = {"status": "pass", "baseline": old, "d38": new, "network": "none",
        "patient_inputs": "identical deterministic source-shaped synthetic fixtures; no public-case answers",
        "scope": "three complete consultations and three controlled prerequisite counterexamples",
        "limitations": ["synthetic cases do not measure clinical accuracy", "timings are local observations",
                       "old heuristic has no counterfactual evaluation count or calibrated score interpretation"]}
    (args.output / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"status": "pass", "cases_per_algorithm": len(new["flows"]), "probes_per_algorithm": 3}))


if __name__ == "__main__":
    main()
