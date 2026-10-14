from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path

from rdflib import Graph, RDF, RDFS, URIRef

from .v5 import NORMALIZATION_VERSION, OW, PreviewBuilder, ROOT, digest, workspace_path
from submission.knowledge.conditions import ScoringPolicy

IS_A = "116680003"
DUE_TO = "42752001"
ASSOCIATED_WITH = "47429007"
INFERRED = "900000000000011006"
FSN = "900000000000003001"
PREFERRED = "900000000000548007"
ATTRIBUTE_MAP = {"363698007": "Location", "246112005": "Severity", "263502005": "Course", "272741003": "Laterality"}

TARGETS = {"21522001": "AbdominalPain", "49727002": "Cough", "386661006": "Fever"}
AXES = {"location": "Location", "laterality": "Laterality", "radiating": "RadiationLocation",
        "onset": "Onset", "duration_since": "TimeSinceOnset", "duration_lasts": "EpisodeDuration",
        "temporal_pattern": "TemporalPattern", "severity": "Severity", "pain_type": "PainQuality",
        "aggravated": "AggravatingFactor", "relieved": "RelievingFactor"}


def rows(path, *, rf2=False):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t" if rf2 else ",", quoting=csv.QUOTE_NONE if rf2 else csv.QUOTE_MINIMAL)
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed source row: {path.name}:{line}")
            yield line, row


