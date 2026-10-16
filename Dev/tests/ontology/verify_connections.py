import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "submission"))

from rdflib import Graph, Literal, RDF, RDFS, URIRef
from Dev.ontology.admission import candidate_set, validated_selection
from Dev.ontology.database import SourceDatabase, file_hash
from Dev.ontology.v5 import OW, digest, write
from knowledge.conditions import QuestionTemplate
from knowledge.graph import ClinicalKnowledge
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.runtime import PreparedResources, TextConfig, assemble_consultation, consult, prepare
from workflow.state.models import ClinicalValue, RecordItem, SessionContext, WorkflowState


def verify(directory):
    checks = []
    def require(value, name):
        if not value:
            raise AssertionError(name)
        checks.append(name)

    started = time.perf_counter()
    directory = directory.resolve()
    db = SourceDatabase(directory / "ontology.sqlite3", readonly=True)
    receipt = json.loads((directory / "review-approved.json").read_text())
    require(receipt["candidate_set_sha256"] == digest(candidate_set(db)), "approved_candidate_set_matches_exact_sqlite_projection")
    require(db.connection.execute("PRAGMA quick_check").fetchone()[0] == "ok", "projection_sqlite_integrity")
    require(all(file_hash(ROOT / "Dev/ontology" / name) == sha for name, sha in db.meta("identity")["generator_files"].items()),
            "executed_generator_files_match_the_admitted_build")
    audit = json.loads((directory / "preview/sources.json").read_text())
    require(audit["database"] == (directory / "ontology.sqlite3").relative_to(ROOT).as_posix()
            and audit["source_custody"] == db.meta("source_custody"), "compact_audit_resolves_the_derived_batch_and_shared_source_custody")
    require(audit["tables"]["source_expressions"] > 0, "shared_original_rf2_expressions_remain_queryable")
    require(sum(row["row_count"] for row in db.inventory()) == 12586084, "all_raw_source_rows_remain_available_through_readonly_custody")
    for row in db.inventory():
        require(row["complete"] == 1 and file_hash(ROOT / row["path"]) == row["sha256"], "source_pin:" + row["path"])
    builder = validated_selection(db, receipt)
    manifest = json.loads((ROOT / "submission/knowledge/manifest.json").read_text())
    require(manifest["build_id"] == db.meta("build_id") and manifest["review_receipt_sha256"] == digest(receipt),
            "submission_manifest_matches_approved_build_and_receipt")
    graph = Graph()
    for asset in [manifest["schema"], manifest["vocabulary"], *manifest["bundles"]]:
        path = ROOT / "submission" / asset["path"]
        require(file_hash(path) == asset["sha256"], "admitted_asset_pin:" + asset["path"])
        graph.parse(path, format="turtle")
    require(set(builder.graph) <= set(graph) and set(builder.vocabulary) <= set(graph), "admitted_graph_contains_every_approved_expression_and_connection")
    knowledge = ClinicalKnowledge(graph)
    knowledge.validate_graph(require_action_assets=False)
    elapsed = time.perf_counter() - started
    require(elapsed < 600 and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < 8 * 1024 * 1024, "source_and_graph_verification_under_competition_resource_limits")
    connections = json.loads((directory / "connections.json").read_text())
    for name, count in connections["relations"].items():
        require(len(list(graph.triples((None, OW[name], None)))) == count, "runtime_relation_count:" + name)
    evidence = json.loads((directory / "connection-evidence.json").read_text())
    require(all(record["source_refs"] for record in evidence), "all_converted_relations_have_nonempty_source_evidence")
    require(len({(record["subject"], record["predicate"], record["object"]) for record in evidence}) == len(evidence), "relation_proofs_are_deduplicated")
    report_keys = {(record["subject"], record["predicate"], record["object"]) for record in evidence}
    require(all((str(s), str(p), o.n3()) in report_keys for p in (OW.inSystem, OW.contextType, OW.hasSupportingContext)
                for s, o in graph.subject_objects(p)), "every_ros_and_context_link_has_exact_relation_evidence")
    require(len({knowledge.get_context_type(str(node)) for node in graph.subjects(RDF.type, OW.ContextFactor)}) == 10, "real_graph_contains_all_ten_context_categories")
    require(not list(graph.triples((None, OW.evaluatedBy, None))), "no_unsupported_test_plan_inference")
    target = str(OW.SymptomSnomedCT21522001)
    config = TextConfig.load()
    resources = PreparedResources(knowledge, config)
    state = WorkflowState(session=SessionContext(session_id="real-connections", deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
        turns_remaining=50, current="ChiefComplaint", initialized=True))
    state.case.put("S.cc", RecordItem(id="chief", scope="ChiefComplaint", status="done", source_refs=["scripted:chief"],
        value=ClinicalValue(kind="symptom", text="Abdominal pain", status="present", concept_ids=[target],
            observation_id="abdominal", episode_id="one", time_context="current")))
    consultation = assemble_consultation(None, resources)
    consultation.planner.prepare_chief_complaint(state)
    systems = knowledge.get_symptom_systems(target)
    require(bool(systems) and bool(state.questions.ros_targets), "actual_abdominal_pain_populates_focused_ros")
    require(set(state.questions.ros_targets) == {t for system in systems for t in knowledge.get_system_symptoms(system)} - {target}, "planner_consumes_exact_frozen_system_union")
    state.session.current = "DifferentialDiagnosis"
    consultation.reasoner.retrieve_candidates(state)
    require(any(not set(knowledge.get_symptom_systems(p.target)) & set(systems)
                for h in state.differential.hypotheses for p in knowledge.get_disease_patterns(h.disease_id)), "body_system_does_not_filter_cross_system_disease_recall")

    original = frozenset(graph)
    english_questions = {}
    for item in knowledge.concepts():
        if item["kind"] not in {"Symptom", "ContextFactor", "FindingAttribute"}:
            continue
        labels = list(graph.objects(URIRef(item["id"]), RDFS.label))
        english = str(next((label for label in labels if label.language == "en"), ""))
        text = english + "?"
        direct = not any(word in english.casefold() for word in ("due to", "secondary to", "caused by", "associated with"))
        allowed = bool(english) and len(text) <= 30 and direct
        english_questions[item["id"]] = QuestionTemplate(text=text if allowed else "Unavailable",
            answer_type="free_text", interviewable=allowed, reason=None if allowed else "English test fixture outside selected short-label scope")
    # Test-only source-label requests leave the data-owned graph and Korean assets unchanged.
    test_graph = Graph() + graph
    for method in test_graph.subjects(RDF.type, OW.ExamMethod):
        label = str(next(test_graph.objects(method, RDFS.label)))
        text = label + " please"
        require(1 <= len(text) <= 30, "source_method_label_fits_english_test_fixture")
        test_graph.add((method, OW.examRequestText, Literal(text)))
    test_knowledge = ClinicalKnowledge(test_graph, questions=english_questions)
    test_knowledge.validate_graph()
    test_knowledge.validate_question_assets()
    test_resources = PreparedResources(test_knowledge, config)
    cases = []

    class ScriptedSDK:
        timeout = 120
        def __init__(self, context_status):
            self.session_id = "d20-scripted-" + context_status
            self.remaining = 50
            self.context_status = context_status
            self.actions, self.submissions = [], []
            self.deadline = datetime.now(timezone.utc) + timedelta(minutes=25)
        def session(self):
            return {"session_id": self.session_id, "status": "active", "deadline": self.deadline.isoformat(),
                "turns_remaining": self.remaining, "initial": {"opening": "Abdominal pain", "vital_signs": {"pulse": 80}},
                "allowed_actions": ["SAY", "EXAM", "DIAGNOSE"]}
        def chat(self, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            question, text = payload["question"], payload["input"]
            facts = []
            if payload["parser_pass"] != "expansion" and (question is None or question["purpose"] in {"chief", "hpi", "ros", "feature", "context"}):
                is_context = question is not None and question["purpose"] == "context"
                attr = question["attribute_id"] if question else None
                concept = question["target_id"] if question and question["target_id"] else target
                status = self.context_status if is_context else "unknown" if attr else "present" if concept == target else "absent"
                value = {"kind": "context" if is_context else "attribute" if attr else "finding" if question and question["kind"] == "EXAM" else "symptom",
                    "text": text, "status": status, "concept_ids": [concept],
                    "subject": question["subject"] if question else "patient",
                    "time_context": question["time_context"] if question else "current"}
                if not is_context:
                    value.update(observation_id=(question["observation_id"] if question else None) or "abdominal",
                                 episode_id=(question["episode_id"] if question else None) or "one")
                if attr:
                    value["attribute_id"] = attr
                fact = {"field": question["field"] if question else "S.cc", "quote": text, "value": value}
                if question:
                    fact["record_id"] = question["item_id"]
                facts.append(fact)
            return {"choices": [{"message": {"content": json.dumps({"facts": facts})}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10}}
        def say(self, content, request_id):
            self.remaining -= 1
            self.actions.append({"kind": "SAY", "content": content, "request_id": request_id})
            return {"status": "OK", "turn": 50 - self.remaining, "turns_remaining": self.remaining, "content": "Abdominal pain" if content == config.texts.chief_question else "Scripted response"}
        def exam(self, maneuver, request_id):
            self.remaining -= 1
            self.actions.append({"kind": "EXAM", "content": maneuver, "request_id": request_id})
            return {"status": "OK", "turn": 50 - self.remaining, "turns_remaining": self.remaining, "content": "No finding"}
        def diagnose(self, **payload):
            self.submissions.append(payload)
            return {"status": "completed"}

    for context_status in ("present", "absent", "unknown"):
        client = ScriptedSDK(context_status)
        outcome = WorkflowState.model_validate(consult(client, test_resources))
        require(outcome.interaction.termination == "submitted" and len(client.submissions) == 1, "real_graph_e2e_confirmed_submission:" + context_status)
        require(sum(len(fields) for fields in client.submissions[0]["note"].values()) == 15, "real_graph_e2e_fifteen_soap_fields:" + context_status)
        ros = sum(entry.delivered and entry.question is not None and entry.question.purpose == "ros" for entry in outcome.interaction.history)
        contexts_asked = [entry for entry in outcome.interaction.history if entry.delivered and entry.question and entry.question.purpose == "context"]
        require(0 < ros <= 6 and bool(contexts_asked), "real_graph_e2e_delivers_bounded_ros_and_context:" + context_status)
        require(all(h.context_bonus in {0, 1} for h in outcome.differential.hypotheses), "real_graph_e2e_context_bonus_cap:" + context_status)
        if context_status == "present":
            require(any(h.context_bonus == 1 for h in outcome.differential.hypotheses), "real_graph_e2e_confirmed_context_activates_support")
        else:
            require(all(h.context_bonus == 0 for h in outcome.differential.hypotheses), "real_graph_e2e_nonpositive_context_adds_no_support:" + context_status)
        require(all(exchange["role"] == "gateway" for exchange in outcome.interaction.model_history), "no_question_generation_model_calls:" + context_status)
        cases.append({"context_status": context_status, "diagnosis_kind": outcome.case.diagnosis_kind,
            "termination": outcome.interaction.termination, "ros_actions": ros, "context_actions": len(contexts_asked),
            "total_actions": len(client.actions), "scripted_gateway_calls": outcome.session.doctor_calls})
        write(directory / ("case-" + context_status + ".json"), outcome.model_dump(mode="json"))
    require(frozenset(graph) == original, "source_graph_remains_readonly_after_all_cases")
    try:
        prepare()
    except ValueError as error:
        require("D20 graph is approved" in str(error), "production_prepare_reports_text_pending_after_graph_admission")
    else:
        raise AssertionError("production_prepare_accepted_missing_text_assets")
    db.close()
    report = {"status": "pass", "check_count": len(checks), "checks": checks, "cases": cases,
        "graph_triples": len(graph), "associations": len(knowledge._profile_cache),
        "graph_verification_seconds": elapsed, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "fixture_language": "English source labels plus unchanged common configuration",
        "korean_generation": "not_run", "real_model_calls": 0, "official_environment_e2e": "not_run", "network": "none"}
    write(directory / "verification.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
