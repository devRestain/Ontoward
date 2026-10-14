import copy
import argparse
import json
import subprocess
import sys
from pathlib import Path

import pydantic
import rdflib

from .models import ExtractionResult, SourceSpan
from .tools import GUIDELINES, SCHEMA, build_prompt, load_source, require_schema, validate_response
from .vocabulary import COUNTS, REGISTRY, ROOT, approved_tables, digest, encode, load_vocabulary, project_vocabulary


def main():
    parser = argparse.ArgumentParser(description="Verify saved candidate boundaries without model calls")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "Tmp/codex/schema-check")
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

    registry = load_vocabulary()
    baseline = approved_tables()
    check("exact_510_approved_terms_and_order", registry["terms"] == baseline
          and sum(map(len, baseline.values())) == 510)
    check("vocabulary_regeneration", REGISTRY.read_text() == encode(project_vocabulary(baseline)))
    schema = require_schema()
    check("schema_regeneration", SCHEMA.read_text() == encode(ExtractionResult.model_json_schema()))
    for kind, count in COUNTS.items():
        definition = schema["$defs"][kind + "Term"]
        check(kind + "_shared_enum", definition["enum"] == baseline[kind]
              and len(definition["enum"]) == count)

    objects = []
    unsupported = []

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                objects.append(node.get("additionalProperties") is False
                               and set(node.get("required", [])) == set(node.get("properties", {})))
            unsupported.extend({"oneOf", "discriminator", "default"} & node.keys())
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    check("closed_required_objects", bool(objects) and all(objects))
    check("supported_schema_union_and_no_defaults", not unsupported)
    check("root_object_without_union", schema["type"] == "object" and "anyOf" not in schema)
    enum_count = sum(len(definition.get("enum", [])) for definition in schema["$defs"].values())
    check("schema_enum_budget", enum_count <= 1000)

    document = "US_StatPearls/statpearls_article-17784.md"
    raw = (GUIDELINES / document).read_bytes()
    source = load_source(document, digest(raw), 1, len(raw.decode().splitlines()))

    def evidence(fragment):
        for number, line in enumerate(source["lines"], 1):
            if fragment in line:
                return [{"start_line": number, "end_line": number,
                         "quote": line.rstrip("\r\n")}]
        raise AssertionError(f"Missing source fragment: {fragment}")

    abdominal = evidence("periumbilical abdominal pain")
    exam = evidence("rebound tenderness")
    imaging = evidence("imaging modalities such as")
    pattern = {
        "disease": "Acute appendicitis", "target": {"kind": "symptom", "term": "Abdominal pain"},
        "features": [{"qualification": {"attribute": "Location", "value": "Right lower quadrant"},
                      "expected_status": None, "evidence": abdominal}], "evidence": abdominal,
    }
    response = {
        "patterns": [pattern, {"disease": "Acute appendicitis",
                               "target": {"kind": "exam_finding", "term": "Rebound tenderness"},
                               "features": [{"qualification": None, "expected_status": "present",
                                             "evidence": exam}], "evidence": exam}],
        "supporting_contexts": [],
        "finding_methods": [{"finding": "Rebound tenderness", "method": "Rebound tenderness assessment",
                             "evidence": exam}],
        "planned_tests": [{"disease": "Acute appendicitis", "test": "Abdominal ultrasonography",
                           "evidence": imaging}],
    }
    result = validate_response(source, encode(response))
    check("pattern_exam_and_test_grounding", result["status"] == "candidate_validated"
          and len(result["grounded_evidence"]) == 6 and result["clinical_review"] == "not_run")
    check("flat_location_no_inferred_abdomen", result["candidates"] == response)
    check("deterministic_section_context", all(item["sections"] for item in result["grounded_evidence"]))
    empty = {key: [] for key in response}
    check("empty_result", validate_response(source, encode(empty))["candidates"] == empty)
    no_features = copy.deepcopy(response)
    no_features["patterns"][0]["features"] = []
    check("zero_feature_pattern", validate_response(source, encode(no_features))["candidates"] == no_features)

    mutations = {
        "unapproved_term": lambda v: v["patterns"][0].update(disease="Unapproved disease"),
        "wrong_target_type": lambda v: v["patterns"][0]["target"].update(term="Complete blood count"),
        "wrong_acquisition_type": lambda v: v["patterns"][0]["target"].update(term="Wheezes"),
        "missing_attribute_value": lambda v: v["patterns"][0]["features"][0]["qualification"].pop("value"),
        "empty_feature": lambda v: v["patterns"][0]["features"][0].update(qualification=None),
        "feature_direct_target": lambda v: v["patterns"][0]["features"][0].update(target="Abdominal pain"),
        "unreviewed_importance": lambda v: v["patterns"][0].update(importance="characteristic"),
        "wrong_context_type": lambda v: v["supporting_contexts"].append(
            {"disease": "Acute appendicitis", "context_factor": "Abdominal pain", "evidence": abdominal}),
        "wrong_method_type": lambda v: v["finding_methods"][0].update(method="Abdominal ultrasonography"),
        "wrong_test_type": lambda v: v["planned_tests"][0].update(test="Abdominal pain"),
        "wrong_quote": lambda v: v["patterns"][0]["evidence"][0].update(quote="Fabricated source text"),
        "out_of_range": lambda v: v["patterns"][0]["evidence"][0].update(end_line=len(source["lines"]) + 1),
        "coerced_line_number": lambda v: v["patterns"][0]["evidence"][0].update(start_line="73"),
        "boolean_line_number": lambda v: v["patterns"][0]["evidence"][0].update(start_line=True),
        "missing_evidence": lambda v: v["patterns"][0].update(evidence=[]),
        "extra_top_level": lambda v: v.update(unresolved=[]),
    }
    for name, mutate in mutations.items():
        value = copy.deepcopy(response)
        mutate(value)
        rejects(name, lambda: validate_response(source, encode(value)))
    rejects("source_hash_mismatch", lambda: load_source(document, "0" * 64, 1, 10))
    rejects("uncatalogued_guidance", lambda: load_source("US_StatPearls/AGENTS.md", "0" * 64, 1, 10))
    rejects("path_traversal", lambda: load_source("../catalog.csv", "0" * 64, 1, 10))
    rejects("reversed_range", lambda: load_source(document, digest(raw), 20, 10))
    limited = load_source(document, digest(raw), 1, 10)
    rejects("evidence_outside_selected_excerpt", lambda: validate_response(limited, encode(response)))
    rejects("reversed_span", lambda: SourceSpan.model_validate_json(
        '{"start_line":2,"end_line":1,"quote":"x"}'))
    rejects("blank_quote", lambda: SourceSpan.model_validate_json(
        '{"start_line":1,"end_line":1,"quote":"  "}'))
    multiline = {"patterns": [copy.deepcopy(pattern)], **{key: [] for key in response if key != "patterns"}}
    quote = "".join(source["lines"][70:74])
    multiline["patterns"][0]["evidence"] = [{"start_line": 71, "end_line": 74, "quote": quote}]
    check("exact_multiline_quote", validate_response(source, encode(multiline))["candidates"] == multiline)

    asthma_doc = "US_StatPearls/statpearls_article-17920.md"
    asthma_raw = (GUIDELINES / asthma_doc).read_bytes()
    asthma = load_source(asthma_doc, digest(asthma_raw), 1, len(asthma_raw.decode().splitlines()))
    for number, line in enumerate(asthma["lines"], 1):
        if "family history of asthma" in line.lower():
            context_evidence = [{"start_line": number, "end_line": number, "quote": line.rstrip("\r\n")}]
            break
    else:
        raise AssertionError("Missing family-history source")
    context_response = {**empty, "supporting_contexts": [{"disease": "Asthma",
                        "context_factor": "Family history of asthma", "evidence": context_evidence}]}
    check("supporting_context_grounding", validate_response(asthma, encode(context_response))["candidates"]
          == context_response)
    new_pair = copy.deepcopy(response)
    new_pair["patterns"][0]["features"][0]["qualification"] = {"attribute": "Quality", "value": "Sharp"}
    check("new_approved_pair_is_unadmitted_candidate", validate_response(source, encode(new_pair))["rdf_admission"]
          == "not_run")
    check("quotation_does_not_prove_clinical_semantics", result["clinical_review"] == "not_run")
    prompt = build_prompt(source)
    check("prompt_contract", all(text in prompt for text in (
        "gpt-6-luna", "medium reasoning", "Standard speed", "510 approved English labels",
        "omit the whole dependent relation", "mandatory conjunction", "Wheezing", "Wheezes",
        "do not browse", "BEGIN UNTRUSTED SOURCE EXCERPT")))
    (out / "response.json").write_text(encode(response))
    (out / "prompt.txt").write_text(prompt)
    common = ["--document", document, "--sha256", digest(raw), "--start-line", "1",
              "--end-line", str(len(source["lines"]))]
    cli = subprocess.run([sys.executable, "-m", "Dev.ontology.tools", "validate", *common,
                          "--response", str(out / "response.json"), "--output", str(out / "validated.json")],
                         capture_output=True, text=True)
    check("offline_cli_workflow", cli.returncode == 0 and json.loads((out / "validated.json").read_text()) == result)
    check("pinned_dependency_versions", pydantic.__version__ == "2.14.0" and rdflib.__version__ == "7.6.0")
    report = {
        "result": "pass", "checks": checks, "check_count": len(checks),
        "approved_term_count": 510, "schema_enum_count": enum_count,
        "pydantic": pydantic.__version__, "rdflib": rdflib.__version__,
        "source_grounding": "pass", "fixture_scope": "Hand-authored offline candidates from two catalog documents",
        "clinical_expert_review": "not_run", "model_schema_acceptance": "not_run",
        "model_calls": "not_run", "clinical_extraction_quality": "not_run", "rdf_admission": "not_run",
    }
    (out / "verification.json").write_text(encode(report))
    print(encode({key: value for key, value in report.items() if key != "checks"}), end="")


if __name__ == "__main__":
    main()
