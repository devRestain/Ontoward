import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "submission"))
sys.path.insert(0, str(ROOT / "Dev/tests/workflow"))

from rdflib import Graph, RDF
from Dev.ontology.database import SourceDatabase
from Dev.ontology.v5 import OW, write
from knowledge.conditions import QuestionTemplate, ScoringPolicy
from knowledge.graph import ClinicalKnowledge
from normalization_fixtures import mapping_from_contracts
from test_workflow import CONFIG, FakeSDK, make_consultation, pending, question, resources, state
from workflow.state.canonical import CanonicalSnapshot
from workflow.state.models import ContextStatement
from workflow.rules.normalization import candidate_contracts


def load(manifest, directory):
    graph = Graph()
    for asset in [manifest["schema"], manifest["vocabulary"], *manifest["bundles"]]:
        graph.parse(directory / Path(asset["path"]).name, format="turtle")
    questions = json.loads((directory / Path(manifest["questions"]["path"]).name).read_text())
    result = ClinicalKnowledge(graph, {k: QuestionTemplate.model_validate(v) for k, v in questions.items()},
        policy=ScoringPolicy.model_validate_json((directory / Path(manifest["scoring_policy"]["path"]).name).read_text()))
    result.validate_graph()
    result.validate_question_assets()
    return result


