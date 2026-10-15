from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import unicodedata

from rdflib import Graph, Namespace, RDF, RDFS, SKOS


ROOT = Path(__file__).resolve().parents[2]
OW = Namespace("urn:ontoward:")
VERSION = "education-excerpts-1"
STATUS = "draft_pending_user_review"
CATALOG_FIELDS = dict(zip(
    ("파일명", "제목", "발행기관", "연도", "언어", "문서 유형", "형식", "라이선스", "출처 URL"),
    ("path", "title", "organization", "year", "language", "document_type", "format", "license", "source_url"),
))
GUIDANCE = {"진료지침", "권고문", "합의문"}
TEXTBOOK = "질환 개요(교과서)"
STOPWORDS = set("a an the and or of in with without to for on by disease diseases disorder disorders syndrome clinical practice guideline guidelines management treatment diagnosis type".split())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def inside(root: Path, value: str | Path) -> Path:
    root = root.resolve()
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path leaves its owner: {value}")
    return resolved


def source_path(root: Path, relative: str) -> Path:
    name = PurePosixPath(relative)
    if not relative or name.is_absolute() or ".." in name.parts or "\\" in relative or name.suffix != ".md":
        raise ValueError(f"Invalid catalog document path: {relative}")
    return inside(root / "assets/guidelines", relative)


def output_path(root: Path, value: str | Path) -> Path:
    path = inside(root, value)
    if not any(path.is_relative_to(root / base) for base in ("data/preparation/education", "Tmp")):
        raise ValueError("Education output must stay in data/preparation/education or Tmp")
    return path


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def normalized(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", text).casefold()).split())


def eligible(source: dict) -> bool:
    title = source["title"].casefold()
    return (source["document_type"] in GUIDANCE | {TEXTBOOK}
            and not any(term in title for term in ("(nursing)", "(archived)", "[archived]")))


def candidates(disease: dict, sources: dict) -> list[dict]:
    names = {normalized(name) for name in [*disease["labels"].values(), *disease["aliases"]] if name.strip()}
    names.discard("")
    terms = set().union(*(set(name.split()) - STOPWORDS for name in names)) if names else set()
    matches = []
    for path, source in sources.items():
        if not source["candidate_eligible"]:
            continue
        title = normalized(source["title"])
        overlap = terms & (set(title.split()) - STOPWORDS)
        if title in names:
            rank, basis = 0, "exact_title_or_alias"
        elif any(len(name) >= 4 and f" {name} " in f" {title} " for name in names):
            rank, basis = 1, "title_contains_label"
        elif len(overlap) >= 2 and len(overlap) >= len(terms) / 2:
            rank, basis = 2, "shared_title_terms"
        else:
            continue
        match = {"source": path, "basis": basis}
        year = int(source["year"]) if source["year"].isdigit() else 0
        matches.append(((rank, source["document_type"] not in GUIDANCE, -year, path), match))
    return [match for _, match in sorted(matches)[:12]]


def runtime_inputs(root: Path) -> tuple[dict, list[dict]]:
    submission = root / "submission"
    path = inside(submission / "knowledge", "manifest.json")
    data = path.read_bytes()
    manifest = json.loads(data)
    if manifest.get("preparation_status") != "admitted":
        raise ValueError("Education inventory requires admitted runtime knowledge")
    graph, assets = Graph(), []
    for name in ("schema", "vocabulary", "bundles", "scoring_policy", "labels", "questions", "plans"):
        entries = manifest.get(name, []) if name == "bundles" else [manifest[name]] if name in manifest else []
        for entry in entries:
            asset = inside(submission, entry["path"])
            if not asset.is_relative_to(submission / "knowledge"):
                raise ValueError("Runtime asset leaves submission/knowledge")
            raw = asset.read_bytes()
            if sha256(raw) != entry["sha256"]:
                raise ValueError(f"Runtime asset digest mismatch: {entry['path']}")
            assets.append({"path": asset.relative_to(root).as_posix(), "sha256": sha256(raw)})
            if name in {"schema", "vocabulary", "bundles"}:
                graph.parse(data=raw.decode("utf-8"), format="turtle")
    diseases = []
    for node in sorted(set(graph.subjects(RDF.type, OW.Disease)), key=str):
        labels = {}
        for label in sorted(graph.objects(node, RDFS.label), key=str):
            labels.setdefault(label.language or "und", str(label))
        diseases.append({"id": str(node), "labels": labels,
                         "aliases": sorted({str(value) for predicate in (RDFS.label, SKOS.altLabel)
                                            for value in graph.objects(node, predicate)})})
    if not diseases:
        raise ValueError("Runtime graph contains no Diseases")
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256(data), "assets": assets}, diseases


