import argparse
import json
import re
from pathlib import Path

from .models import AtomicResult, ClinicalReview, ConversionResult, SourceSelection
from .tools import grounded_evidence, load_source, require_schema, source_metadata, validate_response
from .vocabulary import ONTOLOGY, digest, encode, load_vocabulary


SCHEMAS = {
    "selection": (SourceSelection, "source-selection.schema.json"),
    "atomic": (AtomicResult, "atomic.schema.json"),
    "conversion": (ConversionResult, "conversion.schema.json"),
    "review": (ClinicalReview, "clinical-review.schema.json"),
}
LIST = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
HEADING = re.compile(r"^#{1,6}\s+")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def schema_hashes():
    require_schema()
    hashes = {}
    for stage, (model, filename) in SCHEMAS.items():
        expected = encode(model.model_json_schema())
        if (ONTOLOGY / filename).read_text(encoding="utf-8") != expected:
            raise ValueError(f"Regenerate {filename} from the Python model")
        hashes[stage] = digest(expected.encode())
    return hashes


def selected_source(selection):
    review = SourceSelection.model_validate_json(encode(selection))
    source = load_source(review.document, review.sha256, review.start_line, review.end_line)
    expected = {"textbook": "질환 개요(교과서)", "guideline": "진료지침"}[review.source_kind]
    if source["catalog"]["document_type"] != expected:
        raise ValueError("Select a cataloged textbook or clinician guideline of the reviewed kind")
    grounded_evidence(source, {"evidence": review.model_dump(mode="json")["topic_evidence"]})
    if review.group_context:
        grounded_evidence(source, review.group_context.model_dump(mode="json"))
    return source


def table_cells(line):
    return re.split(r"(?<!\\)\|", line.strip().strip("|"))


def starts_table(lines, number, end):
    line = lines[number - 1]
    return (line.lstrip().startswith("|") or
            ("|" in line and number < end and "|" in lines[number]
             and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in table_cells(lines[number]))))


def parse_blocks(source):
    lines = source["lines"]
    start, end = source["start_line"], source["end_line"]
    if lines and lines[0].strip() == "---":
        for number, line in enumerate(lines[1:], 2):
            if line.strip() == "---":
                start = max(start, number + 1)
                break
        else:
            raise ValueError("Unclosed source frontmatter")
    blocks = []
    number = start
    while number <= end:
        line = lines[number - 1]
        if not line.strip() or HEADING.match(line):
            number += 1
            continue
        first = number
        kind = "paragraph"
        reason = None
        fence = FENCE.match(line)
        if fence:
            kind, reason = "code", "code_or_conversion_artifact"
            number += 1
            while number <= end and not lines[number - 1].lstrip().startswith(fence[1]):
                number += 1
            number = min(number + 1, end + 1)
        elif starts_table(lines, number, end):
            kind = "table"
            while number <= end and "|" in lines[number - 1] and not HEADING.match(lines[number - 1]):
                number += 1
            rows = lines[first - 1:number - 1]
            width = len(table_cells(rows[0]))
            if (len(rows) < 2 or width < 2
                    or not all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in table_cells(rows[1]))
                    or any(len(table_cells(row)) != width for row in rows)):
                reason = "malformed_table"
        else:
            kind = "list" if LIST.match(line) else "paragraph"
            number += 1
            while number <= end:
                following = lines[number - 1]
                if HEADING.match(following) or FENCE.match(following) or starts_table(lines, number, end):
                    break
                if not following.strip():
                    look = number + 1
                    while look <= end and not lines[look - 1].strip():
                        look += 1
                    if (kind == "list" and look <= end
                            and (LIST.match(lines[look - 1]) or lines[look - 1].startswith(("  ", "\t")))):
                        number = look
                        continue
                    break
                if kind == "paragraph" and LIST.match(following):
                    break
                number += 1
        last = number - 1
        sections = source["sections"][first]
        if (kind in {"list", "table"} and blocks and blocks[-1]["kind"] == "paragraph"
                and blocks[-1]["sections"] == sections and blocks[-1]["status"] == "ready"):
            first = blocks.pop()["start_line"]
        if kind == "table" and reason is None:
            look = number
            while look <= end and not lines[look - 1].strip():
                look += 1
            if look <= end and re.match(r"\s*(?:Notes?:|Footnotes?:|\[\^[^]]+\]:)", lines[look - 1], re.I):
                number = look + 1
                while number <= end and lines[number - 1].strip() and not HEADING.match(lines[number - 1]):
                    number += 1
                last = number - 1
        text = "".join(lines[first - 1:last])
        if "\ufffd" in text or re.search(r"<\s*(table|script)\b", text, re.I):
            reason = "conversion_artifact"
        blocks.append({"kind": kind, "start_line": first, "end_line": last,
                       "sections": sections, "status": "excluded" if reason else "ready", "reason": reason})
    return blocks


