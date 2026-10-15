from pathlib import Path
from string import Formatter
import unicodedata

from rdflib import Graph, RDF, RDFS

from .v5 import OW, write


def prepare_texts(preview: Path, wording: dict, output: Path):
    graph = Graph().parse(preview / "vocabulary.ttl", format="turtle")
    labels = {str(OW["SymptomSnomedCT" + key]): value for key, value in wording["symptoms"].items()}
    labels.update({str(OW[key]): value for key, value in wording["attributes"].items()})
    symptoms = sorted(graph.subjects(RDF.type, OW.Symptom), key=str)
    attributes = sorted(graph.subjects(RDF.type, OW.FindingAttribute), key=str)
    missing = {str(node) for node in symptoms if not any(label.language == "ko" for label in graph.objects(node, RDFS.label))}
    if set(labels) != missing | {str(node) for node in attributes}:
        raise ValueError("Korean wording must cover exactly the missing symptoms and current attributes")
    questions = {str(OW[key]): value for key, value in wording["question_templates"].items()}
    if set(questions) != {str(node) for node in attributes}:
        raise ValueError("Every admitted attribute requires a question")
    for target in symptoms:
        label = labels.get(str(target)) or str(next(label for label in graph.objects(target, RDFS.label) if label.language == "ko"))
        questions[str(target)] = f"{label} 있나요?"
    questions.update(wording.get("question_overrides", {}))
    failures = []
    for target in symptoms:
        label = labels.get(str(target)) or str(next(label for label in graph.objects(target, RDFS.label) if label.language == "ko"))
        for key in [target, *graph.objects(target, OW.hasAttribute)]:
            template = questions.get(f"{target}|{key}", questions[str(key)])
            fields = {field for _, field, _, _ in Formatter().parse(template) if field is not None}
            if fields - {"symptom"}:
                raise ValueError("Question templates allow only the symptom placeholder")
            text = template.replace("{symptom}", label)
            if unicodedata.normalize("NFC", text) != text or not 1 <= len(text) <= 30:
                failures.append({"key": f"{target}|{key}", "text": text, "length": len(text)})
    if failures:
        raise ValueError(f"Review overlong question wording: {failures}")
    write(output / "labels.ko.json", dict(sorted(labels.items())))
    write(output / "questions.ko.json", dict(sorted(questions.items())))
    return {"symptom_questions": len(symptoms), "attribute_templates": len(attributes), "display_labels": len(labels),
            "question_overrides": len(wording.get("question_overrides", {}))}
