import hashlib
import json
from pathlib import Path

from rdflib import Graph, Namespace, RDF


ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "data/ontology"
REGISTRY = ONTOLOGY / "extraction-vocabulary.json"
COUNTS = {
    "Disease": 100, "Symptom": 100, "ExamFinding": 60,
    "AttributeValue": 100, "ContextFactor": 60, "Test": 40, "ExamMethod": 50,
}
ATTRIBUTES = (
    "Location", "Laterality", "Quality", "Onset", "Course", "EpisodeDuration",
    "Frequency", "Timing", "Severity", "Trigger", "AggravatingFactor",
    "RelievingFactor", "Radiation",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def terms_digest(terms):
    return digest(json.dumps(terms, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))


def approved_tables():
    document = (ONTOLOGY / "vocabulary-candidates.md").read_text(encoding="utf-8")
    terms = {}
    for kind, count in COUNTS.items():
        heading = f"## {kind} — {count} terms"
        if document.count(heading) != 1:
            raise ValueError(f"Require exactly one approved {kind} table")
        section = document.split(heading, 1)[1].split("\n## ", 1)[0]
        numbered = {}
        for line in section.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[0].isdigit() and cells[2].isdigit():
                for number, term in ((int(cells[0]), cells[1]), (int(cells[2]), cells[3])):
                    if number in numbered:
                        raise ValueError(f"Duplicate {kind} table number: {number}")
                    numbered[number] = term
        if set(numbered) != set(range(1, count + 1)):
            raise ValueError(f"Incomplete approved {kind} numbering")
        values = [numbered[number] for number in range(1, count + 1)]
        if len({value.casefold() for value in values}) != count or any(not v for v in values):
            raise ValueError(f"Duplicate or empty approved {kind} label")
        terms[kind] = values
    return terms


def project_vocabulary(baseline):
    terms = approved_tables()
    if terms != baseline:
        raise ValueError("Approved term names or ordering differ from the retained baseline")
    receipt_path = ONTOLOGY / "vocabulary-approval.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt["status"] != "approved" or receipt["object_counts"] != COUNTS
            or receipt["total_review_items"] != 510):
        raise ValueError("Require the clinician-approved seven-table receipt")
    ow = Namespace("urn:ontoward:")
    graph = Graph().parse(ONTOLOGY / "schema.ttl", format="turtle")
    graph.parse(ONTOLOGY / "vocabulary.ttl", format="turtle")
    declared = {str(node).removeprefix(str(ow))
                for node in graph.subjects(RDF.type, ow.FindingAttribute)}
    if declared != set(ATTRIBUTES):
        raise ValueError("FindingAttribute declarations differ from D08")
    return {
        "version": 1,
        "approval_receipt_sha256": digest(receipt_path.read_bytes()),
        "approved_document_sha256": receipt["approved_artifact_sha256"],
        "annotated_document_sha256": digest((ONTOLOGY / "vocabulary-candidates.md").read_bytes()),
        "terms_sha256": terms_digest(terms),
        "ontology_schema_sha256": digest((ONTOLOGY / "schema.ttl").read_bytes()),
        "starter_vocabulary_sha256": digest((ONTOLOGY / "vocabulary.ttl").read_bytes()),
        "counts": COUNTS,
        "terms": terms,
        "finding_attributes": list(ATTRIBUTES),
        "clinical_review": "not_run",
        "rdf_admission": "not_run",
    }


def load_vocabulary():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if registry != project_vocabulary(registry["terms"]):
        raise ValueError("Regenerate the extraction vocabulary after reconciling its input hashes")
    return registry