def prepare(selection):
    source = selected_source(selection)
    blocks = parse_blocks(source)
    units = []
    for index, block in enumerate(blocks):
        contexts = []
        if block["status"] == "ready":
            for neighbors in (reversed(blocks[:index]), iter(blocks[index + 1:])):
                for neighbor in neighbors:
                    if neighbor["sections"] != block["sections"]:
                        break
                    if neighbor["status"] != "ready":
                        break
                    if neighbor["kind"] == "paragraph":
                        contexts.append({"start_line": neighbor["start_line"], "end_line": neighbor["end_line"]})
                        break
        key = f"{source['sha256']}:{block['start_line']}:{block['end_line']}".encode()
        units.append({"unit_id": digest(key)[:16], **block, "context": contexts,
                      "group_context": selection["group_context"]})
    return {"workflow_version": 2, "differential_policy": "possible_association",
            "selection": selection, "source": source_metadata(source), "units": units,
            "schema_hashes": schema_hashes(), "vocabulary_sha256": load_vocabulary()["terms_sha256"],
            "clinical_review": "not_run", "model_calls": "not_run", "rdf_admission": "not_run"}


def load_prepared(prepared, unit_id):
    if prepared != prepare(prepared["selection"]):
        raise ValueError("Prepared input differs from its source, selection, parser, or schema")
    units = [unit for unit in prepared["units"] if unit["unit_id"] == unit_id]
    if len(units) != 1 or units[0]["status"] != "ready":
        raise ValueError("Select exactly one ready unit")
    return selected_source(prepared["selection"]), units[0]


def ranges(unit):
    definitions = unit["group_context"]["evidence"] if unit["group_context"] else []
    return [{"start_line": unit["start_line"], "end_line": unit["end_line"]}, *unit["context"], *definitions]


def source_input(source, unit):
    chunks = []
    for index, span in enumerate(ranges(unit)):
        label = ("CORE" if index == 0 else "CONTEXT" if index <= len(unit["context"])
                 else "GROUP DEFINITION CONTEXT")
        excerpt = "\n".join(f"{n}: {source['lines'][n - 1].rstrip(chr(10)).rstrip(chr(13))}"
                            for n in range(span["start_line"], span["end_line"] + 1))
        chunks.append(f"BEGIN UNTRUSTED {label}\n{excerpt}\nEND UNTRUSTED {label}")
    return ("Source metadata:\n" + encode(source_metadata(source))
            + "Unit and section context:\n" + encode(unit) + "\n" + "\n".join(chunks))


def atomic_prompt(prepared, unit_id):
    source, unit = load_prepared(prepared, unit_id)
    return (Path(__file__).with_name("atomic_prompt.md").read_text()
            + "\nReviewed selection:\n" + encode(prepared["selection"])
            + "Approved vocabulary:\n" + encode(load_vocabulary()["terms"])
            + source_input(source, unit))


def direct_prompt(prepared, unit_id):
    source, unit = load_prepared(prepared, unit_id)
    return (Path(__file__).with_name("extraction_prompt.md").read_text()
            + "\nExtract only relations anchored in CORE. CONTEXT may complete their subjects or conditions; "
            "do not extract additional relations solely from CONTEXT. Each candidate must quote CORE text.\n"
            + "Reviewed selection:\n" + encode(prepared["selection"])
            + "Approved vocabulary:\n" + encode(load_vocabulary()["terms"])
            + source_input(source, unit))


def quote_overlaps_core(source, unit, span):
    text = "".join(source["lines"][span["start_line"] - 1:span["end_line"]])
    origin = sum(map(len, source["lines"][:span["start_line"] - 1]))
    core_start = sum(map(len, source["lines"][:unit["start_line"] - 1]))
    core_end = sum(map(len, source["lines"][:unit["end_line"]]))
    offset = text.find(span["quote"])
    while offset >= 0:
        if origin + offset < core_end and origin + offset + len(span["quote"]) > core_start:
            return True
        offset = text.find(span["quote"], offset + 1)
    return False


