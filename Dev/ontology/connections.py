from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import re

from rdflib import Literal, RDF, URIRef

from .database import DispositionRecords, SourceDatabase, file_hash
from .v5 import OW, ROOT, digest, workspace_path, write

POLICY = {
    "version": "D20-competition-connections-1",
    "inSystem": "RF2 finding site or complete Pattern Location value -> named organ-system is-a ancestry; interview grouping only",
    "contextType": "BODHI source role and explicit English wording -> existing history categories; source identity kept separate from SCTID identity",
    "hasSupportingContext": "Directed positive nonzero BODHI influence -> confirmed-present Context support, capped at +1 per disease",
    "prerequisite": "Directed positive nonzero BODHI prerequisites -> joint Association applicability, never an unconditional bonus",
    "examination": "Only source-associated targets with explicit physical detection methods; preserve one acquisition role per SCTID",
    "unresolved": "Missing meaning, units, linked findings or acquisition remain technical exclusions, not pending user approval",
}


def context_type(row):
    label = row["name"].casefold()
    if row["concept_type"] == "FamilyHistory" or re.match(r"^(f/?h\b|family history)", label):
        return "family_history"
    if "allerg" in label or row["concept_type"] == "Allergy":
        return "allergy_history"
    if re.search(r"vaccin|screening", label):
        return "screening_history"
    if re.search(r"drug|treatment|therapy|analgesic|decongestant|antidepressant|contraceptive|amiodarone", label):
        return "medication_history"
    if row["concept_type"] == "Procedure":
        return "surgical_history"
    if re.search(r"driver|occupation|work|lifting heavy|prolonged (standing|sitting|kneeling)", label):
        return "occupational_history"
    if re.search(r"stress|bereavement", label):
        return "psychosocial_history"
    if re.search(r"pregnan|menopaus|menarche|parous|parity|childbirth|lactation|breast feeding", label):
        return "demographic"
    if row["concept_type"] == "Lifestyle" or row["type_condition"] == "lifestyle":
        return "social_history" if row["concept_type"] != "Disorder" else "past_medical_history"
    if row["concept_type"] == "Disorder" or re.match(r"^h/o\b", label):
        return "past_medical_history"
    return "social_history"


