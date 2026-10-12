import argparse
import csv
import json
import re
from pathlib import Path, PurePosixPath

from .vocabulary import ONTOLOGY, ROOT, digest, encode, load_vocabulary, project_vocabulary


GUIDELINES = ROOT / "assets/guidelines"
SCHEMA = ONTOLOGY / "extraction.schema.json"
METADATA = {
    "title": "제목", "organization": "발행기관", "year": "연도",
    "language": "언어", "source_url": "출처 URL", "license": "라이선스",
    "document_type": "문서 유형", "format": "형식",
}


def load_source(document, sha256, start_line, end_line):
    relative = PurePosixPath(document)
    if (relative.is_absolute() or str(relative) != document or ".." in relative.parts
            or len(relative.parts) != 2 or relative.suffix != ".md"
            or relative.name in {"AGENTS.md", "README.md"}):
        raise ValueError("Use a catalog-relative clinical Markdown path")
    path = GUIDELINES / document
    if path.resolve() != path.absolute():
        raise ValueError("Reject symlinked source paths")
    with (GUIDELINES / "catalog.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["파일명"] == document]
    if len(rows) != 1:
        raise ValueError("Require exactly one clinical catalog entry")
    raw = path.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256) or digest(raw) != sha256:
        raise ValueError("Source SHA-256 mismatch")
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    if not 1 <= start_line <= end_line <= len(lines):
        raise ValueError("Invalid permitted source line range")
    frontmatter = {}
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            match = re.fullmatch(r"([a-z_]+):\s*(.*?)\s*", line.rstrip("\r\n"))
            if match and match[1] in METADATA:
                value = match[2]
                if value.startswith('"'):
                    value = json.loads(value)
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1].replace("''", "'")
                frontmatter[match[1]] = value
    catalog = {key: rows[0][column] for key, column in METADATA.items()}
    sections = []
    contexts = {}
    for number, line in enumerate(lines, 1):
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line.rstrip("\r\n"))
        if heading:
            level = len(heading[1])
            sections = [(depth, title) for depth, title in sections if depth < level]
            sections.append((level, heading[2]))
        contexts[number] = [title for _, title in sections]
    return {
        "document": document, "source_group": relative.parts[0], "sha256": sha256,
        "start_line": start_line, "end_line": end_line,
        "catalog": catalog, "frontmatter": frontmatter,
        "lines": lines, "sections": contexts,
    }


def source_metadata(source):
    return {key: value for key, value in source.items() if key not in {"lines", "sections"}}


def require_schema():
    from .models import ExtractionResult
    schema = ExtractionResult.model_json_schema()
    if SCHEMA.read_text(encoding="utf-8") != encode(schema):
        raise ValueError("Regenerate the extraction JSON Schema before using the handoff")
    return schema


def build_prompt(source):
    require_schema()
    instructions = Path(__file__).with_name("extraction_prompt.md").read_text(encoding="utf-8")
    excerpt = "\n".join(f"{number}: {source['lines'][number - 1].rstrip(chr(10)).rstrip(chr(13))}"
                        for number in range(source["start_line"], source["end_line"] + 1))
    context = source["sections"][source["start_line"]]
    return (instructions + "\nSource metadata:\n" + encode(source_metadata(source))
            + "Section context at excerpt start:\n" + encode(context)
            + "\nBEGIN UNTRUSTED SOURCE EXCERPT\n" + excerpt
            + "\nEND UNTRUSTED SOURCE EXCERPT\nReturn only the schema-conforming JSON.\n")


def validate_response(source, response):
    from .models import ExtractionResult
    require_schema()
    result = ExtractionResult.model_validate_json(response)
    grounded = []
    value = result.model_dump(mode="json")

    def visit(node, pointer):
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "evidence":
                    for index, span in enumerate(child):
                        start, end = span["start_line"], span["end_line"]
                        if not source["start_line"] <= start <= end <= source["end_line"]:
                            raise ValueError(f"Evidence exceeds the permitted range: {pointer}")
                        if span["quote"] not in "".join(source["lines"][start - 1:end]):
                            raise ValueError(f"Quote is absent from its original lines: {pointer}")
                        grounded.append({"pointer": f"{pointer}/evidence/{index}",
                                         "sections": source["sections"][start], **span})
                else:
                    visit(child, f"{pointer}/{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{pointer}/{index}")

    visit(value, "")
    return {
        "status": "candidate_validated", "schema_version": 1,
        "vocabulary_terms_sha256": load_vocabulary()["terms_sha256"],
        "schema_sha256": digest(SCHEMA.read_bytes()),
        "response_sha256": digest(response.encode("utf-8") if isinstance(response, str) else response),
        "source": source_metadata(source), "grounded_evidence": grounded,
        "candidates": value, "clinical_review": "not_run", "rdf_admission": "not_run",
        "submission_admission": "not_run",
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare and validate offline ontology candidates; never invoke a model")
    commands = parser.add_subparsers(dest="command", required=True)
    vocabulary = commands.add_parser("vocabulary")
    vocabulary.add_argument("--baseline", type=Path, required=True)
    vocabulary.add_argument("--output", type=Path, required=True)
    schema = commands.add_parser("schema")
    schema.add_argument("--output", type=Path, required=True)
    for name in ("prompt", "validate"):
        command = commands.add_parser(name)
        command.add_argument("--document", required=True, help="Path relative to assets/guidelines")
        command.add_argument("--sha256", required=True)
        command.add_argument("--start-line", type=int, required=True)
        command.add_argument("--end-line", type=int, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "validate":
            command.add_argument("--response", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "vocabulary":
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))["terms"]
            output = encode(project_vocabulary(baseline))
        elif args.command == "schema":
            from .models import ExtractionResult
            output = encode(ExtractionResult.model_json_schema())
        else:
            source = load_source(args.document, args.sha256, args.start_line, args.end_line)
            output = (build_prompt(source) if args.command == "prompt" else
                      encode(validate_response(source, args.response.read_bytes())))
        args.output.write_text(output, encoding="utf-8")
        print(f"Write {args.output}")
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
