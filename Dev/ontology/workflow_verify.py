import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

from .models import AtomicResult
from .tools import GUIDELINES, load_source
from .vocabulary import ROOT, digest, encode
from .workflow import (SCHEMAS, atomic_prompt, conversion_prompt, parse_blocks, prepare,
                       direct_prompt, record_review, schema_hashes, validate_atomic,
                       validate_conversion, validate_direct)


def main():
    parser = argparse.ArgumentParser(description="Verify two-stage preparation without LLM calls")
    parser.add_argument("--output-dir", type=Path, required=True)
    out = parser.parse_args().output_dir
    out.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def rejects(name, operation):
        try:
            operation()
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)

    check("four_reproducible_generated_schemas", len(schema_hashes()) == 4)
    for stage, (model, _) in SCHEMAS.items():
        schema = model.model_json_schema()
        enum_count = sum(len(value.get("enum", [])) for value in schema.get("$defs", {}).values())
        check(stage + "_enum_budget", enum_count <= 1000)

    document = "US_StatPearls/statpearls_article-17784.md"
    raw = (GUIDELINES / document).read_bytes()
    source = load_source(document, digest(raw), 1, len(raw.decode().splitlines()))
    title = next(n for n, line in enumerate(source["lines"], 1) if line.startswith("# Appendicitis"))
    selection = {
        "document": document, "sha256": digest(raw), "start_line": 1, "end_line": len(source["lines"]),
        "source_kind": "textbook", "topic_diseases": ["Acute appendicitis"], "group_context": None,
        "topic_evidence": [{"start_line": title, "end_line": title, "quote": "# Appendicitis"}],
        "reviewer": "offline_fixture_not_a_clinician", "selection_reason": "Exercise disease-chapter input custody",
        "population": "Not restricted for this structural fixture", "edition": None,
        "conversion_quality": "acceptable", "quality_notes": "Exercise paragraph parsing only",
        "license_notes": "Retain CC BY-NC-ND; no submission or derivative admission",
    }
    prepared = prepare(selection)
    check("catalog_metadata_retained", prepared["source"]["catalog"]["license"] == "CC BY-NC-ND")
    check("frontmatter_excluded", all(unit["start_line"] > title for unit in prepared["units"]))
    check("stable_preparation_and_unit_ids", prepare(selection) == prepared)
    number = next(n for n, line in enumerate(source["lines"], 1) if "periumbilical abdominal pain" in line)
    unit = next(unit for unit in prepared["units"] if unit["start_line"] <= number <= unit["end_line"])
    quote = source["lines"][number - 1].rstrip("\r\n")
    evidence = [{"start_line": number, "end_line": number, "quote": quote}]
    atomic = {"claims": [{"claim_id": "pain", "statement": "Acute appendicitis may involve Abdominal pain that localizes to the Right lower quadrant.",
                          "relation_type": "patterns", "source_basis": "direct",
                          "concepts": [{"kind": "Disease", "term": "Acute appendicitis"},
                                       {"kind": "Symptom", "term": "Abdominal pain"},
                                       {"kind": "AttributeValue", "term": "Right lower quadrant"}],
                          "evidence": evidence}]}
    candidates = {"patterns": [{"disease": "Acute appendicitis",
                                "target": {"kind": "symptom", "term": "Abdominal pain"},
                                "features": [{"qualification": {"attribute": "Location", "value": "Right lower quadrant"},
                                              "expected_status": None, "evidence": evidence}], "evidence": evidence}],
                  "supporting_contexts": [], "finding_methods": [], "planned_tests": []}
    conversion = {"candidates": candidates, "links": [{"candidate": "/patterns/0", "claim_ids": ["pain"]}],
                  "excluded_claims": []}
    aid = unit["unit_id"]
    validated_atomic = validate_atomic(prepared, aid, encode(atomic))
    validated = validate_conversion(prepared, aid, encode(atomic), encode(conversion))
    check("full_grounded_statement_to_nested_candidate", validated["candidates"] == candidates)
    check("clinical_semantics_remain_unverified", validated["clinical_review"] == "not_run"
          and validated["semantic_validation"] == "not_run" and validated["rdf_admission"] == "not_run")
    check("candidate_review_packet_retains_statement_and_source_basis", validated["review_items"][0]["claims"] == atomic["claims"])
    check("core_and_context_are_separate", "BEGIN UNTRUSTED CORE" in atomic_prompt(prepared, aid)
          and all(context["start_line"] != unit["start_line"] for context in unit["context"]))
    check("conversion_rechecks_original_source", quote in conversion_prompt(prepared, aid, encode(atomic)))
    check("direct_baseline_uses_the_identical_source_unit", quote in direct_prompt(prepared, aid)
          and validate_direct(prepared, aid, encode(candidates))["prepared_sha256"] == validated["prepared_sha256"])

    for name, mutate in {
        "reject_unapproved_stage1_term": lambda v: v["claims"][0]["concepts"][0].update(term="Unknown disease"),
        "reject_wrong_concept_type": lambda v: v["claims"][0]["concepts"][1].update(kind="Test"),
        "reject_duplicate_claim_id": lambda v: v["claims"].append(copy.deepcopy(v["claims"][0])),
        "reject_blank_statement": lambda v: v["claims"][0].update(statement=" "),
        "reject_fabricated_quote": lambda v: v["claims"][0]["evidence"][0].update(quote="fabricated"),
        "reject_extra_stage1_fields": lambda v: v.update(unresolved=[]),
    }.items():
        value = copy.deepcopy(atomic)
        mutate(value)
        rejects(name, lambda: validate_atomic(prepared, aid, encode(value)))
    for name, mutate in {
        "reject_unlinked_candidate": lambda v: v.update(links=[]),
        "reject_unknown_claim": lambda v: v["links"][0].update(claim_ids=["unknown"]),
        "reject_duplicate_link": lambda v: v["links"].append(copy.deepcopy(v["links"][0])),
        "reject_wrong_pointer": lambda v: v["links"][0].update(candidate="/patterns/3"),
        "reject_new_relation_pair": lambda v: v["candidates"]["patterns"][0].update(disease="Asthma"),
        "reject_unexplained_claim_loss": lambda v: v.update(candidates={k: [] for k in candidates}, links=[]),
        "reject_linked_and_excluded": lambda v: v["excluded_claims"].append({"claim_id": "pain", "reason": "conflict"}),
        "reject_blank_exclusion": lambda v: v.update(candidates={k: [] for k in candidates}, links=[],
                excluded_claims=[{"claim_id": "pain", "reason": " "}]),
    }.items():
        value = copy.deepcopy(conversion)
        mutate(value)
        rejects(name, lambda: validate_conversion(prepared, aid, encode(atomic), encode(value)))
    dropped = {"candidates": {k: [] for k in candidates}, "links": [],
               "excluded_claims": [{"claim_id": "pain", "reason": "Fixture reviewer finds a meaning loss"}]}
    check("explicit_conversion_exclusion_is_audited", validate_conversion(prepared, aid, encode(atomic), encode(dropped))["excluded_claims"] == dropped["excluded_claims"])
    empty = {"claims": []}
    empty_conversion = {"candidates": {k: [] for k in candidates}, "links": [], "excluded_claims": []}
    empty_validated = validate_conversion(prepared, aid, encode(empty), encode(empty_conversion))
    check("empty_results_are_valid", not validate_atomic(prepared, aid, encode(empty))["claims"] and not empty_validated["links"])
    rejects("empty_stage1_cannot_gain_a_relation", lambda: validate_conversion(prepared, aid, encode(empty), encode(conversion)))
    fake_prepared = copy.deepcopy(prepared)
    fake_prepared["units"][0]["start_line"] += 1
    rejects("reject_tampered_preparation", lambda: atomic_prompt(fake_prepared, aid))
    changed = dict(selection, source_kind="guideline")
    rejects("reject_wrong_catalog_document_type", lambda: prepare(changed))
    rejects("reject_stale_source_hash", lambda: prepare(dict(selection, sha256="0" * 64)))
    rejects("reject_blank_selection_review", lambda: prepare(dict(selection, selection_reason=" ")))

    group_document = "US_StatPearls/statpearls_article-131092.md"
    group_raw = (GUIDELINES / group_document).read_bytes()
    group_source = load_source(group_document, digest(group_raw), 1, len(group_raw.decode().splitlines()))
    definition = {"start_line": 13, "end_line": 13,
                  "quote": "Inflammatory bowel disease (IBD) is a chronic immune-mediated disorder comprised of Crohn disease and ulcerative colitis."}
    group_core = {"start_line": 59, "end_line": 59, "quote": group_source["lines"][58].rstrip("\r\n")}
    members = ["Crohn disease", "Ulcerative colitis"]
    group_selection = {**selection, "document": group_document, "sha256": digest(group_raw),
                       "end_line": len(group_source["lines"]), "topic_diseases": members,
                       "topic_evidence": [definition], "group_context": {
                           "source_term": "IBD", "member_diseases": members, "evidence": [definition]}}
    group_prepared = prepare(group_selection)
    group_unit = next(u for u in group_prepared["units"] if u["start_line"] == 59)
    gid = group_unit["unit_id"]
    group_atomic = {"claims": [{"claim_id": f"group-{i}", "statement": f"{disease} may involve Diarrhea.",
                               "relation_type": "patterns", "source_basis": "direct",
                               "concepts": [{"kind": "Disease", "term": disease},
                                            {"kind": "Symptom", "term": "Diarrhea"}],
                               "evidence": [group_core, definition]} for i, disease in enumerate(members)]}
    group_conversion = {"candidates": {**{k: [] for k in candidates}, "patterns": [
        {"disease": disease, "target": {"kind": "symptom", "term": "Diarrhea"},
         "features": [], "evidence": [group_core, definition]} for disease in members]},
        "links": [{"candidate": f"/patterns/{i}", "claim_ids": [f"group-{i}"]} for i in range(2)],
        "excluded_claims": []}
    group_validated = validate_conversion(group_prepared, gid, encode(group_atomic), encode(group_conversion))
    check("shared_group_claims_keep_separate_single_disease_owners",
          [p["disease"] for p in group_validated["candidates"]["patterns"]] == members)
    check("group_definition_is_distinct_from_same_section_context",
          not group_unit["context"] and "BEGIN UNTRUSTED GROUP DEFINITION CONTEXT" in atomic_prompt(group_prepared, gid))
    check("conversion_and_review_retain_group_definition_and_core",
          definition["quote"] in conversion_prompt(group_prepared, gid, encode(group_atomic))
          and group_validated["group_context"] == group_selection["group_context"]
          and all(item["claims"][0]["evidence"] == [group_core, definition] for item in group_validated["review_items"]))
    for name, mutate in {
        "reject_duplicate_topic_diseases": lambda v: v["topic_diseases"].append(members[0]),
        "reject_unapproved_topic_disease": lambda v: v["topic_diseases"].append("Unknown disease"),
        "reject_group_member_outside_reviewed_topics": lambda v: v.update(topic_diseases=[members[0]]),
        "reject_duplicate_group_members": lambda v: v["group_context"]["member_diseases"].append(members[0]),
        "reject_blank_source_group": lambda v: v["group_context"].update(source_term=" "),
        "reject_fabricated_group_definition": lambda v: v["group_context"]["evidence"][0].update(quote="fabricated"),
    }.items():
        value = copy.deepcopy(group_selection)
        mutate(value)
        rejects(name, lambda: prepare(value))
    definition_only = copy.deepcopy(group_atomic)
    definition_only["claims"][0]["evidence"] = [definition]
    rejects("group_definition_alone_cannot_generate_a_claim",
            lambda: validate_atomic(group_prepared, gid, encode(definition_only)))
    merged = copy.deepcopy(group_conversion)
    merged["links"][0]["claim_ids"].append("group-1")
    rejects("conversion_cannot_merge_different_group_disease_owners",
            lambda: validate_conversion(group_prepared, gid, encode(group_atomic), encode(merged)))
    ungrouped = prepare({**group_selection, "group_context": None})
    rejects("topic_list_alone_does_not_supply_group_definition_evidence",
            lambda: validate_atomic(ungrouped, gid, encode(group_atomic)))

    if unit["context"]:
        context = unit["context"][0]
        value = copy.deepcopy(atomic)
        value["claims"][0]["evidence"] = [{"start_line": context["start_line"], "end_line": context["end_line"],
                                          "quote": "".join(source["lines"][context["start_line"]-1:context["end_line"]])}]
        rejects("context_alone_cannot_generate_a_claim", lambda: validate_atomic(prepared, aid, encode(value)))
        direct_value = copy.deepcopy(candidates)
        direct_value["patterns"][0]["evidence"] = value["claims"][0]["evidence"]
        rejects("direct_context_alone_cannot_generate_a_relation", lambda: validate_direct(prepared, aid, encode(direct_value)))
    distant = next(n for n, line in enumerate(source["lines"], 1) if "leading cause of abdominal surgery" in line)
    value = copy.deepcopy(atomic)
    value["claims"][0]["evidence"] = [{"start_line": distant, "end_line": distant,
                                      "quote": source["lines"][distant-1].rstrip()}]
    rejects("reject_quote_from_unsupplied_section", lambda: validate_atomic(prepared, aid, encode(value)))
    value = copy.deepcopy(conversion)
    value["candidates"]["patterns"][0]["evidence"] = [{"start_line": distant, "end_line": distant,
                                                       "quote": source["lines"][distant-1].rstrip()}]
    rejects("conversion_evidence_cannot_escape_linked_claim", lambda: validate_conversion(prepared, aid, encode(atomic), encode(value)))
    value = copy.deepcopy(conversion)
    value["candidates"]["patterns"][0]["features"][0]["qualification"]["value"] = "Sharp"
    rejects("conversion_cannot_add_a_qualifier_concept", lambda: validate_conversion(prepared, aid, encode(atomic), encode(value)))
    value = copy.deepcopy(conversion)
    value["candidates"]["patterns"][0]["features"] = []
    rejects("conversion_cannot_drop_a_referenced_qualifier", lambda: validate_conversion(prepared, aid, encode(atomic), encode(value)))

    differential = copy.deepcopy(atomic)
    differential["claims"][0]["source_basis"] = "differential"
    rejects("differential_cannot_declare_qualification_concepts", lambda: AtomicResult.model_validate_json(encode(differential)))
    differential["claims"][0]["concepts"] = differential["claims"][0]["concepts"][:2]
    possible = copy.deepcopy(conversion)
    possible["candidates"]["patterns"][0]["features"] = []
    check("differential_possible_association_contract", validate_conversion(prepared, aid, encode(differential), encode(possible))["review_items"][0]["claims"][0]["source_basis"] == "differential")
    rejects("differential_cannot_gain_expected_presence", lambda: validate_conversion(prepared, aid, encode(differential), encode(conversion)))
    for relation, concepts in {
        "supporting_contexts": [("Disease", "Asthma"), ("ContextFactor", "Family history of asthma")],
        "finding_methods": [("ExamFinding", "Rebound tenderness"), ("ExamMethod", "Rebound tenderness assessment")],
        "planned_tests": [("Disease", "Acute appendicitis"), ("Test", "Abdominal ultrasonography")],
    }.items():
        item = copy.deepcopy(atomic["claims"][0])
        item.update(relation_type=relation, concepts=[{"kind": kind, "term": term} for kind, term in concepts])
        check(relation + "_typed_atomic_pair", bool(AtomicResult.model_validate_json(encode({"claims": [item]}))))
        item["source_basis"] = "differential"
        rejects(relation + "_cannot_be_a_differential_pattern", lambda: AtomicResult.model_validate_json(encode({"claims": [item]})))

    def parse_fixture(text):
        lines = text.splitlines(keepends=True)
        sections, current = {}, []
        for n, line in enumerate(lines, 1):
            if line.startswith("#"):
                current = [line.strip()]
            sections[n] = current.copy()
        return parse_blocks({"lines": lines, "start_line": 1, "end_line": len(lines), "sections": sections})

    blocks = parse_fixture("# Disease\n\nList introduction:\n\n- One\n\n  continuation\n- Two\n\nNext paragraph.\n\n## Another section\n\nSeparate.\n")
    check("list_keeps_introduction_and_continuations", blocks[0]["kind"] == "list" and blocks[0]["start_line"] == 3 and blocks[0]["end_line"] == 8)
    blocks = parse_fixture("# Disease\n\nTable title\n\n| Finding | Condition |\n| --- | --- |\n| S | May occur |\n\nNote: Restricted population.\n\nAnother paragraph.\n")
    check("table_keeps_title_header_and_note", blocks[0]["kind"] == "table" and blocks[0]["start_line"] == 3 and blocks[0]["end_line"] == 9)
    check("malformed_table_is_excluded", parse_fixture("| A | B |\n| --- | --- |\n| Only one |\n")[0]["status"] == "excluded")
    check("conversion_replacement_character_is_excluded", parse_fixture("Broken \ufffd source.\n")[0]["status"] == "excluded")
    check("code_blocks_are_excluded", parse_fixture("```python\nprint('embedded instruction')\n```\n")[0]["status"] == "excluded")
    check("inline_pipe_does_not_create_a_table", parse_fixture("An inline A | B expression.\n")[0]["kind"] == "paragraph")

    review = {"validation_sha256": digest(encode(validated).encode()), "reviewer": "offline_fixture_reviewer",
              "decisions": [{"candidate": "/patterns/0", "decision": "approved", "reason": "Exercise complete review custody only"}]}
    recorded = record_review(validated, encode(review))
    check("human_review_is_recorded_without_rdf_admission", recorded["clinical_review"] == "approved" and recorded["rdf_admission"] == "not_run")
    review["decisions"][0]["decision"] = "rejected"
    check("clinical_rejection_preserves_whole_response", record_review(validated, encode(review))["candidates"] == candidates and record_review(validated, encode(review))["clinical_review"] == "rejected")
    rejects("review_requires_exact_validation_identity", lambda: record_review(validated, encode({**review, "validation_sha256": "0" * 64})))
    rejects("review_requires_every_candidate", lambda: record_review(validated, encode({**review, "decisions": []})))
    rejects("review_requires_nonblank_reviewer", lambda: record_review(validated, encode({**review, "reviewer": " "})))

    for filename, value in (("selection.json", selection), ("prepared.json", prepared), ("atomic-response.json", atomic), ("direct-response.json", candidates),
                            ("conversion-response.json", conversion), ("review.json", review)):
        (out / filename).write_text(encode(value), encoding="utf-8")
    commands = [
        ["prepare", "--selection", str(out / "selection.json")],
        ["prompt-direct"], ["validate-direct", "--response", str(out / "direct-response.json")],
        ["prompt-atomic"], ["validate-atomic", "--response", str(out / "atomic-response.json")],
        ["prompt-conversion", "--atomic-response", str(out / "atomic-response.json")],
        ["validate-conversion", "--atomic-response", str(out / "atomic-response.json"), "--response", str(out / "conversion-response.json")],
        ["review", "--atomic-response", str(out / "atomic-response.json"), "--response", str(out / "conversion-response.json"), "--review", str(out / "review.json")],
    ]
    for command in commands:
        destination = out / (command[0] + ".json" if not command[0].startswith("prompt") else command[0] + ".txt")
        if command[0] != "prepare":
            command += ["--prepared", str(out / "prepared.json"), "--unit", aid]
        completed = subprocess.run([sys.executable, "-m", "Dev.ontology.workflow", *command,
                                    "--output", str(destination)], capture_output=True, text=True)
        check(command[0] + "_cli", completed.returncode == 0)
    check("stage2_cli_retains_original_extraction_shape", json.loads((out / "validate-conversion.json").read_text())["candidates"] == candidates)
    completed = subprocess.run([sys.executable, "-m", "Dev.ontology.workflow", "review-digest", "--validated",
                                str(out / "validate-conversion.json")], capture_output=True, text=True)
    check("review_digest_cli_binds_the_complete_packet", completed.returncode == 0
          and completed.stdout.strip() == digest(encode(validated).encode()))
    report = {"result": "pass", "check_count": len(checks), "checks": checks,
              "fixture_scope": "Hand-authored structural/custody cases and synthetic Markdown; not clinician gold",
              "model_calls": "not_run", "clinical_expert_review": "not_run", "clinical_extraction_quality": "not_run",
              "model_comparison": "not_run", "rdf_generation": "not_run", "rdf_admission": "not_run",
              "submission_admission": "not_run"}
    (out / "verification.json").write_text(encode(report))
    print(encode({k: v for k, v in report.items() if k != "checks"}), end="")


if __name__ == "__main__":
    main()