def inventory(root: Path) -> dict:
    runtime, diseases = runtime_inputs(root)
    catalog = root / "assets/guidelines/catalog.csv"
    raw = catalog.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if reader.fieldnames != list(CATALOG_FIELDS):
        raise ValueError("Guideline catalog columns differ from the source contract")
    sources = {}
    for row in reader:
        source = {name: row[key] for key, name in CATALOG_FIELDS.items()}
        path = source_path(root, source["path"])
        if source["path"] in sources:
            raise ValueError(f"Duplicate catalog source: {source['path']}")
        source["sha256"] = sha256(path.read_bytes())
        source["candidate_eligible"] = eligible(source)
        sources[source["path"]] = source
    sources = dict(sorted(sources.items()))
    for disease in diseases:
        disease["candidates"] = candidates(disease, sources)
    return {"version": VERSION, "status": STATUS, "runtime_manifest": runtime,
            "catalog": {"path": catalog.relative_to(root).as_posix(), "sha256": sha256(raw)},
            "diseases": diseases, "sources": sources}


def check_inputs(root: Path, saved: dict) -> None:
    if saved.get("version") != VERSION or saved.get("status") != STATUS:
        raise ValueError("Education inventory must remain a review draft")
    runtime, diseases = runtime_inputs(root)
    if runtime != saved["runtime_manifest"]:
        raise ValueError("Runtime inventory changed; create a new reviewed inventory")
    original = [{k: v for k, v in disease.items() if k != "candidates"} for disease in saved["diseases"]]
    if original != diseases:
        raise ValueError("Disease inventory differs from the runtime graph")
    catalog = root / "assets/guidelines/catalog.csv"
    if saved["catalog"] != {"path": catalog.relative_to(root).as_posix(), "sha256": sha256(catalog.read_bytes())}:
        raise ValueError("Guideline catalog changed; create a new inventory")
    with catalog.open(encoding="utf-8-sig", newline="") as stream:
        rows = [{name: row[key] for key, name in CATALOG_FIELDS.items()} for row in csv.DictReader(stream)]
    if set(saved["sources"]) != {row["path"] for row in rows}:
        raise ValueError("Inventory differs from the catalog allowlist")
    for row in rows:
        source = saved["sources"][row["path"]]
        if any(source.get(key) != value for key, value in row.items()) or source["candidate_eligible"] != eligible(row):
            raise ValueError(f"Catalog metadata mismatch: {row['path']}")
        if sha256(source_path(root, row["path"]).read_bytes()) != source["sha256"]:
            raise ValueError(f"Source digest mismatch: {row['path']}")


def document(raw: bytes) -> tuple[dict, list[bytes], list[dict]]:
    lines = raw.splitlines(keepends=True)
    text = [line.decode("utf-8") for line in lines]
    if not text or text[0].strip() != "---":
        raise ValueError("Clinical document lacks YAML source metadata")
    end = next((index for index in range(1, len(text)) if text[index].strip() == "---"), None)
    if end is None:
        raise ValueError("Unclosed source metadata")
    metadata = {}
    for line in text[1:end]:
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError("Expected scalar source metadata")
        value = value.strip()
        metadata[key] = json.loads(value) if value.startswith('"') else value.strip("'")
    required = {"title", "organization", "year", "language", "source_url", "license"}
    if not required <= metadata.keys() or any(not str(metadata[key]).strip() for key in required):
        raise ValueError("Clinical document lacks required provenance")
    headings, stack, fenced = [], [], False
    for index, line in enumerate(text[end + 1:], end + 2):
        if re.match(r"^\s{0,3}(```|~~~)", line):
            fenced = not fenced
        match = None if fenced else re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match:
            depth, title = len(match[1]), match[2].strip()
            while stack and stack[-1]["depth"] >= depth:
                stack.pop()
            heading = {"depth": depth, "title": title, "start_line": index,
                       "heading_path": [*[entry["title"] for entry in stack], title]}
            headings.append(heading)
            stack.append(heading)
    for index, heading in enumerate(headings):
        heading["end_line"] = next((later["start_line"] - 1 for later in headings[index + 1:]
                                     if later["depth"] <= heading["depth"]), len(lines))
    return metadata, lines, headings