class SnapshotSources:
    def __init__(self, releases):
        self.releases = []
        self.files = []
        self.concepts = {}
        self.parents = defaultdict(list)
        versions, dependencies = {}, []
        for directory in releases:
            directory = workspace_path(directory)
            metadata = json.loads((directory / "release_package_information.json").read_text(encoding="utf-8"))
            date = metadata["effectiveTime"]
            if not re.fullmatch(r"\d{8}", date):
                raise ValueError("Release metadata must declare an effective date")
            dependency_files = list((directory / "Snapshot/Refset/Metadata").glob("*ModuleDependencySnapshot*.txt"))
            if len(dependency_files) != 1:
                raise ValueError("Release requires one module dependency snapshot")
            active = [row for _, row in rows(dependency_files[0], rf2=True) if row["active"] == "1"]
            if not active:
                raise ValueError("Release requires active module dependency records")
            own_modules = {r["moduleId"] for r in active}
            for row in active:
                version = row["sourceEffectiveTime"]
                if version > date or (row["moduleId"] in versions and versions[row["moduleId"]] != version):
                    raise ValueError("Conflicting module version")
                versions[row["moduleId"]] = version
                dependencies.append(row)
            self.releases.append({"directory": directory, "date": date, "modules": own_modules,
                                  "dependency_file": dependency_files[0]})
        # The self-contained foundation module has no outgoing dependency row.
        versions.setdefault("900000000000012004", self.releases[0]["date"])
        for row in dependencies:
            if versions.get(row["referencedComponentId"]) != row["targetEffectiveTime"]:
                raise ValueError("Module dependency does not match the supplied base release")
        self.module_versions, self.dependencies = versions, dependencies
        for release in self.releases:
            path = self.one_file(release, "sct2_Concept_Snapshot_*.txt")
            self.pin(path, release)
            for _, row in rows(path, rf2=True):
                self.validate_row(row, release)
                value = (row["active"], row["moduleId"], row["effectiveTime"], row["definitionStatusId"])
                previous = self.concepts.get(row["id"])
                if previous and previous[2] == value[2] and previous != value:
                    raise ValueError("Conflicting same-version concept snapshots")
                if previous is None or value[2] > previous[2]:
                    self.concepts[row["id"]] = value
        taxonomy = {}
        for release in self.releases:
            path = self.one_file(release, "sct2_Relationship_Snapshot_*.txt")
            self.pin(path, release)
            for _, row in rows(path, rf2=True):
                self.validate_row(row, release)
                if row["typeId"] == IS_A:
                    self.merge_row(taxonomy, row)
        for row in taxonomy.values():
            if (row["active"] == "1" and row["characteristicTypeId"] == INFERRED
                    and self.active(row["sourceId"]) and self.active(row["destinationId"])):
                self.parents[row["sourceId"]].append((row["destinationId"], row["id"]))
        self.children = defaultdict(list)
        for child, parents in self.parents.items():
            for parent, _ in parents:
                self.children[parent].append(child)
        self.diseases = self.descendants({"64572001"})

    @staticmethod
    def one_file(release, pattern):
        files = list((release["directory"] / "Snapshot/Terminology").glob(pattern))
        if len(files) != 1:
            raise ValueError(f"Require one Snapshot file: {pattern}")
        return files[0]

    def pin(self, path, release):
        relative = path.relative_to(ROOT).as_posix()
        if any(f["path"] == relative for f in self.files):
            return
        with path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        self.files.append({"path": relative, "sha256": sha, "release_date": release["date"]})

    def validate_row(self, row, release):
        if (row["active"] not in {"0", "1"} or row["moduleId"] not in self.module_versions
                or not re.fullmatch(r"\d{8}", row["effectiveTime"])
                or row["effectiveTime"] > self.module_versions[row["moduleId"]]
                or row["effectiveTime"] > release["date"]):
            raise ValueError("RF2 row differs from the pinned module versions")

    def active(self, cid):
        return cid in self.concepts and self.concepts[cid][0] == "1"

    @staticmethod
    def merge_row(selected, row):
        previous = selected.get(row["id"])
        if previous and previous["effectiveTime"] == row["effectiveTime"]:
            fields = set(row) - {"file", "line"}
            if any(previous.get(field) != row[field] for field in fields):
                raise ValueError("Conflicting same-version RF2 component")
        if previous is None or row["effectiveTime"] > previous["effectiveTime"]:
            selected[row["id"]] = row

    def descendants(self, seeds):
        found, stack = set(seeds), list(seeds)
        while stack:
            for child in self.children.get(stack.pop(), []):
                if child not in found and self.active(child):
                    found.add(child)
                    stack.append(child)
        return found

    def path(self, cid, target):
        queue, seen = deque([(cid, [])]), set()
        while queue:
            node, path = queue.popleft()
            if node == target:
                return path
            if node not in seen:
                seen.add(node)
                queue.extend((parent, [*path, relation]) for parent, relation in self.parents.get(node, []))
        return None

    def relationships(self, wanted):
        latest = {}
        for release in self.releases:
            path = self.one_file(release, "sct2_Relationship_Snapshot_*.txt")
            for line, row in rows(path, rf2=True):
                if row["sourceId"] in wanted:
                    self.merge_row(latest, {**row, "file": path.relative_to(ROOT).as_posix(), "line": line})
            concrete = list((release["directory"] / "Snapshot/Terminology").glob("sct2_RelationshipConcreteValues_Snapshot_*.txt"))
            for path in concrete:
                self.pin(path, release)
                for line, row in rows(path, rf2=True):
                    if row["sourceId"] in wanted:
                        self.validate_row(row, release)
                        self.merge_row(latest, {**row, "file": path.relative_to(ROOT).as_posix(), "line": line})
        selected = defaultdict(list)
        for row in sorted(latest.values(), key=lambda row: row["id"]):
            if row["active"] == "1" and row["characteristicTypeId"] == INFERRED:
                selected[row["sourceId"]].append(row)
        return selected

    def descriptions(self, wanted):
        candidates, preferred, latest = defaultdict(list), {}, {}
        for release in self.releases:
            for path in sorted((release["directory"] / "Snapshot/Terminology").glob("sct2_Description_Snapshot-*.txt")):
                self.pin(path, release)
                for line, row in rows(path, rf2=True):
                    if row["conceptId"] in wanted:
                        self.validate_row(row, release)
                        self.merge_row(latest, {**row, "file": path.relative_to(ROOT).as_posix(), "line": line})
            self.pin(release["dependency_file"], release)
            self.pin(release["directory"] / "release_package_information.json", release)
        for row in latest.values():
            if row["active"] == "1":
                candidates[row["conceptId"]].append(row)
        needed = {r["id"] for members in candidates.values() for r in members}
        language_rows = {}
        for release in self.releases:
            for path in sorted((release["directory"] / "Snapshot/Refset/Language").glob("*LanguageSnapshot*.txt")):
                self.pin(path, release)
                for _, row in rows(path, rf2=True):
                    if row["referencedComponentId"] in needed:
                        self.validate_row(row, release)
                        self.merge_row(language_rows, row)
        for row in language_rows.values():
            if row["active"] == "1" and row["acceptabilityId"] == PREFERRED:
                priority = {"21000267104": 0, "900000000000509007": 0, "900000000000508004": 1}.get(row["refsetId"], 2)
                preferred[row["referencedComponentId"]] = min(priority, preferred.get(row["referencedComponentId"], priority))
        output = {}
        for cid, members in candidates.items():
            selected = {}
            for language in ("en", "ko"):
                options = [r for r in members if r["languageCode"] == language]
                options.sort(key=lambda r: (preferred.get(r["id"], 3), r["typeId"] != FSN, r["term"], r["id"]))
                if options:
                    selected[language] = re.sub(r"\s*\([^()]+\)$", "", options[0]["term"]) if options[0]["typeId"] == FSN else options[0]["term"]
            fsns = [r["term"] for r in members if r["typeId"] == FSN and r["languageCode"] == "en"]
            output[cid] = {"labels": selected, "fsn": fsns[0] if fsns else None, "descriptions": members}
        return output

    def manifest(self):
        return {"dataset": "SNOMED_CT", "module_versions": self.module_versions, "dependencies": self.dependencies,
                "files": sorted(self.files, key=lambda f: f["path"]), "dataset_id": digest(self.files)}


