from __future__ import annotations

from collections import Counter, defaultdict
import json
import unicodedata

from rdflib import Literal, RDF, RDFS, SKOS, URIRef

from .database import file_hash
from .v5 import OW, ROOT


def normalize(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().replace("–", "-").split())


def project(directory, mapping, builder, questions):
    evidence_path, condition_path = directory / "release_evidences.json", directory / "release_conditions.json"
    evidences = json.loads(evidence_path.read_text())
    conditions = json.loads(condition_path.read_text())
    files = [{"path": path.relative_to(ROOT).as_posix(), "sha256": file_hash(path)}
             for path in [evidence_path, condition_path, directory / "LICENSE.txt"]]
    index = defaultdict(set)
    for uri, entry in builder.registry.items():
        for predicate in (RDFS.label, SKOS.altLabel):
            for label in builder.vocabulary.objects(URIRef(uri), predicate):
                index[(entry["kind"], normalize(str(label)))].add(uri)

    def existing(names, kind):
        found = set().union(*(index[(kind, normalize(name))] for name in names))
        return next(iter(found)) if len(found) == 1 else None

    def reference(filename, identifier):
        return "ddxplus:v2:" + filename + ":" + str(identifier)

    retained, attributes, targets, dispositions = set(), set(), {}, {}
    for code, row in sorted(evidences.items()):
        specification = mapping.get("contexts" if row["is_antecedent"] else "symptoms", {}).get(code)
        if specification is None:
            dispositions[code] = {"status": "unresolved", "reason": "compound_or_qualified_evidence_not_projected", "raw": row}
            continue
        label, *rest = specification
        kind = "ContextFactor" if row["is_antecedent"] else "Symptom"
        if row["data_type"] != "B":
            raise ValueError("Explicit binary mappings cannot reinterpret categorical evidence")
        if kind == "ContextFactor":
            context_type, text = rest
            uri = str(OW) + "DdxContext" + code
        else:
            text = rest[0]
            uri = existing([label], kind) or str(OW) + "DdxSymptom" + code
        ref = reference(evidence_path.name, code)
        if uri not in builder.registry:
            builder.concept(uri, kind, label, source_refs=[ref])
            questions[uri] = {"text": text, "answer_type": "presence", "affirmative": True, "interviewable": True}
        else:
            builder.registry[uri]["source_refs"] = sorted(set(builder.registry[uri]["source_refs"]) | {ref})
        builder.registry[uri].setdefault("external_mappings", []).append({
            "dataset": "DDXPlus", "id": code, "mapping_relation": "exact", "source_question": row["question_en"]})
        if kind == "ContextFactor":
            builder.vocabulary.set((URIRef(uri), OW.contextType, Literal(context_type)))
        retained.add(uri)
        targets[code] = uri
        dispositions[code] = {"status": "mapped", "role": kind, "target": uri, "raw": row}

    for code, specification in mapping["attributes"].items():
        row = evidences[code]
        if code in mapping.get("deferred_evidences", {}):
            dispositions[code] = {"status": "unresolved", "reason": mapping["deferred_evidences"][code], "raw": row}
            continue
        if row["data_type"] not in {"C", "M"}:
            raise ValueError("An attribute requires categorical or multichoice source metadata")
        parent_code = row["code_question"]
        target = targets.get(parent_code)
        if row["is_antecedent"]:
            dispositions[code] = {"status": "unresolved", "reason": "v5_context_has_no_finding_attribute_contract", "raw": row}
            continue
        if target is None:
            dispositions[code] = {"status": "unresolved", "reason": "parent_evidence_unavailable", "raw": row}
            continue
        label, text = specification
        attribute = str(OW) + "DdxAttribute" + code
        ref = reference(evidence_path.name, code)
        builder.concept(attribute, "FindingAttribute", label, source_refs=[ref])
        builder.vocabulary.add((URIRef(target), OW.hasAttribute, URIRef(attribute)))
        values, exclusions = [], []
        for value in row["possible-values"]:
            if value == row["default_value"]:
                exclusions.append({"value": value, "reason": "default_is_not_an_asserted_finding"})
                continue
            if str(value) in mapping.get("excluded_values", {}):
                exclusions.append({"value": value, "reason": mapping["excluded_values"][str(value)]})
                continue
            meaning = row.get("value_meaning", {}).get(str(value), {}).get("en", str(value))
            uri = str(OW) + "DdxValue" + code + "_" + str(value)
            builder.concept(uri, "AttributeValue", meaning, source_refs=[ref + ":value:" + str(value)])
            builder.registry[uri]["external_value"] = {"code": value, "meaning": row.get("value_meaning", {}).get(str(value)),
                                                        "data_type": row["data_type"], "clinical_unit": None}
            builder.vocabulary.add((URIRef(attribute), OW.canHaveValue, URIRef(uri)))
            values.append(uri)
        questions[target + "|" + attribute] = {"text": text, "answer_type": "category", "affirmative": False}
        attributes.add((target, attribute))
        dispositions[code] = {"status": "mapped_attribute", "target": target, "attribute": attribute,
            "values": values, "excluded_values": exclusions,
            "default_semantics": "not_synthesized_not_negative_evidence", "raw": row}

    disease_mappings, link_dispositions = {}, []
    for code, row in sorted(conditions.items()):
        name = row["condition_name"]
        names = [name, *mapping["conditions"].get(name, [])]
        disease = existing(names, "Disease")
        disease_mappings[code] = {"disease": disease, "status": "mapped" if disease else "disease_identity_unresolved", "raw": row}
        for field in ("symptoms", "antecedents"):
            for evidence_code in sorted(row[field]):
                target = targets.get(evidence_code)
                item = {"condition": code, "evidence": evidence_code, "role": field}
                if disease is None or target is None:
                    item.update(status="unresolved", reason="disease_identity_unresolved" if disease is None else "evidence_mapping_unavailable")
                elif evidences[evidence_code]["data_type"] != "B":
                    item.update(status="record_only", reason="condition_metadata_has_no_expected_attribute_value")
                else:
                    expected_kind = "ContextFactor" if field == "antecedents" else "Symptom"
                    if builder.registry[target]["kind"] != expected_kind:
                        raise ValueError("DDXPlus condition role disagrees with evidence metadata")
                    ref = reference(condition_path.name, str(code) + ":" + evidence_code)
                    if field == "antecedents":
                        builder.vocabulary.add((URIRef(disease), OW.hasSupportingContext, URIRef(target)))
                        builder.vocabulary.add((URIRef(disease), OW.sourceRef, Literal(ref)))
                        item.update(status="mapped_context", disease=disease, target=target, source_ref=ref)
                    else:
                        pattern = builder.pattern(target, [])
                        association = builder.association(disease, pattern, source_ref=ref,
                            relation_basis="external_association", raw={"condition": code, "evidence": evidence_code})
                        item.update(status="mapped_association", association=association, disease=disease, target=target, source_ref=ref)
                link_dispositions.append(item)
    report = {"version": "DDXPlus-English-v2", "license": "CC BY 4.0", "files": files,
        "evidence_count": len(evidences), "condition_count": len(conditions),
        "evidence_statuses": dict(Counter(row["status"] for row in dispositions.values())),
        "condition_statuses": dict(Counter(row["status"] for row in disease_mappings.values())),
        "link_statuses": dict(Counter(row["status"] for row in link_dispositions)),
        "evidences": dispositions, "conditions": disease_mappings, "links": link_dispositions,
        "patient_archives_read": False, "synthetic_probabilities_imported": False}
    return retained, attributes, report