def project(database, terminology, builder):
    from .source_projection import INFERRED

    proofs = defaultdict(set)
    dispositions = []
    conditions = {row["snomed_id"]: (rid, row) for rid, _, row in database.bodhi_rows("nodes_condition.csv")}
    diseases = {entry["snomed_id"]: uri for uri, entry in builder.registry.items() if entry["kind"] == "Disease"}
    prerequisites = defaultdict(dict)
    contexts = {}

    def context(cid):
        if cid in contexts:
            return contexts[cid]
        rid, row = conditions[cid]
        uri = str(OW) + "BodhiContext" + cid
        kind = context_type(row)
        builder.concept(uri, "ContextFactor", row["name"], source_refs=[f"source_row:{rid}:name"])
        builder.registry[uri].update(context_type=kind, source_role="BODHI_context_role",
            referenced_snomed_id=cid, mapping_status="source_identity_not_equated_to_sctid",
            source_condition_type=row["type_condition"], source_concept_type=row["concept_type"])
        triple = (URIRef(uri), OW.contextType, Literal(kind))
        builder.vocabulary.add(triple)
        proofs[triple].add(f"source_row:{rid}:concept_type:type_condition:name")
        contexts[cid] = uri
        return uri

    for filename, role in (("edges_is_influenced_by.csv", "support"), ("edges_has_prerequisite.csv", "prerequisite")):
        for rid, line, row in database.bodhi_rows(filename):
            source, target = row["condition_snomed_id_src"], row["condition_snomed_id_dst"]
            reason = None
            if source not in diseases or target not in conditions:
                reason = "endpoint_outside_selected_diseases_or_source_contexts"
            elif source == target:
                reason = "self_context_not_independent_support"
            elif row["relation_polarity"] != "positive":
                reason = "negative_polarity_not_positive_support"
            elif row["relation_strength"] not in {"rare", "low", "medium", "high", "very_high"}:
                reason = "zero_or_unknown_source_strength"
            if reason:
                dispositions.append({"source_row_id": rid, "file": filename, "line": line, "reason": reason})
                continue
            uri = context(target)
            if role == "support":
                triple = (URIRef(diseases[source]), OW.hasSupportingContext, URIRef(uri))
                builder.vocabulary.add(triple)
                proofs[triple].add(f"source_row:{rid}:positive_nonzero_influence")
            else:
                prerequisites[diseases[source]][uri] = f"source_row:{rid}:positive_prerequisite"

    replaced = 0
    for node in list(builder.graph.subjects(RDF.type, OW.DiseasePatternAssociation)):
        disease = str(next(builder.graph.subjects(OW.hasAssociation, node)))
        if disease not in prerequisites:
            continue
        pattern = str(builder.graph.value(node, OW.pattern))
        conditions_payload = {json.dumps(item, sort_keys=True): item for item in
            json.loads(str(builder.graph.value(node, OW.applicability) or "[]"))}
        for uri in prerequisites[disease]:
            item = {"concept_id": uri, "status": "present", "subject": "family" if
                builder.registry[uri]["context_type"] == "family_history" else "patient", "time_context": "unspecified"}
            conditions_payload[json.dumps(item, sort_keys=True)] = item
        assertions = builder.assertions.pop(str(node))
        builder.selected.pop(str(node), None)
        builder.graph.remove((None, OW.hasAssociation, node))
        builder.graph.remove((node, None, None))
        for assertion in assertions:
            raw = {"original": assertion["raw"], "prerequisite_source_refs": sorted(prerequisites[disease].values()),
                   "derivation_rule": POLICY["prerequisite"]}
            key = builder.association(disease, pattern, **{name: assertion[name] for name in
                ("source_ref", "relation_basis", "derivation_scope", "predictiveness", "typicality", "strong_predictor")},
                applicability=list(conditions_payload.values()), raw=raw)
            for ref in prerequisites[disease].values():
                builder.graph.add((URIRef(key), OW.sourceRef, Literal(ref)))
        replaced += 1

    systems = {cid for cid in terminology.children.get("91689009", ()) if "system" in
        terminology.fsns.get(cid, "").casefold() and not any(word in terminology.fsns.get(cid, "").casefold()
            for word in ("entire body system", "subdivision"))}
    sites = defaultdict(list)
    for row in database.connection.execute("""SELECT id,source_id,destination_id FROM rf2_components
            WHERE kind='relationship' AND active='1' AND characteristic=? AND type_id='363698007' ORDER BY id""", (INFERRED,)):
        sites[row["source_id"]].append((row["destination_id"], ["rf2:" + row["id"]]))
    for pattern, target in builder.graph.subject_objects(OW.targets):
        for feature in builder.graph.objects(pattern, OW.hasFeature):
            if builder.graph.value(feature, OW.onAttribute) != OW.Location:
                continue
            payload = json.loads(str(builder.graph.value(builder.graph.value(feature, OW.expected), OW.valueJSON)))
            for value in ([payload["concept"]] if payload.get("concept") else payload.get("concepts", [])):
                entry = builder.registry.get(value, {})
                if entry.get("snomed_id"):
                    sites[builder.registry[str(target)]["snomed_id"]].append((entry["snomed_id"], entry["source_refs"]))
    for uri, entry in list(builder.registry.items()):
        if entry["kind"] not in {"Symptom", "ExamFinding"}:
            continue
        for site, refs in sites.get(entry.get("snomed_id"), []):
            paths = terminology.ancestor_paths(site)
            for cid in sorted(systems & paths.keys()):
                system = str(OW) + "BodySystemSnomedCT" + cid
                path_refs = refs + ["rf2:" + rid for rid in paths[cid]]
                path_refs += ["rf2:" + rid for parent, rid in terminology.parents[cid] if parent == "91689009"]
                builder.concept(system, "BodySystem", terminology.fsns[cid].rsplit(" (", 1)[0],
                    snomed_id=cid, source_refs=path_refs)
                triple = (URIRef(uri), OW.inSystem, URIRef(system))
                builder.vocabulary.add(triple)
                proofs[triple].update(path_refs)
    return proofs, {"policy": POLICY, "contexts": len(contexts), "context_types": dict(Counter(
        entry["context_type"] for entry in builder.registry.values() if entry["kind"] == "ContextFactor")),
        "prerequisite_diseases": len(prerequisites), "conditioned_associations": replaced,
        "excluded_context_edges": dispositions}