def verify(batch, admitted, output):
    checks = []

    def require(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    baseline_manifest = json.loads((batch / "baseline-manifest.json").read_text())
    manifest = json.loads((admitted / "manifest.json").read_text())
    before, knowledge = load(baseline_manifest, ROOT / "submission/knowledge"), load(manifest, admitted)
    require(manifest["schema"]["sha256"] == baseline_manifest["schema"]["sha256"] and manifest["schema_version"] == "5.0",
            "unchanged_v5_schema")
    require(manifest["reasoning_policy"]["sha256"] == baseline_manifest["reasoning_policy"]["sha256"]
        and manifest["algorithm_version"] == "d41.1", "preserve_d41_algorithm_and_reasoning_policy")
    require(set(before._graph.subjects(RDF.type, OW.Disease)) == set(knowledge._graph.subjects(RDF.type, OW.Disease)),
            "preserve_exact_843_disease_catalog")
    for ident, profile in before._profile_cache.items():
        require(ident in knowledge._profile_cache and profile.model_dump(exclude={"source_refs"}) ==
            knowledge._profile_cache[ident].model_dump(exclude={"source_refs"}), "preserve_existing_profile:" + ident)
    for profile in knowledge._profile_cache.values():
        if profile.relation_basis == "external_association":
            require(profile.score == 1 and profile.typicality is None and profile.strong_predictor is None,
                "qualitative_external_without_invented_frequency:" + profile.association_id)
    roots = json.loads((batch / "root-audit.json").read_text())
    require(len([r for r in roots if r["bodhi_root"] and r["source_id"]]) == 590, "account_for_all_590_nonempty_bodhi_roots")
    require(any(r["source_id"] == "16001004" and r["active_sctid"] == "301354004" and r["history_refs"] for r in roots),
            "inactive_ear_pain_uses_unique_active_same_as")
    ddx = json.loads((batch / "ddxplus.json").read_text())
    require(len(ddx["evidences"]) == 223 and len(ddx["conditions"]) == 49 and not ddx["patient_archives_read"]
        and not ddx["synthetic_probabilities_imported"], "ddxplus_metadata_only_complete_dispositions")
    require(all(len(knowledge.get_pattern_features(p.id)) == 1 for p in knowledge._profile_cache.values()
        if p.relation_basis == "external_association"), "ddxplus_binary_links_are_independent_presence_not_joint_and")
    probes = [("잠을 잘 못 자요", "301345002"), ("키가 또래보다 작아요", "444000005"),
        ("살이 빠져요", "262285001"), ("숨이 차요", "267036007"), ("더위를 많이 타요", "69215007"),
        ("땀이 많이 나요", "52613005"), ("손이 떨려요", "26079004"), ("불면증", "193462001")]
    heldout = [("요즘 통 잠을 이루질 못합니다", "301345002"), ("전보다 체중이 계속 줄어듭니다", "262285001"),
        ("조금 걷는데도 숨차고 힘듭니다", "267036007"), ("손에 떨림이 생겼습니다", "26079004"),
        ("뜨거운 날씨를 견디기가 힘듭니다", "69215007"), ("땀이 과하게 흐르는 편입니다", "52613005"),
        ("제 나이의 다른 아이들에 비해 키가 작습니다", "444000005"), ("몸이 피곤한 느낌이 지속됩니다", "84229001")]
    recall = {}
    for name, cases in [("development", probes), ("heldout", heldout)]:
        rows = []
        for phrase, cid in cases:
            target = str(OW) + "SymptomSnomedCT" + cid
            statement = ContextStatement(quote=phrase, role="clinical", assertion="present", target_terms=[phrase])
            contracts = candidate_contracts(knowledge, statement, None)
            expanded = candidate_contracts(knowledge, statement, None, expanded=True)
            rows.append({"phrase": phrase, "target": target,
                "before_recall10": target in before.search_concepts(phrase, kind="Symptom")[:10],
                "after_recall10": target in knowledge.search_concepts(phrase, kind="Symptom")[:10],
                "primary8": target in [c["id"] for c in contracts], "expanded32": target in [c["id"] for c in expanded]})
        recall[name] = {"rows": rows, **{field: sum(r[field] for r in rows) / len(rows) for field in
            ("before_recall10", "after_recall10", "primary8", "expanded32")}}
    require(recall["development"]["after_recall10"] == 1 and recall["development"]["primary8"] == 1,
            "all_original_eight_complaints_reach_d41_primary_candidates")
    require(recall["heldout"]["after_recall10"] > recall["heldout"]["before_recall10"], "heldout_lexical_recall_improves")
    require(len(set(knowledge.resolve_concept("속이 안 좋다")) & {str(OW) + "SymptomSnomedCT" + cid
        for cid in ("422587007", "116289008", "16331000")}) == 3, "ambiguous_expression_retains_multiple_targets")
    payloads = []

    def interpret(text, statements, *, target=None, mapping_failure=False, session=None):
        client = FakeSDK()
        consultation = make_consultation(client, resources(knowledge, CONFIG))
        s = session or state()
        response_field = "result" if s.interaction.pending and s.interaction.pending.question.kind == "EXAM" else "content"
        s.interaction.incoming = {response_field: text} if session else {"initial": {"opening": text}}

        def chat(messages, **kwargs):
            p = json.loads(messages[1]["content"])
            size = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode())
            payloads.append({"task": p["task"], "bytes": size, "payload": p})
            if p["task"] == "input_context":
                result = {"statements": statements}
            elif mapping_failure:
                return client.completion("invalid json")
            else:
                p = copy.deepcopy(p)
                if target:
                    for item in p["statements"]:
                        item["candidates"].sort(key=lambda c: c["id"] != target)
                result = mapping_from_contracts(p)
            return client.completion(json.dumps(result, ensure_ascii=False))

        client.chat = Mock(side_effect=chat)
        consultation.interpreter.process_input(s, knowledge, client)
        return s, consultation

    def statement(text, **changes):
        return {"quote": text, "role": "clinical", "assertion": "present", "time_context": "current", **changes}

    for phrase, cid in probes:
        target = str(OW) + "SymptomSnomedCT" + cid
        s, c = interpret(phrase, [statement(phrase, target_terms=[phrase])], target=target)
        require(any(target in i.value.concept_ids for _, i in CanonicalSnapshot.from_case(s.case).entries), "actual_payload_to_canonical:" + cid)
        c.writer.build_soap(s)
        require(knowledge.label(target, language="en") in json.dumps(s.interaction.submission_payload), "canonical_soap:" + cid)
    target, attribute = str(OW.SymptomSnomedCT444000005), str(OW.BodyHeight)
    text = "키가 또래보다 작아요. 현재 키는 약 100cm예요."
    statements = [statement("키가 또래보다 작아요", target_terms=["Short stature"], primary_concern=True),
        statement("현재 키는 약 100cm예요", target_terms=["Short stature"], attribute_terms=["Body height"],
            anchor=0, measurement={"kind": "quantity", "value": 100, "unit": "cm", "operator": "eq", "approximate": True})]
    s, c = interpret(text, statements, target=target)
    facts = CanonicalSnapshot.from_case(s.case).entries
    measured = next((i for _, i in facts if i.value.attribute_id == attribute), None)
    if measured is None:
        write(output.with_name("measurement-debug.json"), {"facts": [(f, i.model_dump()) for f, i in facts],
            "outcomes": [o.model_dump() for o in s.case.outcomes], "interpretations": s.interaction.interpretations,
            "payloads": payloads[-6:]})
        raise AssertionError("registered measurement was not admitted; see measurement-debug.json")
    require(measured.value.measurement.value == 100 and measured.value.measurement.approximate
        and measured.value.subject == "patient" and measured.value.time_context == "current", "registered_measurement_preserves_number_unit_approximation_and_subject")
    c.reasoner.retrieve_candidates(s)
    scores = [(h.disease_id, h.evidence_score) for h in s.differential.hypotheses]
    isolated = copy.deepcopy(s)
    isolated.case.remove({measured.id})
    c.reasoner.refresh_hypotheses(isolated, force=True)
    require(scores == [(h.disease_id, h.evidence_score) for h in isolated.differential.hypotheses], "measurement_adds_no_threshold_or_diagnostic_support")
    c.writer.build_soap(s)
    note = s.interaction.submission_payload["note"]
    require("100" in note["S"]["hpi"] and "cm" in note["S"]["hpi"] and not note["O"]["exam"], "patient_measurement_reaches_s_hpi_without_exam_conversion")
    c.planner.prepare_chief_complaint(s)
    require(s.questions.chief_attributes.get(attribute) == "acquired", "planner_uses_same_acquired_measurement")
    s.session.turns_remaining = 1
    c.planner.prepare_chief_complaint(s)
    require("budget_stopped" in s.questions.chief_attributes.values(), "added_attributes_respect_existing_submission_reserve")
    exam_target = str(OW.ExamFindingSnomedCT43478001)
    exam_state = state("DifferentialDiagnosis", True)
    spec = c.planner._spec(exam_state, exam_target)
    require(spec and spec["kind"] == "EXAM" and spec["text"] == "배를 눌러 압통을 확인해 주세요.", "source_confirmed_palpation_has_prepared_request")
    from workflow.state.models import Question
    pending(exam_state, Question(item_id="common:palpation", order=0, priority=0, **spec))
    s, c = interpret("복부 압통이 있습니다", [statement("복부 압통이 있습니다", target_terms=[exam_target])],
        target=exam_target, session=exam_state)
    require(any(f == "O.exam" and i.value.kind == "finding" and i.acquisition == "EXAM"
        for f, i in CanonicalSnapshot.from_case(s.case).entries), "actual_exam_result_reaches_canonical_o_exam")
    s, c = interpret("복부 압통이 있습니다", [statement("복부 압통이 있습니다", target_terms=[exam_target])])
    require(not any(f == "O.exam" for f, _ in CanonicalSnapshot.from_case(s.case).entries), "patient_report_does_not_create_physical_exam")
    for assertion, subject, timing in [("absent", "patient", "current"), ("present", "family", "current"), ("present", "patient", "past")]:
        text = "피부에 발진이 났어요"
        s, c = interpret(text, [statement(text, target_terms=[text], assertion=assertion, subject=subject, time_context=timing,
            **({"subject_member": "mother"} if subject == "family" else {}))], target=str(OW.SymptomSnomedCT271807003))
        c.reasoner.retrieve_candidates(s)
        require(not any(h.evidence_score > 0 for h in s.differential.hypotheses), "no_positive_evidence_from:" + assertion + subject + timing)
    s, c = interpret("모르겠어요", [{"quote": "모르겠어요", "role": "unknown"}])
    require(not CanonicalSnapshot.from_case(s.case).entries and s.case.outcomes[0].state == "unknown", "unknown_remains_unknown")
    s, c = interpret("잠을 잘 못 자요", [statement("잠을 잘 못 자요", target_terms=["잠을 잘 못 자요"])], mapping_failure=True)
    require(s.case.chief().value.forced_by == "deterministic", "new_aliases_reach_bounded_forced_completion")
    require(all(p["bytes"] <= (12288 if p["payload"].get("phase") in {"mapping", "context"} else 16384) for p in payloads),
        "actual_full_serialized_messages_remain_within_d41_limits")
    database = SourceDatabase(batch / "ontology.sqlite3", readonly=True)
    try:
        require(sum(r["row_count"] for r in database.inventory()) == 12586084, "readonly_custody_keeps_all_12586084_source_rows")
    finally:
        database.close()
    report = {"status": "pass", "checks": len(checks), "check_names": [n for n in checks if not n.startswith((
        "preserve_existing_profile:", "qualitative_external_without_invented_frequency:"))],
        "preserved_profiles": len(before._profile_cache), "recall": recall,
        "mapping_payloads": len([p for p in payloads if p["task"] == "input_mapping"]),
        "largest_full_messages_bytes": max(p["bytes"] for p in payloads),
        "clinical_attribute_counts": dict(Counter(len(knowledge.get_symptom_attributes(c["id"]))
            for c in knowledge.concepts() if c["kind"] == "Symptom")),
        "actual_model_semantic_accuracy": "not_run", "clinical_validation": "not_run"}
    write(output, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"check_names", "recall"}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--admitted", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.batch.resolve(), args.admitted.resolve(), args.output.resolve())