def extract(root: Path, saved: dict, mapping: dict) -> dict:
    path = mapping["source"]
    if path not in saved["sources"] or not saved["sources"][path]["candidate_eligible"]:
        raise ValueError(f"Source is outside the eligible catalog: {path}")
    source = saved["sources"][path]
    if mapping["source_sha256"] != source["sha256"]:
        raise ValueError(f"Mapping source pin differs: {path}")
    raw = source_path(root, path).read_bytes()
    if sha256(raw) != source["sha256"]:
        raise ValueError(f"Source digest mismatch: {path}")
    metadata, lines, headings = document(raw)
    for key in ("title", "organization", "year", "source_url", "license"):
        if metadata[key] != source[key]:
            raise ValueError(f"Document provenance differs from catalog: {path}:{key}")
    start, end = mapping["start_line"], mapping["end_line"]
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
        raise ValueError(f"Invalid excerpt range: {path}")
    sections = [heading for heading in headings if heading["heading_path"] == mapping["heading_path"]
                and heading["start_line"] <= start <= end <= heading["end_line"]]
    if len(sections) != 1:
        raise ValueError(f"Missing or ambiguous heading at the specified range: {path}")
    section = sections[0]
    mode = mapping["selection"]
    if mode not in {"section", "lines"} or mode == "section" and (start, end) != (section["start_line"], section["end_line"]):
        raise ValueError("Section selections must retain the entire section including child headings")
    excerpt = b"".join(lines[start - 1:end])
    body = [line for line in excerpt.decode("utf-8").splitlines() if line.strip() and not re.match(r"^\s*#", line)]
    if not body:
        raise ValueError(f"Empty clinical excerpt: {path}")
    for field in ("reason", "applicability", "limitations", "identity_evidence", "authority_evidence", "context_review"):
        if not isinstance(mapping.get(field), str) or not mapping[field].strip():
            raise ValueError(f"Mapping requires an explicit {field}")
    role = mapping.get("document_role")
    if role not in {"clinical_guidance", "clinician_textbook"} or (role == "clinical_guidance") != (source["document_type"] in GUIDANCE):
        raise ValueError("Mapping role differs from the eligible source type")
    result = {key: mapping[key] for key in ("source", "source_sha256", "heading_path", "start_line", "end_line", "selection",
                                          "reason", "applicability", "limitations", "identity_evidence", "authority_evidence",
                                          "context_review", "document_role")}
    result.update(provenance=metadata, text=excerpt.decode("utf-8"), excerpt_sha256=sha256(excerpt))
    result["id"] = sha256(json_bytes([path, source["sha256"], start, end]))
    return result