def temporal_value(raw):
    text = raw.strip().casefold()
    units = {"second": "s", "sec": "s", "s": "s", "minute": "min", "min": "min", "hour": "h", "h": "h",
             "day": "day", "week": "week", "month": "month", "year": "year"}
    unit_pattern = r"(seconds?|secs?|s|minutes?|mins?|hours?|h|days?|weeks?|months?|years?)"
    interval = re.fullmatch(r"(\d+(?:\.\d+)?)\s*" + unit_pattern + r"\s+to\s+(\d+(?:\.\d+)?)\s*" + unit_pattern, text)
    if interval:
        lower, a, upper, b = interval.groups()
        a, b = units[a.rstrip("s") if a != "s" else a], units[b.rstrip("s") if b != "s" else b]
        return {"kind": "interval", "lower": float(lower), "upper": float(upper), "unit": a, "upper_unit": b}
    point = re.fullmatch(r"(?:(less than|more than)\s+)?(\d+(?:\.\d+)?)\s*" + unit_pattern, text)
    if point:
        comparator, value, unit = point.groups()
        return {"kind": "quantity", "value": float(value), "unit": units[unit.rstrip("s") if unit != "s" else unit],
                "operator": {None: "eq", "less than": "lt", "more than": "gt"}[comparator]}
    raise ValueError("temporal_expression_unresolved")