def validate_atomic(prepared, unit_id, response):
    source, unit = load_prepared(prepared, unit_id)
    value = AtomicResult.model_validate_json(response).model_dump(mode="json")
    grounded = grounded_evidence(source, value)
    for claim in value["claims"]:
        for span in claim["evidence"]:
            if not any(r["start_line"] <= span["start_line"] <= span["end_line"] <= r["end_line"]
                       for r in ranges(unit)):
                raise ValueError("Claim evidence exceeds the core and supplied context")
        if not any(quote_overlaps_core(source, unit, span) for span in claim["evidence"]):
            raise ValueError("A claim needs a quoted occurrence in the core")
    return {"status": "atomic_validated", "unit_id": unit_id,
            "prepared_sha256": digest(encode(prepared).encode()),
            "response_sha256": digest(response.encode() if isinstance(response, str) else response),
            "claims": value["claims"], "grounded_evidence": grounded,
            "group_context": unit["group_context"],
            "clinical_review": "not_run", "rdf_admission": "not_run"}


def validate_direct(prepared, unit_id, response):
    source, unit = load_prepared(prepared, unit_id)
    validated = validate_response(source, response)
    for span in validated["grounded_evidence"]:
        if not any(r["start_line"] <= span["start_line"] <= span["end_line"] <= r["end_line"]
                   for r in ranges(unit)):
            raise ValueError("Direct evidence exceeds the same supplied core/context ranges")
    for candidates in validated["candidates"].values():
        for candidate in candidates:
            if not any(quote_overlaps_core(source, unit, span) for span in candidate["evidence"]):
                raise ValueError("Direct candidates also need evidence anchored in the core")
    return {**validated, "workflow_version": 2, "unit_id": unit_id,
            "prepared_sha256": digest(encode(prepared).encode()),
            "semantic_validation": "not_run", "quality_admission": "not_run"}


def conversion_prompt(prepared, unit_id, atomic_response):
    validated = validate_atomic(prepared, unit_id, atomic_response)
    source, unit = load_prepared(prepared, unit_id)
    return (Path(__file__).with_name("conversion_prompt.md").read_text()
            + "\nReviewed selection:\n" + encode(prepared["selection"])
            + "Validated atomic claims:\n" + encode(validated["claims"])
            + "Approved vocabulary:\n" + encode(load_vocabulary()["terms"])
            + source_input(source, unit))


def candidate_concepts(kind, candidate):
    if kind == "patterns":
        target = candidate["target"]
        pairs = {("Disease", candidate["disease"]),
                 ("Symptom" if target["kind"] == "symptom" else "ExamFinding", target["term"])}
        pairs.update(("AttributeValue", feature["qualification"]["value"])
                     for feature in candidate["features"] if feature["qualification"])
        return pairs
    fields = {"supporting_contexts": (("Disease", "disease"), ("ContextFactor", "context_factor")),
              "finding_methods": (("ExamFinding", "finding"), ("ExamMethod", "method")),
              "planned_tests": (("Disease", "disease"), ("Test", "test"))}[kind]
    return {(concept, candidate[field]) for concept, field in fields}


def validate_conversion(prepared, unit_id, atomic_response, response):
    atomic = validate_atomic(prepared, unit_id, atomic_response)
    source, unit = load_prepared(prepared, unit_id)
    value = ConversionResult.model_validate_json(response).model_dump(mode="json")
    checked = validate_response(source, encode(value["candidates"]))
    claims = {claim["claim_id"]: claim for claim in atomic["claims"]}
    pointers = {f"/{kind}/{index}": (kind, candidate) for kind, candidates in value["candidates"].items()
                for index, candidate in enumerate(candidates)}
    linked = set()
    seen = set()
    for link in value["links"]:
        pointer, ids = link["candidate"], link["claim_ids"]
        if pointer in seen or pointer not in pointers or len(set(ids)) != len(ids) or not set(ids) <= claims.keys():
            raise ValueError("Require one valid link per candidate and known unique claim IDs")
        seen.add(pointer)
        linked.update(ids)
        kind, candidate = pointers[pointer]
        wanted = candidate_concepts(kind, candidate)
        for claim_id in ids:
            claim = claims[claim_id]
            supplied = {(concept["kind"], concept["term"]) for concept in claim["concepts"]}
            primary = {pair for pair in wanted if pair[0] != "AttributeValue"}
            if claim["relation_type"] != kind or not primary <= supplied:
                raise ValueError("A linked claim must support the same typed concept pair")
            if claim["source_basis"] == "differential" and candidate["features"]:
                raise ValueError("Differential associations cannot acquire expected-status or qualification features")
        supplied = {(concept["kind"], concept["term"]) for cid in ids for concept in claims[cid]["concepts"]}
        if wanted != supplied:
            raise ValueError("Conversion introduced or dropped a linked concept or qualifier")
        evidence = [span for cid in ids for span in claims[cid]["evidence"]]
        for span in grounded_evidence(source, candidate):
            if not any(original["start_line"] <= span["start_line"] <= span["end_line"] <= original["end_line"]
                       and span["quote"] in original["quote"] for original in evidence):
                raise ValueError("Candidate evidence must be contained in linked atomic evidence")
    excluded = [item["claim_id"] for item in value["excluded_claims"]]
    if (seen != pointers.keys() or len(set(excluded)) != len(excluded)
            or not set(excluded) <= claims.keys() or set(excluded) & linked
            or set(excluded) | linked != claims.keys()
            or any(not item["reason"].strip() for item in value["excluded_claims"])):
        raise ValueError("Account for every candidate and every claim without unexplained losses")
    review_items = [{"candidate": pointer, "candidate_value": candidate,
                     "claims": [claims[cid] for link in value["links"] if link["candidate"] == pointer
                                for cid in link["claim_ids"]]}
                    for pointer, (_, candidate) in pointers.items()]
    return {**checked, "workflow_version": 2, "unit_id": unit_id,
            "prepared_sha256": atomic["prepared_sha256"], "atomic_response_sha256": atomic["response_sha256"],
            "conversion_response_sha256": digest(response.encode() if isinstance(response, str) else response),
            "links": value["links"], "excluded_claims": value["excluded_claims"], "review_items": review_items,
            "group_context": unit["group_context"],
            "semantic_validation": "not_run", "quality_admission": "not_run"}


