import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time


def verify(submission, output):
    submission, output = submission.resolve(), output.resolve()
    sys.path.insert(0, str(submission))
    from knowledge.graph import OW
    from workflow.runtime import prepare, consult
    from workflow.state.models import WorkflowState
    from nova_sdk import RECORD_FIELDS

    started = time.perf_counter()
    resources = prepare()
    elapsed = time.perf_counter() - started
    knowledge, config = resources.knowledge, resources.config
    manifest_path = submission / "knowledge/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["preparation_status"] == "admitted"
    assert manifest["build_id"] == "b4954e33d5c04f4d76949149d9bf6affec1d2ab8c4b34fa99085003933d346aa"
    assert len(knowledge._profile_cache) == 9400 and len(knowledge._graph) == 96017
    assert elapsed <= 600 and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= 8 * 1024 * 1024
    concepts = knowledge.concepts()
    assert sum(c["kind"] == "Symptom" for c in concepts) == 490
    assert sum(c["kind"] == "FindingAttribute" for c in concepts) == 16
    assert not any(c["kind"] in {"ExamFinding", "ContextFactor"} for c in concepts)
    assert all(knowledge.question(c["id"], c["id"]) for c in concepts if c["kind"] == "Symptom")
    knowledge.validate_question_assets()
    original = frozenset(knowledge._graph)
    target, disease = str(OW.AbdominalPain), str(OW.SnomedCT65275009)
    profiles = [p for p in knowledge.get_disease_patterns(disease) if p.target == target]
    upper = next(p for p in profiles if p.score == 1 and len([f for f in knowledge.get_pattern_features(p.id) if f.expected]) == 1
                 and all(not f.expected or f.attribute == str(OW.Location) for f in knowledge.get_pattern_features(p.id)))
    detailed = next(p for p in profiles if p.score == 4 and knowledge.pattern_refines(p.id, upper.id))
    locations = [f.expected.concept for f in knowledge.get_pattern_features(detailed.id) if f.expected and f.attribute == str(OW.Location)]
    assert len(locations) >= 2

    class ScriptedSDK:
        timeout = 120

        def __init__(self, case_target, numeric=False):
            self.target, self.numeric = case_target, numeric
            self.session_id = "synthetic-admitted-" + ("numeric" if numeric else case_target.rsplit(":", 1)[-1])
            self.remaining, self.spoken_question = 50, None
            self.actions, self.submissions = [], []
            self.deadline = datetime.now(timezone.utc) + timedelta(minutes=25)

        def session(self):
            return {"session_id": self.session_id, "status": "active", "deadline": self.deadline.isoformat(),
                    "turns_remaining": self.remaining, "initial": {"opening": knowledge.label(self.target), "vital_signs": {"pulse": 80}},
                    "allowed_actions": ["SAY", "EXAM", "DIAGNOSE"]}

        @staticmethod
        def completion(content):
            return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 20, "completion_tokens": 10}}

        def chat(self, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            q, text = payload["question"], payload.get("input")
            if messages[0]["content"] == config.doctor_prompt:
                self.spoken_question = q
                return self.completion(q["text"])
            if payload["parser_pass"] == "expansion":
                return self.completion('{"facts":[]}')
            value = {"kind": "symptom", "text": text, "status": "present", "concept_ids": [self.target],
                     "subject": "patient", "time_context": "current", "observation_id": "synthetic-observation", "episode_id": "synthetic-episode"}
            field = "S.cc"
            if q and q["attribute_id"]:
                value.update(kind="attribute", concept_ids=[q["target_id"]], attribute_id=q["attribute_id"],
                             observation_id=q["observation_id"], episode_id=q["episode_id"])
                field = q["field"]
                if q["attribute_id"] == str(OW.Location):
                    value["values"] = locations
                elif q["attribute_id"] == str(OW.TimeSinceOnset):
                    value["measurement"] = {"kind": "quantity", "value": 2.0, "unit": "month", "operator": "eq"}
                elif q["attribute_id"] == str(OW.EpisodeDuration):
                    value["measurement"] = {"kind": "interval", "lower": 1.0, "upper": 2.0, "unit": "h", "upper_inclusive": False}
            fact = {"field": field, "quote": text, "value": value}
            if q:
                fact["record_id"] = q["item_id"]
            return self.completion(json.dumps({"facts": [fact]}, ensure_ascii=False))

        def say(self, content, request_id):
            q = self.spoken_question
            assert q and 1 <= len(content) <= 30
            self.remaining -= 1
            if q["purpose"] == "chief":
                answer = knowledge.label(self.target)
            elif q["target_id"] == self.target and q["attribute_id"] == str(OW.Location) and self.target == target:
                answer = ", ".join(knowledge.label(value) for value in locations)
            elif self.numeric and q["target_id"] == self.target and q["attribute_id"] == str(OW.TimeSinceOnset):
                answer = "2개월 전부터요"
            elif self.numeric and q["target_id"] == self.target and q["attribute_id"] == str(OW.EpisodeDuration):
                answer = "한 번에 1시간에서 2시간 미만이요"
            elif q["purpose"] == "education":
                answer = "알겠습니다"
            else:
                answer = "모르겠어요"
            self.actions.append({"question": q, "content": content, "answer": answer, "request_id": request_id})
            return {"status": "OK", "turn": 50 - self.remaining, "turns_remaining": self.remaining, "content": answer}

        def exam(self, **kwargs):
            raise AssertionError("This admitted batch has no examination methods")

        def diagnose(self, **payload):
            assert set(payload) == {"note", "diagnosis", "request_id"}
            assert set(payload["note"]) == set(RECORD_FIELDS)
            assert all(set(payload["note"][section]) == set(fields) for section, fields in RECORD_FIELDS.items())
            assert payload["note"]["O"]["tests"] == ""
            assert all(isinstance(text, str) for section in payload["note"].values() for text in section.values())
            assert payload["diagnosis"]
            self.submissions.append(payload)
            return {"status": "completed"}

    output.mkdir(parents=True, exist_ok=True)
    cases = []
    selected_cases = [(target, False), (target, True)]
    fallback = next((c["id"] for c in concepts if c["kind"] == "Symptom" and knowledge.get_patterns_by_target(c["id"])
                     and all(p.applicability or any(f.expected for f in knowledge.get_pattern_features(p.id))
                             for p in knowledge.get_patterns_by_target(c["id"]))), None)
    if fallback:
        selected_cases.append((fallback, False))
    for i, (case_target, numeric) in enumerate(selected_cases):
        client = ScriptedSDK(case_target, numeric)
        result = consult(client, resources)
        state = WorkflowState.model_validate(result)
        assert state.interaction.termination == "submitted" and len(client.submissions) == 1
        assert frozenset(knowledge._graph) == original
        if case_target == target:
            score = next(h.evidence_score for h in state.differential.hypotheses if h.disease_id == disease)
            assert score == 4
            assert state.case.diagnosis_kind == "disease"
            assert any(issue.startswith("missing_plan:") for issue in state.interaction.issues)
        else:
            assert state.case.diagnosis_kind == "symptom"
            assert any(action["question"]["purpose"] == "education" for action in client.actions)
        if numeric:
            hpi = state.interaction.submission_payload["note"]["S"]["hpi"]
            assert "2 개월" in hpi
        for exchange in state.interaction.model_history:
            if exchange["role"] == "gateway":
                metrics = exchange["parser_payload"]
                expanded = metrics["pass"] == "expansion"
                assert metrics["vocabulary_count"] <= (1024 if expanded else 256)
                assert metrics["vocabulary_bytes"] <= (131072 if expanded else 32768)
        (output / f"case-{i}.json").write_text(state.model_dump_json(indent=2))
        cases.append({"target": case_target, "numeric": numeric, "actions": len(client.actions), "model_calls": state.session.doctor_calls,
                      "diagnosis_kind": state.case.diagnosis_kind, "termination": state.interaction.termination,
                      "unresolved_records": sum(item.value is not None and item.value.status == "unknown" for _, item in state.case.entries())})
    report = {"status": "pass", "cases": cases, "prepare_seconds": elapsed,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "graph_triples": len(original), "associations": len(knowledge._profile_cache), "symptom_questions": 490,
              "attribute_templates": 16, "display_labels": len(knowledge.labels),
              "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              "runtime_root": str(submission), "network": "none", "patient_data": "synthetic", "model_responses": "scripted",
              "actual_luna": "not_run", "authenticated_sdk": "not_run", "diagnostic_performance": "not_run"}
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.submission, args.output)
