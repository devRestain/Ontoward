from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import re

from rdflib import Graph, Literal, RDF, RDFS, SKOS, URIRef

from . import authored, ddxplus
from .admission import RULES, review_material
from .database import SourceDatabase, file_hash
from .source_projection import INFERRED, Normalizer, SnapshotSources, target_uri
from .v5 import OW, ROOT, digest, workspace_path, write

DEFAULT_SOURCE = ROOT / "data/preparation/v5/source-only-2026-10-16/findings-2026-10-16/ontology.sqlite3"
DEFAULT_PARENT = ROOT / "data/preparation/v5/competition-graph-2026-10-16/ontology.sqlite3"
DEFAULT_INPUTS = ROOT / "data/preparation/v5/common-complaints-inputs-2026-10-18"
DDXPLUS = ROOT / "assets/nova-benchmarks-2026/DDXPlus"
VERSION = "v5.0.5-common-complaints"
QUALITIES = {"painful": "Painfulness", "painless": "Painfulness", "single": "Multiplicity",
    "multiple": "Multiplicity", "burning": "Quality", "purulent": "Content", "pus filled": "Content",
    "blood in discharge": "Content", "foul smelling": "Odour", "soft in consistency": "Consistency",
    "hard in consistency": "Consistency", "round in shape": "Shape", "red in color": "Colour"}
QUALITY_QUESTIONS = {"Painfulness": "해당 부위에 통증이 있나요?", "Multiplicity": "하나인가요, 여러 개인가요?",
    "Quality": "어떤 양상으로 나타나나요?", "Content": "어떤 내용물이 보이나요?", "Odour": "어떤 냄새가 나나요?",
    "Consistency": "만졌을 때 얼마나 단단한가요?", "Shape": "어떤 모양인가요?", "Colour": "어떤 색인가요?"}


def active_identity(terminology, cid):
    seen, proof = set(), []
    while cid not in seen:
        if terminology.active(cid):
            return cid, proof
        seen.add(cid)
        rows = terminology.connection.execute("""SELECT r.id,s.payload FROM rf2_components r
            JOIN source_rows s ON s.id=r.row_id WHERE r.kind='refset' AND r.active='1'
            AND r.refset_id='900000000000527005' AND r.source_id=?""", (cid,)).fetchall()
        targets = {json.loads(row["payload"])["targetComponentId"] for row in rows}
        if len(targets) != 1:
            return None, proof
        proof.extend("rf2:" + row["id"] for row in rows)
        cid = next(iter(targets))
    return None, proof