def record_review(validated, response):
    review = ClinicalReview.model_validate_json(response).model_dump(mode="json")
    pointers = {item["candidate"] for item in validated["review_items"]}
    decisions = review["decisions"]
    if (review["validation_sha256"] != digest(encode(validated).encode())
            or not review["reviewer"].strip()
            or {item["candidate"] for item in decisions} != pointers
            or len(decisions) != len(pointers)
            or any(not item["reason"].strip() for item in decisions)):
        raise ValueError("Bind clinical review to this complete validation packet and every candidate")
    state = ("rejected" if any(item["decision"] == "rejected" for item in decisions)
             else "approved" if pointers else "reviewed_empty")
    return {**validated, "clinical_review": state, "clinical_review_record": review,
            "quality_admission": "not_run", "rdf_admission": "not_run", "submission_admission": "not_run"}


def main():
    parser = argparse.ArgumentParser(description="Prepare and validate two-stage inputs; never call an LLM")
    commands = parser.add_subparsers(dest="command", required=True)
    schemas = commands.add_parser("schemas")
    schemas.add_argument("--output-dir", type=Path, required=True)
    review_digest = commands.add_parser("review-digest")
    review_digest.add_argument("--validated", type=Path, required=True)
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("--selection", type=Path, required=True)
    prepare_command.add_argument("--output", type=Path, required=True)
    for name in ("prompt-direct", "validate-direct", "prompt-atomic", "validate-atomic",
                 "prompt-conversion", "validate-conversion", "review"):
        command = commands.add_parser(name)
        command.add_argument("--prepared", type=Path, required=True)
        command.add_argument("--unit", required=True)
        command.add_argument("--output", type=Path, required=True)
        if "conversion" in name or name == "review":
            command.add_argument("--atomic-response", type=Path, required=True)
        if name.startswith("validate") or name == "review":
            command.add_argument("--response", type=Path, required=True)
        if name == "review":
            command.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "review-digest":
            print(digest(encode(json.loads(args.validated.read_text(encoding="utf-8"))).encode()))
            return
        if args.command == "schemas":
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for model, filename in SCHEMAS.values():
                (args.output_dir / filename).write_text(encode(model.model_json_schema()), encoding="utf-8")
            print("Write four generated preparation schemas")
            return
        if args.command == "prepare":
            output = encode(prepare(json.loads(args.selection.read_text(encoding="utf-8"))))
        else:
            prepared = json.loads(args.prepared.read_text(encoding="utf-8"))
            if args.command == "prompt-direct":
                output = direct_prompt(prepared, args.unit)
            elif args.command == "validate-direct":
                output = encode(validate_direct(prepared, args.unit, args.response.read_bytes()))
            elif args.command == "prompt-atomic":
                output = atomic_prompt(prepared, args.unit)
            elif args.command == "validate-atomic":
                output = encode(validate_atomic(prepared, args.unit, args.response.read_bytes()))
            elif args.command == "prompt-conversion":
                output = conversion_prompt(prepared, args.unit, args.atomic_response.read_bytes())
            else:
                validated = validate_conversion(prepared, args.unit, args.atomic_response.read_bytes(),
                                                args.response.read_bytes())
                if args.command == "review":
                    validated = record_review(validated, args.review.read_bytes())
                output = encode(validated)
        args.output.write_text(output, encoding="utf-8")
        print(f"Write {args.output}")
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