class Normalizer:
    def __init__(self, builder):
        self.builder = builder
        self.existing = defaultdict(set)
        graph = Graph().parse(ROOT / "data/ontology/vocabulary.ttl")
        for subject, label in graph.subject_objects(RDFS.label):
            if (subject, RDF.type, OW.AttributeValue) in graph:
                self.existing[str(label).casefold()].add(str(subject))

    def value(self, attribute, text, *, cid=None):
        candidates = self.existing.get(text.casefold(), set())
        uri = next(iter(candidates)) if len(candidates) == 1 else str(OW) + "AttributeValue" + digest([attribute, text.casefold()])[:24]
        self.builder.concept(uri, "AttributeValue", text, snomed_id=cid)
        return uri

    def categorical(self, attribute, text, *, cid=None):
        pieces = text.split(" or ")
        values = [self.value(attribute, piece.strip(), cid=cid if len(pieces) == 1 else None) for piece in pieces]
        expected = {"kind": "concept", "concept": values[0]} if len(values) == 1 else {
            "kind": "concept_set", "concepts": values, "selection": "any_of"}
        return {"attribute": str(OW[attribute]), "expected": expected}

    def qualifier(self, target, axis, raw):
        text = re.sub(r"\s+", " ", raw).strip().casefold()
        if axis == "characteristic":
            if target == "49727002":
                mapping = {"dry cough": ("Quality", "dry"), "productive cough": ("Quality", "productive"),
                           "yellow sputum": ("SputumColour", "yellow"), "green sputum": ("SputumColour", "green"),
                           "clear sputum": ("SputumColour", "clear"), "blood stained": ("SputumContent", "blood stained"),
                           "bark like sound": ("CoughSound", "bark like")}
                if text in mapping:
                    return self.categorical(*mapping[text])
            raise ValueError("linked_finding_deferred" if any(k in text for k in ("chill", "rigor", "nausea", "tender")) else "characteristic_meaning_unresolved")
        if axis not in AXES:
            raise ValueError("axis_unresolved")
        attribute = AXES[axis]
        if axis in {"duration_since", "duration_lasts"}:
            return {"attribute": str(OW[attribute]), "expected": temporal_value(text)}
        if axis == "severity" and text not in {"mild", "moderate", "severe"}:
            raise ValueError("severity_conditions_or_units_unresolved")
        if axis == "temporal_pattern" and re.search(r"\d", text):
            raise ValueError("frequency_window_unresolved")
        if axis == "laterality" and text not in {"left", "right", "left side", "right side", "bilateral", "unilateral", "both", "both sides", "alternating"}:
            raise ValueError("laterality_location_scope_unresolved")
        return self.categorical(attribute, text)