def metrics(builder, questions):
    symptoms = set(builder.vocabulary.subjects(RDF.type, OW.Symptom))
    interviewable = [s for s in symptoms if questions.get(str(s), {}).get("interviewable", True)
                     and questions.get(str(s), {}).get("text")]
    counts = sorted(len({target for association in builder.graph.objects(disease, OW.hasAssociation)
        for pattern in builder.graph.objects(association, OW.pattern) for target in builder.graph.objects(pattern, OW.targets)})
        for disease in builder.vocabulary.subjects(RDF.type, OW.Disease))
    return {"classes": {kind: len(set(graph.subjects(RDF.type, OW[kind]))) for kind, graph in
        [(kind, builder.vocabulary) for kind in ("Disease", "Symptom", "ContextFactor", "FindingAttribute", "AttributeValue", "ExamFinding", "ExamMethod", "BodySystem")]
        + [(kind, builder.graph) for kind in ("ClinicalPattern", "ClinicalFeature", "DiseasePatternAssociation")]},
        "interviewable_symptoms": len(interviewable),
        "interviewable_without_attributes": sum(not any(builder.vocabulary.objects(s, OW.hasAttribute)) for s in interviewable),
        "korean_alternative_labels": sum(label.language == "ko" for label in builder.vocabulary.objects(None, SKOS.altLabel)),
        "disease_unique_targets_median": counts[len(counts) // 2], "diseases_with_at_most_two_targets": sum(n <= 2 for n in counts)}


def add_source_terms(builder, terminology):
    entries = {uri: entry for uri, entry in builder.registry.items() if entry.get("snomed_id")}
    descriptions = terminology.descriptions({entry["snomed_id"] for entry in entries.values()})
    for uri, entry in entries.items():
        for row in descriptions.get(entry["snomed_id"], {}).get("descriptions", []):
            if row["languageCode"] not in {"ko", "en"}:
                continue
            text = re.sub(r"\s*\([^()]+\)$", "", row["term"]) if row["typeId"] == "900000000000003001" else row["term"]
            authored.aliases(builder, uri, {row["languageCode"]: [text]}, "rf2:description:" + row["id"])


def restore_roots(source, terminology, builder, questions, config):
    rows = source.bodhi_rows("nodes_symptom.csv")
    roots = defaultdict(list)
    for rid, line, row in rows:
        roots[row["root_snomed_id"]].append((rid, line, row))
    known = {entry["snomed_id"]: uri for uri, entry in builder.registry.items()
             if entry.get("snomed_id") and entry["kind"] in {"Symptom", "ExamFinding"}}
    curation = {row["sctid"]: row for row in config["complaints"]}
    exam_config = {row["sctid"]: row for row in config["examinations"]}
    mapped = {cid: active_identity(terminology, cid) for cid in set(roots) | set(curation) | set(exam_config)}
    descriptions = terminology.descriptions({cid for cid, _ in mapped.values() if cid})
    targets, audit, retained = {}, [], set()
    for raw_id in sorted(set(roots) | set(curation) | set(exam_config)):
        cid, proof = mapped[raw_id]
        original = roots.get(raw_id, [])
        row = curation.get(cid, {})
        before = known.get(cid)
        item = {"source_id": raw_id, "active_sctid": cid, "history_refs": proof,
                "source_rows": [r[0] for r in original], "baseline_target": before, "bodhi_root": bool(original)}
        if cid is None:
            item.update(status="id_unresolved", reason="no_unique_active_same_as_mapping")
            audit.append(item)
            continue
        if not before and cid not in curation and cid not in exam_config:
            item.update(status="role_deferred", reason="outside_selected_common_complaints")
            audit.append(item)
            continue
        if cid not in terminology.findings or re.search(r"due to|secondary to|caused by|associated with", terminology.fsns.get(cid, ""), re.I):
            item.update(status="role_unavailable", reason="no_neutral_patient_finding_role")
            audit.append(item)
            continue
        labels = descriptions.get(cid, {}).get("labels", {})
        label = labels.get("en")
        if not label:
            item.update(status="role_unavailable", reason="english_source_label_missing")
            audit.append(item)
            continue
        ref = "prepared:complaints:" + cid
        refs = ["rf2:concept:" + cid, *proof, *[f"source_row:{r[0]}:root_snomed_id" for r in original]]
        uri, kind = before or target_uri(cid), "Symptom"
        if cid in exam_config:
            exam = exam_config[cid]
            if before and builder.registry[before]["kind"] == "Symptom":
                item.update(status="role_deferred", reason="existing_patient_report_role_requires_separate_exam_review")
                audit.append(item)
                continue
            method_rows = terminology.connection.execute("""SELECT id FROM rf2_components WHERE kind='relationship'
                AND active='1' AND characteristic=? AND source_id=? AND type_id='418775008' AND destination_id=?""",
                (INFERRED, cid, exam["method"])).fetchall()
            if not method_rows:
                item.update(status="question_unavailable", reason="physical_method_not_in_source")
                audit.append(item)
                continue
            kind, uri = "ExamFinding", str(OW) + "ExamFindingSnomedCT" + cid
            refs.extend("rf2:" + method["id"] for method in method_rows)
            method = str(OW) + "ExamMethodSnomedCT" + exam["method"]
            builder.concept(method, "ExamMethod", terminology.fsns[exam["method"]].rsplit(" (", 1)[0],
                            snomed_id=exam["method"], source_refs=refs)
            builder.vocabulary.add((URIRef(uri), OW.detectedBy, URIRef(method)))
            builder.vocabulary.set((URIRef(method), OW.examRequestText, Literal(exam["request"])))
        elif before and builder.registry[before]["kind"] == "ExamFinding":
            kind = "ExamFinding"
        if before:
            refs.extend(builder.registry[before]["source_refs"])
            label = builder.registry[before]["label"]
        builder.concept(uri, kind, label, korean=labels.get("ko") if not before else None, snomed_id=cid, source_refs=refs)
        builder.registry[uri].update(source_role="BODHI_patient_report_role" if original else "explicit_prepared_acquisition_role",
                                     role_source_rows=[r[0] for r in original], history_refs=proof)
        if row:
            authored.aliases(builder, uri, {"ko": [row["korean"], *row["aliases"]]}, ref)
            if not list(builder.vocabulary.objects(URIRef(uri), RDFS.label)):
                raise ValueError("Prepared complaint requires source terminology")
            questions.setdefault(uri, {"text": row["question"], "answer_type": "presence", "affirmative": True})
        if kind == "Symptom" and uri not in questions:
            korean = labels.get("ko")
            text = "요즘 " + korean + " 증상이 있나요?" if korean else ""
            usable = bool(text and len(text) <= 30)
            questions[uri] = {"text": text if usable else "", "answer_type": "presence", "affirmative": True,
                              "interviewable": usable, "reason": None if usable else "korean_wording_unavailable"}
        targets[raw_id] = uri
        if cid in curation:
            targets.setdefault(cid, uri)
        retained.add(uri)
        item.update(status="retained" if before else "restored", target=uri, role=kind,
                    question_available=bool(questions.get(uri, {}).get("text")))
        audit.append(item)
    for entry in config.get("ambiguous_expressions", []):
        for cid in entry["sctids"]:
            uri = targets.get(cid) or known.get(cid)
            if uri:
                authored.aliases(builder, uri, {"ko": [entry["phrase"]]}, "prepared:D42:ambiguous_expression")
                builder.registry[uri].setdefault("ambiguous_expressions", []).append(entry)
    return rows, targets, retained, audit


def restore_variants(source, builder, rows, targets):
    normalizer, patterns, dispositions = Normalizer(builder), {}, []
    for rid, line, row in rows:
        target = targets.get(row["root_snomed_id"])
        features, errors = [], []
        for n in range(1, 4):
            axis, raw = row[f"relation{n}_type"], row[f"child{n}_name"]
            if bool(axis) != bool(raw):
                errors.append("incomplete_qualifier")
            elif axis:
                normalizer.source_refs = [f"source_row:{rid}:relation{n}_type:child{n}_name"]
                try:
                    text = raw.strip().casefold()
                    feature = normalizer.categorical(QUALITIES[text], text) if axis == "characteristic" and text in QUALITIES else \
                        normalizer.qualifier(row["root_snomed_id"], axis, raw)
                    features.append(feature)
                except ValueError as error:
                    errors.append(str(error))
        if target and not errors:
            patterns[row["uuid"]] = builder.pattern(target, features)
        dispositions.append({"dataset": "bodhi-s", "source_row_id": rid, "file": "nodes_symptom.csv", "line": line,
            "source_id": row["uuid"], "pattern": patterns.get(row["uuid"]),
            "status": "mapped" if target and not errors else "unresolved",
            "reasons": errors or ([] if target else ["target_role_or_identifier_unavailable"])})
    diseases = {entry["snomed_id"]: uri for uri, entry in builder.registry.items() if entry["kind"] == "Disease"}
    prerequisites = defaultdict(dict)
    for rid, _, row in source.bodhi_rows("edges_has_prerequisite.csv"):
        disease = diseases.get(row["condition_snomed_id_src"])
        context = str(OW) + "BodhiContext" + row["condition_snomed_id_dst"]
        if (disease and context in builder.registry and row["condition_snomed_id_src"] != row["condition_snomed_id_dst"]
                and row["relation_polarity"] == "positive" and row["relation_strength"] in {"rare", "low", "medium", "high", "very_high"}):
            prerequisites[disease][context] = {"concept_id": context, "status": "present", "subject": "family" if
                builder.registry[context].get("context_type") == "family_history" else "patient", "time_context": "unspecified"}
    for rid, line, row in source.bodhi_rows("edges_present_in.csv"):
        disease, pattern = diseases.get(row["condition_snomed_id"]), patterns.get(row["symptom_uuid"])
        prediction, typicality = row["likelihood_condition_given_symptom"].casefold(), row["likelihood_symptom_given_condition"].casefold()
        valid = prediction in {"zero", "rare", "low", "medium", "high", "very_high"} and typicality in {"zero", "rare", "low", "medium", "high", "very_high"}
        if disease and pattern and valid and row["strong_predictor"] in {"", "0", "1"}:
            builder.association(disease, pattern, source_ref=f"bodhi-s:{source.meta('build_id')}:edges_present_in.csv:{line}",
                relation_basis="bodhi_present_in", predictiveness=prediction, typicality=typicality,
                strong_predictor=None if not row["strong_predictor"] else row["strong_predictor"] == "1",
                applicability=list(prerequisites[disease].values()), raw={"source_row_id": rid, "source_claim": row})
    return dispositions


def collect_attributes(builder, questions, config, terminology):
    retained = set()
    for entry in config["complaints"]:
        target = target_uri(entry["sctid"])
        if target not in builder.registry:
            continue
        for name, label, answer in [("TimeSinceOnset", "Time since onset", "duration"),
                                    ("Course", "Course", "category")]:
            attribute = str(OW[name])
            if attribute not in builder.registry:
                builder.concept(attribute, "FindingAttribute", label, source_refs=["policy:D40:common_intake"])
            builder.vocabulary.add((URIRef(target), OW.hasAttribute, URIRef(attribute)))
            questions.setdefault(target + "|" + attribute, {"text": "언제부터 이 증상이 있었나요?" if answer == "duration" else
                "증상이 좋아지거나 나빠지고 있나요?", "answer_type": answer, "affirmative": False})
            retained.add((target, attribute))
    for word, korean in [("improving", "호전"), ("worsening", "악화"), ("unchanged", "변화 없음")]:
        uri = str(OW) + "RecordedCourse" + word.title()
        builder.concept(uri, "AttributeValue", word, korean=korean, source_refs=["policy:D40:course_collection"])
        builder.vocabulary.add((OW.Course, OW.canHaveValue, URIRef(uri)))
    for target, attribute in builder.vocabulary.subject_objects(OW.hasAttribute):
        name = str(attribute).removeprefix(str(OW))
        if name in QUALITY_QUESTIONS:
            questions.setdefault(str(target) + "|" + str(attribute), {"text": QUALITY_QUESTIONS[name],
                "answer_type": "category", "affirmative": False})
    for cid, name, source_id, label, korean, unit, unit_id, text in [
            ("444000005", "BodyHeight", "1153637007", "Body height", "신장", "cm", "258672001", "현재 키가 몇 센티미터인가요?"),
            ("262285001", "BodyWeight", "27113001", "Body weight", "체중", "kg", "258683005", "현재 몸무게가 몇 킬로그램인가요?")]:
        target, attribute = target_uri(cid), str(OW[name])
        if target not in builder.registry:
            continue
        if not terminology.active(source_id) or not terminology.active(unit_id):
            raise ValueError("Reported measurement requires active observable and unit source identifiers")
        builder.concept(attribute, "FindingAttribute", label, korean=korean,
            source_refs=["rf2:concept:" + source_id, "rf2:concept:" + unit_id, "prepared:D42:reported_measurement"])
        authored.aliases(builder, attribute, {"ko": ["키" if name == "BodyHeight" else "몸무게"]}, "prepared:D42:reported_measurement")
        builder.vocabulary.add((URIRef(target), OW.hasAttribute, URIRef(attribute)))
        questions[target + "|" + attribute] = {"text": text, "answer_type": "quantity", "units": [unit]}
        retained.add((target, attribute))
    return retained


def build(output, *, source_path=DEFAULT_SOURCE, parent_path=DEFAULT_PARENT, inputs=DEFAULT_INPUTS, authored_path=None):
    output, inputs = workspace_path(output), workspace_path(inputs)
    if not (output.is_relative_to(ROOT / "data/preparation/v5") or output.is_relative_to(ROOT / "Tmp")):
        raise ValueError("Rebuild output must remain in preparation or scratch")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty rebuild directory")
    manifest_path = ROOT / "submission/knowledge/manifest.json"
    baseline = json.loads(manifest_path.read_text())
    source, parent = SourceDatabase(source_path, readonly=True), SourceDatabase(parent_path, readonly=True)
    database = None
    try:
        if parent.meta("build_id") != baseline["build_id"]:
            raise ValueError("Use the preparation database of the currently admitted build as --parent-database")
        builder = parent.builder()
        builder.vocabulary = Graph().parse(ROOT / "submission" / baseline["vocabulary"]["path"], format="turtle")
        builder.graph = Graph()
        for asset in baseline["bundles"]:
            builder.graph.parse(ROOT / "submission" / asset["path"], format="turtle")
        questions = json.loads((ROOT / "submission" / baseline["questions"]["path"]).read_text())
        before = metrics(builder, questions)
        terminology = SnapshotSources(source)
        config = json.loads((inputs / "complaints.json").read_text())
        rows, targets, retained, audit = restore_roots(source, terminology, builder, questions, config)
        variant_dispositions = restore_variants(source, builder, rows, targets)
        add_source_terms(builder, terminology)
        retained_attributes = set(builder.vocabulary.subject_objects(OW.hasAttribute))
        retained_attributes.update(collect_attributes(builder, questions, config, terminology))
        extra_concepts, extra_attributes, ddx_report = ddxplus.project(DDXPLUS,
            json.loads((inputs / "ddxplus.json").read_text()), builder, questions)
        retained.update(extra_concepts)
        retained_attributes.update(extra_attributes)
        authored_path = workspace_path(authored_path or inputs / "authored.jsonl")
        extra_concepts, extra_attributes, author_report = authored.apply(builder, authored.read_entries(authored_path), questions,
            source_name=authored_path.relative_to(ROOT).as_posix(), terminology=terminology)
        retained.update(extra_concepts)
        retained_attributes.update(extra_attributes)
        policy_path = inputs / "scoring_policy.json"
        reasoning_path = ROOT / "submission" / baseline["reasoning_policy"]["path"]
        input_paths = sorted({*inputs.glob("*.json"), authored_path, DDXPLUS / "release_evidences.json",
                              DDXPLUS / "release_conditions.json", DDXPLUS / "LICENSE.txt"})
        identity = {"schema_version": "5.0", "schema": file_hash(ROOT / "data/ontology/schema.ttl"),
            "normalization_version": VERSION, "parent_build_id": baseline["build_id"],
            "parent_database": {"path": parent.path.relative_to(ROOT).as_posix(), "sha256": file_hash(parent.path)},
            "parent_manifest": digest(baseline), "scoring_policy": file_hash(policy_path),
            "scoring_policy_path": policy_path.relative_to(ROOT).as_posix(),
            "reasoning_policy_path": reasoning_path.relative_to(ROOT).as_posix(),
            "inputs": [*source.meta("identity")["inputs"], *[{"path": p.relative_to(ROOT).as_posix(), "sha256": file_hash(p)} for p in input_paths]],
            "generator_files": {p.name: file_hash(p) for p in (ROOT / "Dev/ontology").glob("*.py")}}
        build_id = digest(identity)
        report = {"build_id": build_id, "decision": "D42", "baseline": before,
            "bodhi_roots": len({row["root_snomed_id"] for _, _, row in rows if row["root_snomed_id"]}),
            "bodhi_blank_root_rows": sum(not row["root_snomed_id"] for _, _, row in rows),
            "root_statuses": dict(Counter(row["status"] for row in audit if row["bodhi_root"] and row["source_id"])),
            "variant_statuses": dict(Counter(row["status"] for row in variant_dispositions)),
            "ddxplus": {k: v for k, v in ddx_report.items() if k not in {"evidences", "conditions", "links"}},
            "authored_records": len(author_report), "model_calls": 0, "normalization_version": VERSION,
            "algorithm_version": baseline["algorithm_version"],
            "independent_clinical_validation": "not_run"}
        output.mkdir(parents=True, exist_ok=True)
        write(output / "baseline-manifest.json", baseline)
        write(output / "root-audit.json", audit)
        write(output / "variant-audit.json", variant_dispositions)
        write(output / "ddxplus.json", ddx_report)
        write(output / "authored-provenance.json", author_report)
        write(output / "questions.ko.json", questions)
        exam_requests = {str(method): str(text) for method, text in builder.vocabulary.subject_objects(OW.examRequestText)}
        write(output / "exam-requests.ko.json", exam_requests)
        snapshots = [*baseline["source_snapshots"], {"dataset": "DDXPlus", "version": "English-v2", "license": "CC BY 4.0",
            "files": [{"path": p.relative_to(ROOT).as_posix(), "sha256": file_hash(p)} for p in input_paths if p.parent == DDXPLUS]},
            {"dataset": "D42-preparation", "version": VERSION, "files": [
                {"path": p.relative_to(ROOT).as_posix(), "sha256": file_hash(p)} for p in input_paths if p.parent != DDXPLUS]}]
        result = builder.export(output / "preview", source_snapshots=snapshots, report=report, dispositions=[],
            require_action_assets=True, retain_concepts=retained, retain_attributes=retained_attributes,
            scoring_policy_path=policy_path, reasoning_policy_path=reasoning_path)
        after = metrics(builder, questions)
        if after["classes"]["Disease"] != before["classes"]["Disease"]:
            raise ValueError("The common complaint batch must preserve the admitted disease catalog")
        result.update(current=after)
        database = SourceDatabase(output / "ontology.sqlite3")
        database.set_meta("source_custody", {"path": source.path.relative_to(ROOT).as_posix(), "build_id": source.meta("build_id")})
        database.set_meta("identity", identity)
        database.set_meta("build_id", build_id)
        database.set_meta("composition", source.meta("composition"))
        database.set_meta("retain_concepts", sorted(retained))
        database.set_meta("retain_attributes", sorted((str(t), str(a)) for t, a in retained_attributes))
        database.set_meta("source_snapshots", snapshots)
        database.set_meta("report", result)
        database.save_builder(builder)
        for disposition in [*audit, *variant_dispositions]:
            database.disposition({**disposition, "decision": disposition["status"]})
        database.set_meta("stage", "complete")
        review_material(database, output / "preview")
        receipt = json.loads((output / "preview/review-batch.json").read_text())
        receipt.update(approved=True, approver="user-approved-D42-plan", approved_at=datetime.now(timezone.utc).isoformat(),
            approval_basis="explicit_user_candidate_acceptance", accepted_rules=RULES,
            independent_clinical_validation="not_run", approved_associations=receipt["available_associations"],
            approved_registry=receipt["available_registry"])
        receipt["text_assets"] = {name: {"path": (output / filename).relative_to(ROOT).as_posix(), "sha256": file_hash(output / filename)}
            for name, filename in [("questions", "questions.ko.json"), ("exam_requests", "exam-requests.ko.json")]}
        if baseline.get("guidelines"):
            index = json.loads((ROOT / "submission" / baseline["guidelines"]["path"]).read_text())
            index.update(build_id=build_id, parent_build_id=baseline["build_id"])
            write(output / "guideline-index.json", index)
            receipt["text_assets"]["guidelines"] = {"path": (output / "guideline-index.json").relative_to(ROOT).as_posix(),
                                                      "sha256": file_hash(output / "guideline-index.json")}
        write(output / "review-approved.json", receipt)
        write(output / "report.json", result)
        database.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return result
    finally:
        source.close()
        parent.close()
        if database:
            database.close()