def build(database_path, output, *, accept_competition=False):
    from .admission import RULES, candidate_set, review_material
    from .findings import project as project_findings
    from .source_projection import SnapshotSources

    database_path, output = workspace_path(database_path), workspace_path(output)
    if not (output.is_relative_to(ROOT / "data/preparation/v5") or output.is_relative_to(ROOT / "Tmp")):
        raise ValueError("Connection output must remain in project preparation or scratch")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty connection build directory")
    source = SourceDatabase(database_path, readonly=True)
    try:
        if source.meta("stage") != "complete":
            raise ValueError("Connections require a complete source build")
        identity = {**source.meta("identity"), "parent_build_id": source.meta("build_id"), "connection_policy": POLICY,
            "generator_files": {p.name: file_hash(p) for p in sorted((ROOT / "Dev/ontology").glob("*.py"))}}
        builder = source.builder()
        terminology = SnapshotSources(source)
        findings, _, _ = project_findings(source, terminology, builder)
        reported = {entry.get("snomed_id") for entry in builder.registry.values() if entry["kind"] == "Symptom"}
        promoted, excluded = set(), Counter()
        for node in findings.graph.subjects(RDF.type, OW.ClinicalPattern):
            target = findings.graph.value(node, OW.targets)
            entry = findings.registry[str(target)]
            reason = "same_sctid_patient_report_already_scored" if entry.get("snomed_id") in reported else \
                "physical_method_missing" if not list(findings.vocabulary.objects(target, OW.detectedBy)) else None
            if reason:
                excluded[reason] += 1
            else:
                promoted.add(str(target))
        selected = {str(node) for node in findings.graph.subjects(RDF.type, OW.DiseasePatternAssociation)
                    if str(findings.graph.value(findings.graph.value(node, OW.pattern), OW.targets)) in promoted}
        for node in list(findings.graph.subjects(RDF.type, OW.DiseasePatternAssociation)):
            if str(node) not in selected:
                findings.graph.remove((None, OW.hasAssociation, node))
                findings.graph.remove((node, None, None))
        builder.graph += findings.graph
        builder.vocabulary += findings.vocabulary
        for uri, entry in findings.registry.items():
            if uri not in builder.registry:
                builder.registry[uri] = entry
        builder.assertions.update({key: value for key, value in findings.assertions.items() if key in selected})
        builder.selected.update({key: value for key, value in findings.selected.items() if key in selected})
        proofs, report = project(source, terminology, builder)
        report.update(build_id=digest(identity), parent_build_id=source.meta("build_id"), promoted_exam_targets=sorted(promoted),
            exam_pattern_exclusions=dict(excluded), real_model_calls=0, korean_generation="not_run")
        output.mkdir(parents=True, exist_ok=True)
        db = SourceDatabase(output / "ontology.sqlite3")
        try:
            for key in ("composition", "target_roles"):
                db.set_meta(key, source.meta(key))
            db.set_meta("identity", identity)
            db.set_meta("build_id", digest(identity))
            db.set_meta("source_custody", source.meta("source_custody") or {
                "path": database_path.relative_to(ROOT).as_posix(), "build_id": source.meta("build_id")})
            db.set_meta("admission_scope", "graph")
            db.close()
            db = SourceDatabase(output / "ontology.sqlite3")
            db.save_builder(builder)
            result = builder.export(output / "preview", source_snapshots=source.source_snapshots(), report=report,
                dispositions=DispositionRecords(db), require_action_assets=False)
            db.save_builder(builder)
            db.set_meta("report", result)
            db.set_meta("stage", "complete")
            report["relations"] = {name: len(list(builder.vocabulary.triples((None, OW[name], None)))) for name in
                                   ("hasSupportingContext", "contextType", "inSystem", "detectedBy", "evaluatedBy")}
            symptoms = set(builder.vocabulary.subjects(RDF.type, OW.Symptom))
            report["symptom_system_coverage"] = {"total": len(symptoms), "mapped": sum(
                bool(list(builder.vocabulary.objects(node, OW.inSystem))) for node in symptoms)}
            report["runtime_classes"] = dict(Counter(str(kind).removeprefix(str(OW)) for _, kind in
                builder.vocabulary.subject_objects(RDF.type)))
            records = [{"subject": str(s), "predicate": str(p), "object": o.n3(), "source_refs": sorted(refs)}
                       for (s, p, o), refs in sorted(proofs.items(), key=lambda pair: tuple(map(str, pair[0])))
                       if (s, p, o) in builder.vocabulary]
            write(output / "connection-evidence.json", records)
            write(output / "connections.json", report)
            write(output / "required-text-assets.json", {"build_id": db.meta("build_id"),
                "status": "generation_not_run", "requires_new_workset_and_budget": True,
                "entries": [entry for entry in builder.registry.values() if entry["kind"] in
                            {"Symptom", "ContextFactor", "FindingAttribute", "ExamMethod"}]})
            review_material(db, output / "preview")
            receipt = {"build_id": db.meta("build_id"), "candidate_set_sha256": digest(candidate_set(db)),
                "approved": True, "approver": "user", "approved_at": datetime.now(timezone.utc).isoformat(),
                "approval_basis": "explicit_user_candidate_acceptance", "admission_scope": "graph",
                "authorization": "2026-10-16 user requested competition-MVP graph connections and approval of pending source expressions; Korean generation excluded",
                "approved_associations": [r[0] for r in db.connection.execute("SELECT id FROM associations ORDER BY id")],
                "approved_registry": sorted(builder.registry), "accepted_rules": RULES, "reviewed_rules": [],
                "accepted_connection_policy": POLICY, "independent_clinical_validation": "not_run",
                "text_assets": {}}
            if accept_competition:
                write(output / "review-approved.json", receipt)
            db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()
        return report
    finally:
        source.close()