def project_sources(international, korean, bodhi, output):
    terminology = SnapshotSources([international, *([korean] if korean else [])])
    if not all(terminology.active(cid) for cid in TARGETS):
        raise ValueError("The three bounded targets must exist in the pinned release")
    bodhi = workspace_path(bodhi)
    files, source = [], {}
    for name in ("nodes_condition.csv", "nodes_symptom.csv", "edges_present_in.csv"):
        path = bodhi / name
        records = list(rows(path))
        with path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        files.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha, "rows": len(records)})
        source[name] = records
    bodhi_id = digest(files)
    conditions = {r["snomed_id"]: (line, r) for line, r in source["nodes_condition.csv"]}
    symptoms = {r["uuid"]: (line, r) for line, r in source["nodes_symptom.csv"]}
    if len(conditions) != len(source["nodes_condition.csv"]) or len(symptoms) != len(source["nodes_symptom.csv"]):
        raise ValueError("Duplicate source node identifiers")
    selected = {cid for cid, (_, row) in symptoms.items() if row["root_snomed_id"] in TARGETS}
    descendants = terminology.descendants(set(TARGETS))
    relations = terminology.relationships(descendants)
    needed = set(conditions) | set(TARGETS) | descendants | {
        r["destinationId"] for members in relations.values() for r in members if "destinationId" in r}
    descriptions = terminology.descriptions(needed)
    builder = PreviewBuilder()
    normalizer = Normalizer(builder)
    policy = ScoringPolicy.load_default()
    dispositions, patterns, disease_uris = [], {}, {}
    target_uris = {cid: str(OW[name]) for cid, name in TARGETS.items()}
    for cid, uri in target_uris.items():
        labels = descriptions[cid]["labels"]
        builder.concept(uri, "Symptom", labels["en"], korean=labels.get("ko"), snomed_id=cid,
                        source_refs=["rf2:concept:" + cid])
    for cid, (line, row) in conditions.items():
        reason = None
        if not terminology.active(cid):
            reason = "inactive_snomed_identifier" if cid in terminology.concepts else "identifier_not_in_supplied_releases"
        elif (cid not in terminology.diseases or row["concept_type"] != "Disorder"
              or row["type_condition"] == "medical_history" or re.match(r"^(h/o|fh)\b", row["name"], re.I)):
            reason = "context_or_non_disease_entity"
        if reason:
            dispositions.append({"dataset": "bodhi-s", "source_file": "nodes_condition.csv", "line": line,
                                 "source_id": cid, "decision": "excluded", "reason": reason, "raw": row})
            continue
        labels = descriptions.get(cid, {}).get("labels", {})
        if "en" not in labels:
            dispositions.append({"source_id": cid, "decision": "unresolved", "reason": "english_description_missing", "raw": row})
            continue
        uri = str(OW) + "SnomedCT" + cid
        builder.concept(uri, "Disease", labels["en"], korean=labels.get("ko"), snomed_id=cid,
                        aliases=[row["name"]], source_refs=["rf2:concept:" + cid])
        disease_uris[cid] = uri
    for uuid in sorted(selected):
        line, row = symptoms[uuid]
        features, reason = [], None
        for axis in range(1, 4):
            key, value = row[f"relation{axis}_type"], row[f"child{axis}_name"]
            if bool(key) != bool(value):
                reason = "incomplete_qualifier"
                break
            if key:
                try:
                    features.append(normalizer.qualifier(row["root_snomed_id"], key, value))
                except ValueError as error:
                    reason = str(error)
                    break
        if reason is None:
            try:
                patterns[uuid] = builder.pattern(target_uris[row["root_snomed_id"]], features)
            except ValueError as error:
                reason = str(error)
        dispositions.append({"dataset": "bodhi-s", "source_file": "nodes_symptom.csv", "line": line, "source_id": uuid,
                             "decision": "unresolved" if reason else "accepted_preview", "reason": reason, "raw": row,
                             "pattern_id": patterns.get(uuid), "verified_root_sctid": row["root_snomed_id"]})
    conflicts = []
    for line, row in source["edges_present_in.csv"]:
        uuid, cid = row["symptom_uuid"], row["condition_snomed_id"]
        if uuid not in symptoms or cid not in conditions:
            raise ValueError("Dangling BODHI edge")
        if uuid not in selected:
            continue
        if uuid not in patterns or cid not in disease_uris:
            dispositions.append({"source_file": "edges_present_in.csv", "line": line, "decision": "excluded",
                                 "reason": "dependent_variant_or_disease_unresolved", "raw": row})
            continue
        prediction, typicality = row["likelihood_condition_given_symptom"].casefold(), row["likelihood_symptom_given_condition"].casefold()
        if prediction not in policy.labels or typicality not in policy.labels or row["strong_predictor"] not in {"", "0", "1"}:
            dispositions.append({"source_file": "edges_present_in.csv", "line": line, "decision": "unresolved", "reason": "source_label_unresolved", "raw": row})
            continue
        ref = f"bodhi-s:{bodhi_id}:edges_present_in.csv:{line}"
        association = builder.association(disease_uris[cid], patterns[uuid], source_ref=ref, relation_basis="bodhi_present_in",
            predictiveness=prediction, typicality=typicality, strong_predictor=None if row["strong_predictor"] == "" else row["strong_predictor"] == "1",
            raw={"edge": row, "symptom_uuid": uuid, "symptom_row": symptoms[uuid][1], "condition_row": conditions[cid][1]})
        dispositions.append({"source_file": "edges_present_in.csv", "line": line, "decision": "accepted_preview", "association_id": association, "raw": row})
        if row["strong_predictor"] == "1" and prediction in {"zero", "rare", "low"}:
            conflicts.append({"source_ref": ref, "reason": "strong_predictor_likelihood_conflict", "raw": row})
    snomed_packets = []
    for cid, members in sorted(relations.items()):
        targets = [(tid, terminology.path(cid, tid)) for tid in TARGETS]
        targets = [(tid, path) for tid, path in targets if path is not None]
        links = [(r["destinationId"], "due_to" if r["typeId"] == DUE_TO else "associated_with", r)
                 for r in members if r["typeId"] in {DUE_TO, ASSOCIATED_WITH} and r["destinationId"] in terminology.diseases]
        if cid in terminology.diseases:
            links.extend((did, "subtype_intersection", None) for did in disease_uris if did != cid and terminology.path(cid, did) is not None)
        for target, target_path in targets:
            for did, basis, link in links:
                features, reasons = [], []
                qualified = [r for r in members if r["typeId"] not in {IS_A, DUE_TO, ASSOCIATED_WITH}]
                groups = {r["relationshipGroup"] for r in qualified if r["relationshipGroup"] != "0"}
                if len(groups) > 1:
                    reasons.append("relationship_group_scope_unresolved")
                for row in qualified:
                    attribute = ATTRIBUTE_MAP.get(row["typeId"])
                    value = row.get("destinationId")
                    label = descriptions.get(value, {}).get("labels", {}).get("en")
                    if attribute is None or not value or not terminology.active(value) or not label:
                        reasons.append("required_rf2_condition_unresolved")
                    else:
                        features.append(normalizer.categorical(attribute, label, cid=value))
                packet = {"source_concept_id": cid, "disease_id": did, "target_id": target, "relation_basis": basis,
                          "target_path": target_path, "relationship": link, "qualifiers": qualified,
                          "descriptions": descriptions.get(cid, {}), "decision": "unresolved" if reasons else "accepted_preview",
                          "reasons": sorted(set(reasons))}
                snomed_packets.append(packet)
                if reasons:
                    continue
                if did not in disease_uris:
                    labels = descriptions.get(did, {}).get("labels", {})
                    if not terminology.active(did) or "en" not in labels:
                        packet.update(decision="unresolved", reasons=["disease_mapping_unresolved"])
                        continue
                    disease_uris[did] = str(OW) + "SnomedCT" + did
                    builder.concept(disease_uris[did], "Disease", labels["en"], korean=labels.get("ko"), snomed_id=did,
                                    source_refs=["rf2:concept:" + did])
                pattern = builder.pattern(target_uris[target], features)
                packet["pattern_id"] = pattern
                packet["association_id"] = builder.association(disease_uris[did], pattern,
                    source_ref="rf2:" + (link["id"] if link else digest([cid, did, target_path])), relation_basis=basis,
                    derivation_scope="descendant" if basis == "subtype_intersection" else "exact", raw=packet.copy())
    dispositions.extend({"dataset": "SNOMED_CT", **packet} for packet in snomed_packets)
    for entry in builder.registry.values():
        cid = entry["snomed_id"]
        if cid in terminology.concepts:
            active, module, date, definition = terminology.concepts[cid]
            entry["snomed_record"] = {"id": cid, "active": active, "moduleId": module,
                                      "effectiveTime": date, "definitionStatusId": definition}
            entry["descriptions"] = descriptions.get(cid, {})
            entry["mapping_status"] = "identifier_verified_semantic_review_pending"
    report = {"targets": TARGETS, "source_counts": {f["path"].split("/")[-1]: f["rows"] for f in files},
              "bodhi_selected_variants": len(selected), "bodhi_projected_variants": len(patterns),
              "bodhi_variant_dispositions": dict(Counter(d["reason"] or "accepted_preview" for d in dispositions if d.get("source_file") == "nodes_symptom.csv")),
              "snomed_packets": len(snomed_packets), "snomed_dispositions": dict(Counter(p["decision"] for p in snomed_packets)),
              "exceptions": conflicts, "normalization_version": NORMALIZATION_VERSION}
    report["condition_dispositions"] = dict(Counter(d["reason"] for d in dispositions if d.get("source_file") == "nodes_condition.csv"))
    return builder.export(output, source_snapshots=[terminology.manifest(), {"dataset": "bodhi-s", "dataset_id": bodhi_id, "files": files}],
                          report=report, dispositions=dispositions)

def main(argv=None):
    parser = argparse.ArgumentParser(prog="ontoward-source-projection")
    parser.add_argument("--international", type=Path, required=True)
    parser.add_argument("--korean", type=Path)
    parser.add_argument("--bodhi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = project_sources(args.international, args.korean, args.bodhi, args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
