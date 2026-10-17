import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time


def verify(submission, output, candidate=None):
    submission, output = submission.resolve(), output.resolve()
    sys.path.insert(0, str(submission))
    from knowledge.graph import OW, ClinicalKnowledge
    from knowledge.conditions import QuestionTemplate, ScoringPolicy, ReasoningPolicy
    from workflow.runtime import PreparedResources, TextConfig, prepare, consult
    from workflow.state.models import WorkflowState
    from nova_sdk import RECORD_FIELDS

    started = time.perf_counter()
    if candidate:
        candidate = candidate.resolve()
        korean_report = json.loads((candidate / 'korean/report.json').read_text())
        if korean_report['status'] != 'complete':
            report = {'status':'not_run', 'reason':'complete_reviewed_korean_assets_required',
                      'korean_failure':korean_report['failure'], 'runtime_admission':'not_run',
                      'actual_luna':'not_run', 'authenticated_sdk':'not_run'}
            output.mkdir(parents=True,exist_ok=True)
            (candidate / 'candidate-workflow.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(report,ensure_ascii=False,indent=2))
            return report
        sys.path.insert(0,str(submission.parent))
        from Dev.ontology.korean import load_graph
        graph=load_graph(candidate/'catalog')
        graph.parse(candidate/'preview/schema.ttl',format='turtle')
        texts=candidate/'korean'
        knowledge=ClinicalKnowledge(graph,
            questions={key:QuestionTemplate.model_validate(value) for key,value in json.loads((texts/'questions.ko.json').read_text()).items()},
            labels=json.loads((texts/'labels.ko.json').read_text()),
            policy=ScoringPolicy.model_validate_json((candidate/'preview/scoring_policy.json').read_text()),
            reasoning=ReasoningPolicy.model_validate_json((submission/'knowledge/reasoning_policy.json').read_text()))
        knowledge.validate_graph()
        resources=PreparedResources(knowledge,TextConfig.load())
    else:
        resources = prepare()
    elapsed = time.perf_counter() - started
    knowledge, config = resources.knowledge, resources.config
    manifest_path = candidate/'preview/manifest.json' if candidate else submission / "knowledge/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["preparation_status"] == ("preview_only" if candidate else "admitted")
    assert knowledge._profile_cache
    assert elapsed <= 600 and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= 8 * 1024 * 1024
    concepts = knowledge.concepts()
    assert all(c["id"] in knowledge.questions for c in concepts if c["kind"] == "Symptom")
    knowledge.validate_question_assets()
    original = frozenset(knowledge._graph)
    target, disease = str(OW.SymptomSnomedCT21522001), str(OW.SnomedCT65275009)
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
            self.session_id = "synthetic-source-candidate-" + ("numeric" if numeric else case_target.rsplit(":", 1)[-1])
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
            if content == config.texts.chief_question:
                q = {"purpose": "chief", "target_id": None, "attribute_id": None}
            elif content in {config.texts.provisional_education, config.texts.symptom_education,
                             config.texts.understanding_question, config.texts.correction_education}:
                q = {"purpose": "education", "target_id": None, "attribute_id": None}
            elif content == config.texts.open_question:
                q = {"purpose": "open_inquiry", "target_id": None, "attribute_id": None}
            else:
                q = next(({"purpose": "hpi", "target_id": c["id"], "attribute_id": attr}
                          for c in concepts if c["kind"] == "Symptom"
                          for attr in knowledge.get_symptom_attributes(c["id"])
                          if knowledge.question(attr, c["id"]) == content), None)
                q = q or {"purpose": "feature", "target_id": None, "attribute_id": None}
            import unicodedata
            assert unicodedata.normalize('NFC',content)==content and 1 <= len(content) <= 30
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
        case_started = time.perf_counter()
        result = consult(client, resources)
        state = WorkflowState.model_validate(result)
        (output / f"case-{i}.json").write_text(state.model_dump_json(indent=2))
        assert state.interaction.termination == "submitted" and len(client.submissions) == 1
        assert frozenset(knowledge._graph) == original
        if case_target == target:
            score = next(h.evidence_score for h in state.differential.hypotheses if h.disease_id == disease)
            assert score == 4
            assert state.case.diagnosis_kind == "disease"
            assert any(issue.startswith("missing_plan:") for issue in state.interaction.issues)
        else:
            assert state.case.diagnosis_kind == "symptom"
        assert state.session.usage["Education"].actions == 0
        assert state.session.usage["Education"].calls == 0
        assert not any(action["question"]["purpose"] == "education" for action in client.actions)
        assert state.interaction.submission_payload["note"]["P"]["education"] == ""
        note = state.interaction.submission_payload["note"]
        assert note["S"]["cc"].startswith("C.C: ")
        assert all(": " in line for fields in note.values() for text in fields.values() for line in text.splitlines())
        assert not any("가" <= char <= "힣" for text in note["S"].values() for char in text)
        assert state.case.diagnosis == knowledge.label(state.differential.selected_id or case_target, language="en")
        if numeric:
            hpi = state.interaction.submission_payload["note"]["S"]["hpi"]
            assert "2 months" in hpi
        for exchange in state.interaction.model_history:
            assert exchange["role"] in {"gateway", "terminology", "empathy"}
            if exchange["role"] in {"gateway", "terminology"}:
                metrics = exchange["parser_payload"]
                expanded = metrics["pass"] != "primary"
                assert metrics["vocabulary_count"] <= (1024 if expanded else 256)
                assert metrics["vocabulary_bytes"] <= (131072 if expanded else 32768)
        cases.append({"target": case_target, "numeric": numeric, "actions": len(client.actions), "model_calls": state.session.doctor_calls,
                      "diagnosis_kind": state.case.diagnosis_kind, "termination": state.interaction.termination,
                      "unresolved_records": sum(item.value is not None and item.value.status == "unknown" for _, item in state.case.entries()),
                      "scripted_consult_seconds": time.perf_counter() - case_started,
                      "question_generation_calls": sum(e["role"] == "doctor" for e in state.interaction.model_history),
                      "gateway_payload_bytes": sum(e.get("parser_payload", {}).get("payload_bytes", 0) for e in state.interaction.model_history),
                      "max_context_bytes": max((e.get("parser_payload", {}).get("context_bytes", 0) for e in state.interaction.model_history), default=0),
                      "pattern_evaluations": state.differential.pattern_evaluations,
                      "scoring_refreshes": state.differential.refreshes})
    report = {"status": "pass", "cases": cases, "prepare_seconds": elapsed,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "graph_triples": len(original), "associations": len(knowledge._profile_cache),
              "symptom_questions":sum(c['kind']=='Symptom' for c in concepts),
              "blocked_targets":sum(not q.interviewable for q in knowledge.questions.values()), "display_labels": len(knowledge.labels),
              "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              "runtime_root": str(submission), "network": "none", "patient_data": "synthetic", "model_responses": "scripted",
              "actual_luna": "not_run", "authenticated_sdk": "not_run", "diagnostic_performance": "not_run"}
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if candidate:
        report['runtime_admission']='not_run'
        report['candidate_injection']='isolated_test_only'
        (candidate/'candidate-workflow.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    verify(args.submission, args.output, args.candidate)
