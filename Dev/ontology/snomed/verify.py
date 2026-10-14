from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph, Namespace, URIRef

from .extractor import create_sessionless_client, extract, sdk_client, sdk_request
from .models import Evidence, ROOT, digest, read, write
from .project import export_preview, incompatible, merge_profiles, project, validate_projection
from .rf2 import ASSOCIATED_WITH, DUE_TO, IS_A, import_rf2, normalize, normalize_description, RF2
from .vocabulary import expand_vocabulary, freeze_vocabulary, validate_vocabulary

RELEASE = "20260501"
CORE = "900000000000207008"
MODEL_MODULE = "900000000000012004"
ENGLISH = "900000000000509007"
PREFERRED = "900000000000548007"
ACCEPTABLE = "900000000000549004"
FSN = "900000000000003001"
LOCATION = "363698007"
SEVERITY = "246112005"
COURSE = "263502005"
UNKNOWN_ATTRIBUTE = "999999001"
TYPE_CONCEPTS = {IS_A, DUE_TO, ASSOCIATED_WITH, LOCATION, SEVERITY, COURSE, UNKNOWN_ATTRIBUTE}


def write_rf2(directory):
    rows = {kind: [] for kind in ("Concept", "Description", "Relationship", "Language", "ModuleDependency", "ConcreteValues")}
    concepts = {
        "100": ("Chest pain", "finding"), "101": ("Abdominal pain", "finding"),
        "200": ("Crohn disease", "disorder"), "201": ("Abdominal pain due to Crohn disease", "finding"),
        "202": ("Severe abdominal pain due to Crohn disease", "finding"),
        "203": ("Mild left abdominal pain due to Crohn disease", "finding"),
        "204": ("Abdominal pain associated with Crohn disease", "finding"),
        "205": ("Abdominal pain in Crohn ileitis", "finding"),
        "214": ("Abdominal pain due to Crohn ileitis", "finding"),
        "206": ("Crohn ileitis", "disorder"), "207": ("Synthetic intermediate pain finding", "finding"),
        "208": ("Unlinked abdominal discomfort", "finding"), "209": ("Five minute abdominal pain due to Crohn disease", "finding"),
        "210": ("Unmapped relation abdominal pain due to Crohn disease", "finding"),
        "211": ("Obsolete concept", "finding"), "212": ("Shared label candidate one", "finding"),
        "213": ("Shared label candidate two", "finding"),
        "301": ("Right lower quadrant structure", "body structure"),
        "302": ("Severe", "qualifier value"), "303": ("Mild", "qualifier value"),
        "304": ("Left upper quadrant structure", "body structure"), "900": ("Synthetic unsupported attribute", "attribute"),
        "901": ("Synthetic International model module concept", "metadata"),
    }
    for type_id in TYPE_CONCEPTS:
        concepts.setdefault(type_id, ("Synthetic relationship type " + type_id, "attribute"))
    for cid, (label, tag) in concepts.items():
        if cid == "211":
            continue
        module = MODEL_MODULE if cid == "901" else CORE
        rows["Concept"].append({"id": cid, "effectiveTime": RELEASE, "active": "1", "moduleId": module,
                                "definitionStatusId": "900000000000074008"})
        fsn_id, term_id = "d" + cid + "f", "d" + cid + "s"
        rows["Description"].append({"id": fsn_id, "effectiveTime": RELEASE, "active": "1", "moduleId": CORE,
                                    "conceptId": cid, "languageCode": "en", "typeId": FSN,
                                    "term": f"{label} ({tag})", "caseSignificanceId": "900000000000448009"})
        rows["Description"].append({"id": term_id, "effectiveTime": RELEASE, "active": "1", "moduleId": CORE,
                                    "conceptId": cid, "languageCode": "en", "typeId": "900000000000013009",
                                    "term": "Shared synthetic label" if cid in {"212", "213"} else label,
                                    "caseSignificanceId": "900000000000448009"})
        rows["Language"].append({"id": "l" + cid + "f", "effectiveTime": RELEASE, "active": "1", "moduleId": CORE,
                                 "refsetId": ENGLISH, "referencedComponentId": fsn_id, "acceptabilityId": ACCEPTABLE})
        rows["Language"].append({"id": "l" + cid + "s", "effectiveTime": RELEASE, "active": "1", "moduleId": CORE,
                                 "refsetId": ENGLISH, "referencedComponentId": term_id, "acceptabilityId": PREFERRED})
    rows["Concept"].extend([
        {"id": "211", "effectiveTime": "20250131", "active": "1", "moduleId": CORE, "definitionStatusId": "900000000000074008"},
        {"id": "211", "effectiveTime": RELEASE, "active": "0", "moduleId": CORE, "definitionStatusId": "900000000000074008"},
    ])
    rels = []

    def rel(source, destination, type_id, group="0", number=None):
        rels.append({"id": "r" + str(number or (len(rels) + 1)), "effectiveTime": RELEASE, "active": "1", "moduleId": CORE,
                     "sourceId": source, "destinationId": destination, "relationshipGroup": group,
                     "typeId": type_id, "characteristicTypeId": "900000000000011006", "modifierId": "900000000000451002"})

    rel("201", "101", IS_A, number=1); rel("201", "200", DUE_TO, number=2); rel("201", "301", LOCATION, "2", 3)
    rel("202", "101", IS_A, number=4); rel("202", "200", DUE_TO, "0", 5); rel("202", "301", LOCATION, "2", 6); rel("202", "302", SEVERITY, "3", 7)
    rel("203", "101", IS_A, number=8); rel("203", "200", DUE_TO, number=9); rel("203", "304", LOCATION, "4", 10); rel("203", "303", SEVERITY, "5", 11)
    rel("204", "101", IS_A, number=12); rel("204", "200", ASSOCIATED_WITH, number=13)
    rel("205", "207", IS_A, number=14); rel("205", "206", IS_A, number=15); rel("206", "200", IS_A, number=16); rel("207", "101", IS_A, number=17)
    rel("214", "101", IS_A, number=25); rel("214", "206", DUE_TO, number=26)
    rel("208", "101", IS_A, number=18)
    rel("209", "101", IS_A, number=19); rel("209", "200", DUE_TO, number=20); rel("209", "301", LOCATION, number=21)
    rel("210", "101", IS_A, number=22); rel("210", "200", DUE_TO, number=23); rel("210", "900", UNKNOWN_ATTRIBUTE, number=24)
    rows["Relationship"].extend(rels)
    rows["ConcreteValues"].append({"id": "c209", "effectiveTime": RELEASE, "active": "1", "moduleId": CORE,
                                   "sourceId": "209", "value": "#5", "relationshipGroup": "0", "typeId": SEVERITY,
                                   "characteristicTypeId": "900000000000011006", "modifierId": "900000000000451002"})
    rows["ModuleDependency"].extend([
        {"id": "m1", "effectiveTime": RELEASE, "active": "1", "moduleId": CORE,
         "refsetId": "900000000000534007", "referencedComponentId": MODEL_MODULE,
         "sourceEffectiveTime": RELEASE, "targetEffectiveTime": "20250131"},
        {"id": "m2", "effectiveTime": RELEASE, "active": "1", "moduleId": MODEL_MODULE,
         "refsetId": "900000000000534007", "referencedComponentId": CORE,
         "sourceEffectiveTime": RELEASE, "targetEffectiveTime": RELEASE},
    ])
    headers = {
        "Concept": ("id", "effectiveTime", "active", "moduleId", "definitionStatusId"),
        "Description": ("id", "effectiveTime", "active", "moduleId", "conceptId", "languageCode", "typeId", "term", "caseSignificanceId"),
        "Relationship": ("id", "effectiveTime", "active", "moduleId", "sourceId", "destinationId", "relationshipGroup", "typeId", "characteristicTypeId", "modifierId"),
        "Language": ("id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "acceptabilityId"),
        "ModuleDependency": ("id", "effectiveTime", "active", "moduleId", "refsetId", "referencedComponentId", "sourceEffectiveTime", "targetEffectiveTime"),
        "ConcreteValues": ("id", "effectiveTime", "active", "moduleId", "sourceId", "value", "relationshipGroup", "typeId", "characteristicTypeId", "modifierId"),
    }
    filenames = {"Concept": "sct2_Concept_Snapshot", "Description": "sct2_Description_Snapshot-en",
                 "Relationship": "sct2_Relationship_Snapshot", "Language": "der2_cRefset_LanguageSnapshot-en",
                 "ModuleDependency": "der2_ssRefset_ModuleDependencySnapshot",
                 "ConcreteValues": "sct2_ConcreteValues_Snapshot"}
    for kind, records in rows.items():
        folder = directory / "Snapshot" / kind
        folder.mkdir(parents=True, exist_ok=True)
        filename = folder / f"{filenames[kind]}_{RELEASE}.txt"
        with filename.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers[kind], delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
    return rows


def span(rf2, sctid):
    row = rf2.descriptions(sctid)[0]
    return {"kind": "description", "id": row["id"], "quote": row["term"], "start": 0, "end": len(row["term"])}


def relationship_evidence(row):
    return {"kind": "relationship", "id": row["id"]}


def qualifier(rf2, source, value_id, attribute):
    relationship = next(r for r in rf2.relationships(source) if r["destinationId"] == value_id)
    return {"attribute": attribute, "value_id": value_id, "evidence": [relationship_evidence(relationship)]}


def mk_vocabulary_response(rf2, expansion):
    decisions = []
    for packet in expansion["packets"]:
        cid = packet["candidates"][0]["sctid"]
        evidence = [span(rf2, cid)]
        expected_kind = ("Symptom" if cid in {"201", "202", "203", "204", "205", "207", "208", "209", "210", "100"}
                        else "Disease" if cid == "206" else "AttributeValue" if cid in {"301", "302", "303", "304"}
                        else None)
        if expected_kind is not None and expected_kind not in packet["allowed_kinds"]:
            decisions.append({"packet_id": packet["packet_id"], "decision": "exclude", "sctid": cid,
                              "evidence": evidence, "reason": "Synthetic lexical collision has an incompatible object kind"})
            continue
        if cid in {"201", "202", "203", "204", "205", "207", "208", "209", "210"}:
            if cid in {"201", "202", "203", "204", "205", "209", "210"}:
                qualifications = []
                for relation in rf2.relationships(cid):
                    attribute = {LOCATION: "Location", SEVERITY: "Severity"}.get(relation["typeId"])
                    if attribute:
                        qualifications.append({"attribute": attribute, "value_id": relation["destinationId"],
                                               "evidence": [relationship_evidence(relation)]})
                decisions.append({"packet_id": packet["packet_id"], "decision": "decompose", "sctid": cid,
                                  "kind": "Symptom", "target_id": "101", "qualifications": qualifications,
                                  "evidence": evidence, "reason": "Synthetic finding is a subtype of the reviewed base target"})
            else:
                decisions.append({"packet_id": packet["packet_id"], "decision": "exclude", "sctid": cid,
                                  "evidence": evidence, "reason": "Synthetic exclusion fixture"})
        elif cid == "206":
            decisions.append({"packet_id": packet["packet_id"], "decision": "map", "sctid": cid, "kind": "Disease",
                              "evidence": evidence, "reason": "Synthetic disease subtype mapping"})
        elif cid == "100" and "Symptom" in packet["allowed_kinds"]:
            decisions.append({"packet_id": packet["packet_id"], "decision": "map", "sctid": cid, "kind": "Symptom",
                              "attributes": ["Location", "Severity"], "evidence": evidence,
                              "reason": "Synthetic seed mapping for the chest pain target"})
        elif cid == "100":
            decisions.append({"packet_id": packet["packet_id"], "decision": "exclude", "sctid": cid,
                              "evidence": evidence, "reason": "Synthetic lexical collision is not the requested value"})
        elif cid in {"301", "304"}:
            decisions.append({"packet_id": packet["packet_id"], "decision": "map", "sctid": cid,
                              "kind": "AttributeValue", "value_attributes": ["Location"],
                              "evidence": evidence, "reason": "Synthetic categorical location value mapping"})
        elif cid in {"302", "303"}:
            decisions.append({"packet_id": packet["packet_id"], "decision": "map", "sctid": cid,
                              "kind": "AttributeValue", "value_attributes": ["Severity"],
                              "evidence": evidence, "reason": "Synthetic categorical severity value mapping"})
        elif cid == "213":
            decisions.append({"packet_id": packet["packet_id"], "decision": "exclude", "sctid": cid,
                              "evidence": evidence, "reason": "Synthetic unsupported concept"})
        else:
            decisions.append({"packet_id": packet["packet_id"], "decision": "exclude", "sctid": cid,
                              "evidence": evidence, "reason": "Synthetic fixture term outside the intended vocabulary scope"})
    return {"decisions": decisions}


def assert_raises(fn, phrase):
    try:
        fn()
    except Exception as exc:
        if phrase not in str(exc):
            raise AssertionError(f"Expected {phrase!r}; received {exc!r}") from exc
        return
    raise AssertionError(f"Expected failure containing {phrase!r}")


def run():
    scratch = ROOT / "Tmp/snomed"
    scratch.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="verify-", dir=scratch))
    try:
        def cli(*args):
            completed = subprocess.run([sys.executable, "-m", "Dev.ontology.snomed", *map(str, args)],
                                       cwd=ROOT, capture_output=True, text=True, check=True)
            return json.loads(completed.stdout)

        rf2_dir = work / "rf2"
        rf2_dir.mkdir()
        write_rf2(rf2_dir)
        database = work / "rf2.sqlite"
        imported = import_rf2(rf2_dir, database, RELEASE, [ENGLISH])
        cli_database = work / "cli" / "rf2.sqlite"
        cli_import = cli("import", "--rf2", rf2_dir, "--release-date", RELEASE,
                         "--language-refset", ENGLISH, "--database", cli_database)
        assert cli_import["dataset_id"] == imported["dataset_id"]
        rf2 = RF2(database)
        try:
            assert rf2.dataset_id == imported["dataset_id"]
            assert rf2.metadata["dependencies"][0][3] == "20250131"
            assert rf2.active("211") is False
            assert rf2.search("shared synthetic label") == ["212", "213"]
            assert rf2.search("Abdominal pain") == ["101"]
            assert normalize("pain (right)") != normalize("pain")
            assert normalize_description(rf2.descriptions("101")[0]) == normalize("Abdominal pain")
            assert len(rf2.path("205", "101")) == 2 and len(rf2.path("205", "200")) == 2
            assert rf2.concrete("209")[0]["value"] == "#5"

            expansion = expand_vocabulary(rf2)
            cli_candidates = work / "cli" / "vocabulary-candidates.json"
            cli("expand-vocabulary", "--database", cli_database, "--output", cli_candidates)
            assert read(cli_candidates) == expansion
            cli_dry = work / "cli" / "vocabulary-dry-run"
            cli_extract = cli("extract", "--database", cli_database, "--stage", "vocabulary",
                              "--input", cli_candidates, "--output-dir", cli_dry)
            assert cli_extract["calls_made"] == 0 and read(cli_dry / "dry-run.json")["calls_made"] == 0
            assert {"101", "200"} <= {item["sctid"] for item in expansion["entries"]}
            response = mk_vocabulary_response(rf2, expansion)
            cli_vocabulary_response = work / "cli" / "vocabulary-response.json"
            write(cli_vocabulary_response, response)
            cli_validated_vocabulary = work / "cli" / "vocabulary-validated.json"
            cli("validate", "--database", cli_database, "--stage", "vocabulary", "--input", cli_candidates,
                "--response", cli_vocabulary_response, "--output", cli_validated_vocabulary)
            validated_vocab = validate_vocabulary(rf2, expansion, response)
            assert read(cli_validated_vocabulary) == validated_vocab
            review = {"input_sha256": validated_vocab["sha256"], "reviewer": "synthetic offline verifier",
                      "accepted_sctids": sorted(item["sctid"] for item in validated_vocab["entries"]),
                      "excluded_sctids": [],
                      "accepted_decompositions": sorted(item["packet_id"] for item in validated_vocab["decompositions"])}
            registry = freeze_vocabulary(rf2, validated_vocab, review)
            cli_review = work / "cli" / "vocabulary-review.json"
            write(cli_review, review)
            cli_registry = work / "cli" / "registry.json"
            cli("freeze-vocabulary", "--database", cli_database, "--candidates", cli_validated_vocabulary,
                "--review", cli_review, "--output", cli_registry)
            assert read(cli_registry) == registry
            candidates = {item["sctid"] for item in registry["entries"]}
            assert {"101", "200", "206", "301", "302", "303", "304"} <= candidates
            assert "201" not in candidates and len(registry["decompositions"]) >= 5

            linkage = project(rf2, registry)
            cli_linkage = work / "cli" / "projection-packets.json"
            cli("project", "--database", cli_database, "--registry", cli_registry, "--output", cli_linkage)
            assert read(cli_linkage) == linkage
            cli_projection_dry = work / "cli" / "projection-dry-run"
            cli_projection_extract = cli("extract", "--database", cli_database, "--stage", "projection",
                                         "--input", cli_linkage, "--registry", cli_registry,
                                         "--output-dir", cli_projection_dry)
            assert cli_projection_extract["calls_made"] == 0
            assert linkage["packets"]
            packet_by_source = {}
            for packet in linkage["packets"]:
                packet_by_source.setdefault(packet["source"]["sctid"], []).append(packet)
            assert {"201", "202", "203", "204", "205", "209", "210", "214"} <= set(packet_by_source)
            assert "208" not in packet_by_source
            assert any(p["relation_basis"] == "due_to" for p in packet_by_source["201"])
            assert any(p["relation_basis"] == "associated_with" for p in packet_by_source["204"])
            assert {("200", "206", "descendant"), ("206", "206", "exact")} <= {
                (p["disease_id"], p["source_disease_id"], p["derivation_scope"]) for p in packet_by_source["214"]
            }
            assert all(p["derivation_scope"] == "descendant" for p in packet_by_source["205"])
            assert any(p["paths"] for p in packet_by_source["205"])
            projection_response = {"decisions": []}
            for packet in linkage["packets"]:
                source = packet["source"]["sctid"]
                if source == "209":
                    evidence = [{"kind": "concrete", "id": row["id"]} for row in packet["concrete_values"]]
                    projection_response["decisions"].append({"packet_id": packet["packet_id"], "decision": "exclude",
                                                              "unrepresentable": evidence,
                                                              "reason": "Concrete duration cannot be represented in categorical runtime RDF"})
                elif source == "210":
                    row = next(r for r in packet["source"]["relationships"] if r["typeId"] == UNKNOWN_ATTRIBUTE)
                    projection_response["decisions"].append({"packet_id": packet["packet_id"], "decision": "exclude",
                                                              "unrepresentable": [relationship_evidence(row)],
                                                              "reason": "Unknown defining relationship is not representable"})
                else:
                    distinct = source == "203"
                    projection_response["decisions"].append({"packet_id": packet["packet_id"], "decision": "accept",
                                                              "profile": "distinct" if distinct else "compatible",
                                                              "profile_evidence": [span(rf2, source)] if distinct else [],
                                                              "features": [], "reason": "Synthetic source-grounded profile"})
            validated_projection = validate_projection(rf2, registry, linkage, projection_response)
            cli_projection_response = work / "cli" / "projection-response.json"
            write(cli_projection_response, projection_response)
            cli_validated_projection = work / "cli" / "projection-validated.json"
            cli("validate", "--database", cli_database, "--stage", "projection", "--input", cli_linkage,
                "--registry", cli_registry, "--response", cli_projection_response,
                "--output", cli_validated_projection)
            assert read(cli_validated_projection) == json.loads(json.dumps(validated_projection))
            profiles = validated_projection["profiles"]
            profile_201 = next(item for item in profiles if item["source_concept_id"] == "201")
            assert profile_201["characteristic"] is True
            assert profile_201["relation_basis"] == "due_to"
            profile_204 = next(item for item in profiles if item["source_concept_id"] == "204")
            assert profile_204["characteristic"] is False
            profile_202 = next(item for item in profiles if item["source_concept_id"] == "202")
            source_groups = set(tuple(value) for value in profile_202["source_groups"])
            assert ("202", "2") in source_groups and ("202", "3") in source_groups
            assert not any(source != "202" for source, _ in source_groups)
            assert len(validated_projection["excluded"]) == 2

            shuffled = {**validated_projection, "profiles": list(reversed(profiles))}
            assert [(item["uri"], [tuple((feature["attribute"], feature["value_id"]) for feature in item["features"])])
                    for item in merge_profiles(shuffled["profiles"])] == [
                        (item["uri"], [tuple((feature["attribute"], feature["value_id"]) for feature in item["features"])])
                        for item in merge_profiles(profiles)]
            merged = merge_profiles(profiles)
            assert incompatible({"features": [{"attribute": "Location", "value_id": "301"}]},
                               {"features": [{"attribute": "Location", "value_id": "304"}]})
            assert not incompatible({"features": [{"attribute": "Location", "value_id": "301"}]},
                                    {"features": [{"attribute": "Location", "value_id": "301"}]})
            assert len({item["uri"] for item in merged}) == len(merged)
            assert sum("Variant" in item["uri"] for item in merged) == 3, [
                (item["uri"], item["disease_id"], item["target_id"], [source["source_concept_id"] for source in item["sources"]])
                for item in merged]
            due_pattern = next(item for item in merged if item["disease_id"] == "200" and item["characteristic"]
                               and any(source["source_concept_id"] == "201" for source in item["sources"]))
            location_feature = next(item for item in due_pattern["features"] if item["attribute"] == "Location")
            assert len(location_feature["evidence"]) == 2
            assert all("clinical_role" not in feature for item in merged for feature in item["features"])

            broken = json.loads(json.dumps(projection_response))
            target_packet = next(packet for packet in linkage["packets"] if packet["source"]["sctid"] == "201")
            bad_decision = next(item for item in broken["decisions"] if item["packet_id"] == target_packet["packet_id"])
            bad_decision["features"] = [{"attribute": "Location", "value_id": "301", "evidence": [
                {"kind": "relationship", "id": "missing-relationship"}]}]
            assert_raises(lambda: validate_projection(rf2, registry, linkage, broken), "Evidence is absent")
            omitted = json.loads(json.dumps(projection_response))
            source_packet = next(packet for packet in linkage["packets"] if packet["source"]["sctid"] == "210")
            omitted_decision = next(item for item in omitted["decisions"] if item["packet_id"] == source_packet["packet_id"])
            omitted_decision.update({"decision": "accept", "unrepresentable": [], "reason": "Must not broaden"})
            assert_raises(lambda: validate_projection(rf2, registry, linkage, omitted), "Every source defining relationship")
            missing = {"decisions": projection_response["decisions"][:-1]}
            assert_raises(lambda: validate_projection(rf2, registry, linkage, missing), "every projection packet")

            preview = work / "preview"
            report = export_preview(rf2, registry, validated_projection, preview)
            cli_preview = work / "cli" / "preview"
            cli_preview_report = cli("export-preview", "--database", cli_database, "--registry", cli_registry,
                                     "--validated", cli_validated_projection, "--output-dir", cli_preview)
            assert cli_preview_report == report
            assert report["status"] == "preview_only" and report["patterns"] == 5 and report["variants"] == 3
            assert report["patterns_with_features"] == 2
            graph = Graph().parse(preview / "schema.ttl").parse(preview / "vocabulary.ttl").parse(preview / "clinical.ttl")
            sys.path.insert(0, str(ROOT / "submission"))
            from knowledge.graph import ClinicalKnowledge, OW
            knowledge = ClinicalKnowledge(graph)
            knowledge.validate_graph()
            disease_uri = next(item["uri"] for item in registry["entries"] if item["sctid"] == "200")
            target_uri = next(item["uri"] for item in registry["entries"] if item["sctid"] == "101")
            assert len(knowledge.get_patterns_by_target(target_uri)) == 5
            disease_patterns = knowledge.get_disease_patterns(disease_uri)
            assert sum(item["characteristic"] for item in disease_patterns) == 2
            assert all(not knowledge.get_pattern_features(item["id"]) or
                       all(feature["role"] is None for feature in knowledge.get_pattern_features(item["id"]))
                       for item in disease_patterns)

            from workflow.clinical_reasoner import ClinicalReasoner
            from workflow.state.models import ClinicalValue, RecordItem, SessionContext, WorkflowState
            session = SessionContext(session_id="synthetic-offline", deadline=datetime.now(timezone.utc) + timedelta(minutes=10), turns_remaining=50)
            state = WorkflowState(session=session)
            state.differential.initialized = True
            state.case.put("S.cc", RecordItem(id="complaint", scope="Initiation", status="done", source_refs=["source-1"],
                value=ClinicalValue(kind="symptom", text="abdominal pain", status="present", concept_ids=[target_uri],
                                    observation_id="episode-1", episode_id="episode-1")))
            location_uri = next(item["uri"] for item in registry["entries"] if item["sctid"] == "301")
            state.case.put("S.hpi", RecordItem(id="location", scope="ChiefComplaint", status="done", source_refs=["source-2"],
                value=ClinicalValue(kind="attribute", text="right lower quadrant", status="present", concept_ids=[target_uri],
                                    attribute_id=str(OW.Location), values=[location_uri], observation_id="episode-1", episode_id="episode-1")))
            ClinicalReasoner(knowledge).refresh_hypotheses(state)
            disease_score = next(item.evidence_score for item in state.differential.hypotheses if item.disease_id == disease_uri)
            assert disease_score == 3, f"Expected characteristic feature and one deduplicated presence score, got {disease_score}"

            vocab_bad_id = json.loads(json.dumps(response))
            bad_map = next(item for item in vocab_bad_id["decisions"] if item["sctid"] == "206")
            bad_map["sctid"] = "99999999"
            assert_raises(lambda: validate_vocabulary(rf2, expansion, vocab_bad_id), "must select an offered concept")
            vocab_bad_quote = json.loads(json.dumps(response))
            bad_value = next(item for item in vocab_bad_quote["decisions"] if item["sctid"] == "301")
            bad_value["evidence"][0].update({"quote": "wrong", "start": 0, "end": 5})
            assert_raises(lambda: validate_vocabulary(rf2, expansion, vocab_bad_quote), "exact character span")
            assert_raises(lambda: validate_vocabulary(rf2, expansion, {"decisions": response["decisions"][:-1]}),
                          "exactly one decision")

            dry_dir = work / "dry-run"
            dry_report = extract(rf2, "projection", linkage, dry_dir, live=False, registry=registry)
            assert dry_report["calls_made"] == 0 and read(dry_dir / "dry-run.json")["calls_made"] == 0
            client_options = {}
            class FakeClient:
                def __init__(self, **kwargs):
                    client_options.update(kwargs)
                    self.session_id = ""
                def chat(self, messages, **kwargs):
                    self.messages, self.options = messages, kwargs
                    return {"choices": [{"message": {"content": "{}"}}]}
            fake_client = create_sessionless_client(FakeClient, "test-token", "https://nova.example")
            assert client_options == {"token": "test-token", "api_base": "https://nova.example", "sample": False}
            sdk_request(fake_client, [{"role": "user", "content": "{}"}], "request-id")
            assert fake_client.options == {"model": "openai/gpt-6.1-sol", "reasoning_effort": "medium",
                                           "max_tokens": 4000, "request_id": "request-id"}
            class SessionClient(FakeClient):
                def __init__(self, **kwargs):
                    super().__init__(**kwargs)
                    self.session_id = "unexpected-session"
            assert_raises(lambda: create_sessionless_client(SessionClient, "test-token", "https://nova.example"),
                          "unexpectedly has a session")
            with patch.dict(os.environ, {"NOVA_DEV_KEY": "synthetic-only", "NOVA_API_BASE": "https://nova.example"}, clear=True):
                pinned_sdk_client = sdk_client()
                assert not pinned_sdk_client.session_id
            cache_dir, ledger_path = work / "live-first", work / "call-ledger.sqlite"
            call_log = []
            response_by_packet = {item["packet_id"]: item for item in projection_response["decisions"]}
            def fake_call(messages, request_id):
                batch_input = json.loads(messages[1]["content"])
                call_log.append((request_id, messages, batch_input))
                packet_ids = {packet["packet_id"] for packet in batch_input["packets"]}
                content = {"decisions": [item for key, item in response_by_packet.items() if key in packet_ids]}
                return {"choices": [{"message": {"content": json.dumps(content)}}], "usage": {"total_tokens": 12}}
            live_report = extract(rf2, "projection", linkage, cache_dir, live=True, max_calls=10,
                                  daily_remaining=10, ledger_path=ledger_path, registry=registry, call=fake_call)
            assert live_report["calls_made"] == 2 and len(call_log) == 2
            assert all(len(call[2]["packets"]) <= 5 for call in call_log)
            assert len({call[0] for call in call_log}) == 2
            request_records = [read(path) for path in sorted((cache_dir / "requests").glob("*.json"))]
            assert {record["request_id"] for record in request_records} == {call[0] for call in call_log}
            cached_report = extract(rf2, "projection", linkage, work / "live-cached", live=True, max_calls=10,
                                    daily_remaining=10, ledger_path=ledger_path, registry=registry, call=fake_call)
            assert cached_report["calls_made"] == 0 and len(call_log) == 2
            assert read(work / "live-cached" / "response.json") == read(cache_dir / "response.json")
            assert_raises(lambda: extract(rf2, "projection", linkage, work / "blocked-quota", live=True,
                                          max_calls=1, daily_remaining=1, ledger_path=work / "quota-ledger.sqlite",
                                          registry=registry, call=fake_call), "allowance exhausted")
            assert len(call_log) == 3

            class MockApiError(Exception):
                def __init__(self, code):
                    super().__init__(code)
                    self.code = code
            for code, status in (("QUOTA_EXCEEDED", "api_error"), ("TIMEOUT", "unknown")):
                failures = []
                def failing_call(messages, request_id, code=code):
                    failures.append(request_id)
                    raise MockApiError(code)
                ledger = work / f"{status}-ledger.sqlite"
                assert_raises(lambda: extract(rf2, "projection", linkage, work / f"{status}-first", live=True,
                                              max_calls=1, daily_remaining=1, ledger_path=ledger,
                                              registry=registry, call=failing_call), "will not be retried")
                assert len(failures) == 1
                assert_raises(lambda: extract(rf2, "projection", linkage, work / f"{status}-again", live=True,
                                              max_calls=1, daily_remaining=1, ledger_path=ledger,
                                              registry=registry, call=failing_call), f"Existing call is {status}")
                assert len(failures) == 1

            malformed_calls = []
            def malformed_call(messages, request_id):
                malformed_calls.append(request_id)
                return {"choices": [{"message": {"content": "not valid json"}}]}
            malformed_ledger = work / "malformed-ledger.sqlite"
            assert_raises(lambda: extract(rf2, "projection", linkage, work / "malformed-first", live=True,
                                          max_calls=1, daily_remaining=1, ledger_path=malformed_ledger,
                                          registry=registry, call=malformed_call), "not valid JSON")
            raw_files = list((work / "malformed-first" / "responses").glob("*.json"))
            assert len(raw_files) == 1 and read(raw_files[0])["content"] == "not valid json"
            assert_raises(lambda: extract(rf2, "projection", linkage, work / "malformed-again", live=True,
                                          max_calls=1, daily_remaining=1, ledger_path=malformed_ledger,
                                          registry=registry, call=malformed_call), "not valid JSON")
            assert len(malformed_calls) == 1

            alternate = expand_vocabulary(rf2, seeds={"Disease": [], "Symptom": ["Shared synthetic label"]})
            assert len(alternate["packets"]) == 1 and len(alternate["packets"][0]["candidates"]) == 2
            assert not alternate["entries"]
            verification = {"status": "pass", "release": "synthetic_only", "dataset_id": rf2.dataset_id,
                "cli": {"full_synthetic_pipeline": "pass", "dry_run_default": "pass"},
                "rf2": {"latest_inactive": "pass", "duplicate_label_ambiguity": "pass", "semantic_tag_search_preserves_parentheses": "pass",
                        "older_dependency_target_version": "pass",
                        "multilevel_hierarchy": "pass", "concrete_value_preserved": "pass"},
                "vocabulary": {"seed_match": "pass", "new_candidates": "pass", "decomposition": "pass",
                               "registry_freeze": "pass", "bad_sctid_rejected": "pass", "bad_quote_rejected": "pass",
                               "missing_decision_rejected": "pass"},
                "projection": {"due_to": "pass", "associated_with": "pass", "subtype_intersection": "pass",
                               "unlinked_pair_absent": "pass", "defining_relation_omission_rejected": "pass",
                               "feature_evidence_rejected": "pass", "group_scope": "pass", "profile_variant": "pass",
                               "permutation_stability": "pass", "source_deduplication": "pass", "location_conflict_variant": "pass",
                               "characteristic_scope": "pass"},
                "preview": {"patterns": report["patterns"], "variants": report["variants"],
                            "feature_patterns": report["patterns_with_features"], "graph_validation": "pass",
                            "reverse_target_lookup": "pass", "score_deduplication": "pass"},
                "extractor": {"dry_run_calls": 0, "live_mock_calls": live_report["calls_made"],
                              "batch_limit": 5, "cache_replay_calls": cached_report["calls_made"],
                              "sessionless_sdk_contract": "pass", "session_id_rejected": "pass",
                              "pinned_sdk_mount": "pass", "request_ids_persisted": "pass",
                              "quota_error_no_retry": "pass", "unknown_completion_no_retry": "pass",
                              "malformed_json_saved_no_retry": "pass", "daily_cap_blocks_extra_batch": "pass",
                              "live_network_calls": "not_run"}}
        finally:
            rf2.close()
        report_path = ROOT / "Tmp/snomed/verification.json"
        write(report_path, verification)
        return verification
    finally:
        shutil.rmtree(work)
    return {"status": "incomplete"}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