def render(root: Path, saved: dict, mappings: dict, inventory_hash: str, mappings_hash: str,
           report_directory: Path) -> tuple[bytes, bytes, dict]:
    check_inputs(root, saved)
    if mappings.get("version") != VERSION or mappings.get("status") != STATUS or mappings.get("inventory_sha256") != inventory_hash:
        raise ValueError("Mappings require the exact draft inventory pin")
    entries = mappings["diseases"]
    diseases = {entry["id"]: entry for entry in saved["diseases"]}
    if len(entries) != len(diseases) or {entry["disease_id"] for entry in entries} != set(diseases):
        raise ValueError("Mappings must cover every runtime Disease exactly once")
    excerpts, counts = [], Counter()
    report = ["# 질환별 교육 원문 검토 초안", "", "상태: 사용자 검토 전 초안. 임상 승인·제출 편입·환자 전달은 수행하지 않았습니다.", "",
              f"- 런타임 질환: {len(diseases):,}개", f"- Inventory SHA-256: `{inventory_hash}`",
              f"- Mappings SHA-256: `{mappings_hash}`", "",
              "공식·학회 임상지침을 우선하고 교과서를 보완 원천으로 선택합니다. 모든 내용은 보유 문서의 고정된 원문이며 최신성의 외부 확인은 수행하지 않았습니다.",
              "문서별 라이선스는 출처 메타데이터입니다. 이 초안은 제출 외 전처리 영역에 보관하며 재배포 허가를 의미하지 않습니다.", "",
              "[원문 발췌 JSONL](excerpts.jsonl)은 각 발췌 ID와 전체 원문을 담습니다. 아래 출처 링크와 줄 범위로 원문을 직접 대조할 수 있습니다.", "",
              "## 질환별 매핑", ""]
    seen = set()
    for entry in sorted(entries, key=lambda item: item["disease_id"]):
        disease_id = entry["disease_id"]
        disease = diseases[disease_id]
        label = disease["labels"].get("ko") or disease["labels"].get("en") or next(iter(disease["labels"].values()), disease_id)
        status = entry["disposition"]
        selections = entry.get("selections", [])
        if status not in {"mapped_draft", "needs_review", "no_suitable_source_selected"} or bool(selections) != (status == "mapped_draft"):
            raise ValueError("Disposition must distinguish selected excerpts from unresolved candidates")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise ValueError("Every Disease requires a concrete selection or gap reason")
        counts[status] += 1
        report += [f"### {label}", "", f"- 질환: `{disease_id}`", f"- 상태: `{status}`", f"- 판단: {entry['reason']}"]
        for review in entry.get("source_reviews", []):
            if review.get("source") not in saved["sources"] or not isinstance(review.get("reason"), str) or not review["reason"].strip():
                raise ValueError("Source reviews require catalog identity and a concrete reason")
            report.append(f"- 원천 검토: `{review['source']}` — {review['reason']}")
        shown_sources = set()
        for mapping in selections:
            excerpt = extract(root, saved, mapping)
            key = (disease_id, excerpt["id"])
            if key in seen:
                raise ValueError("Duplicate excerpt mapping for one Disease")
            seen.add(key)
            excerpt.update(disease_id=disease_id, status=STATUS)
            excerpts.append(excerpt)
            source = saved["sources"][mapping["source"]]
            relative = Path(os.path.relpath(source_path(root, mapping["source"]), report_directory)).as_posix()
            if mapping["source"] not in shown_sources:
                shown_sources.add(mapping["source"])
                report += [f"- 원문: [{source['title']}]({relative}) — {source['organization']}, {source['year']}",
                           f"- 질환 확인: {mapping['identity_evidence']}", f"- 문서 역할 확인: {mapping['authority_evidence']}",
                           f"- 적용 대상: {mapping['applicability']}", f"- 제한: {mapping['limitations']}",
                           f"- 조건·예외 보존: {mapping['context_review']}",
                           f"- 출처: [{source['source_url']}]({source['source_url']}); {source['license']}"]
            report.append(f"- 구간: {' → '.join(mapping['heading_path'])}; 줄 {mapping['start_line']}–{mapping['end_line']}; 발췌 ID `{excerpt['id']}`")
        if not selections and disease["candidates"]:
            report.append("- 검토할 문서 후보:")
            for candidate in disease["candidates"][:4]:
                source = saved["sources"][candidate["source"]]
                report.append(f"  - {source['title']} ({source['year']}, {candidate['basis']}); `{candidate['source']}`")
        report.append("")
    summary = {"version": VERSION, "status": STATUS, "diseases": len(diseases), "catalog_sources": len(saved["sources"]),
               "dispositions": dict(sorted(counts.items())), "excerpts": len(excerpts),
               "selected_documents": len({entry["source"] for entry in excerpts}),
               "excerpt_roles": dict(sorted(Counter(entry["document_role"] for entry in excerpts).items())),
               "document_roles": dict(sorted(Counter({entry["source"]: entry["document_role"] for entry in excerpts}.values()).items())),
               "runtime_admission": "not_run", "independent_clinical_validation": "not_run"}
    report[9:9] = [f"- 연결 초안: {counts['mapped_draft']:,}개; 추가 검토: {counts['needs_review']:,}개; 적합 원천 미선택: {counts['no_suitable_source_selected']:,}개",
                   f"- 발췌: {len(excerpts):,}개; 원천 문서: {summary['selected_documents']:,}개", ""]
    payload = b"".join(json.dumps(entry, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n" for entry in excerpts)
    return payload, ("\n".join(report) + "\n").encode("utf-8"), summary


def batch(root: Path, inventory_file: Path, mappings_file: Path, output: Path, *, verify: bool) -> dict:
    inventory_file, mappings_file = inside(root, inventory_file), inside(root, mappings_file)
    output = output_path(root, output)
    raw = inventory_file.read_bytes()
    saved, mappings = json.loads(raw), json.loads(mappings_file.read_bytes())
    excerpts, report, summary = render(root, saved, mappings, sha256(raw), sha256(mappings_file.read_bytes()), output)
    for name, payload in (("excerpts.jsonl", excerpts), ("review.md", report)):
        path = output / name
        if verify:
            if path.read_bytes() != payload:
                raise ValueError(f"Generated artifact differs from its pinned mapping: {name}")
        else:
            write(path, payload)
    return {**summary, "result": "pass", "mode": "verify" if verify else "build",
            "inventory_sha256": sha256(raw), "mappings_sha256": sha256(mappings_file.read_bytes()),
            "excerpts_sha256": sha256(excerpts), "report_sha256": sha256(report),
            "preserved_catalog_documents": len(saved["sources"]), "preserved_runtime_assets": len(saved["runtime_manifest"]["assets"])}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare fixed original education excerpts outside submission")
    commands = parser.add_subparsers(dest="command", required=True)
    inv = commands.add_parser("inventory")
    inv.add_argument("--output", required=True, type=Path)
    for name in ("build", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--inventory", required=True, type=Path)
        command.add_argument("--mappings", required=True, type=Path)
        command.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "inventory":
        result = inventory(ROOT)
        write(output_path(ROOT, args.output), json_bytes(result))
        print(json.dumps({"diseases": len(result["diseases"]), "sources": len(result["sources"]), "status": STATUS}))
    else:
        print(json.dumps(batch(ROOT, args.inventory, args.mappings, args.output, verify=args.command == "verify")))


if __name__ == "__main__":
    main()
