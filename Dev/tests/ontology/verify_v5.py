import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

from rdflib import Graph, RDF

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "submission"))

from knowledge.conditions import ScoringPolicy
from knowledge.graph import ClinicalKnowledge, OW
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.state.models import ClinicalValue, RecordItem, SessionContext, WorkflowState


def verify(preview):
    preview = preview.resolve()
    if not preview.is_relative_to(ROOT / "data/preparation/v5"):
        raise ValueError("Verify a data-owned v5.0 preview")
    manifest = json.loads((preview / "manifest.json").read_text())
    sources = json.loads((preview / "sources.json").read_text())
    report = json.loads((preview / "report.json").read_text())
    registry = json.loads((preview / "registry.json").read_text())
    checks = []

    def require(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    require(manifest["schema_version"] == "5.0" and manifest["preparation_status"] == "preview_only"
            and report["model_calls"] == 0 and registry["review_status"] == "candidate", "preview_and_no_model_boundary")
    files = [file for snapshot in manifest["source_snapshots"] for file in snapshot["files"]]
    for record in files:
        path = (ROOT / record["path"]).resolve()
        require(path.is_relative_to(ROOT), "source_path_in_workspace:" + record["path"])
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        require(actual == record["sha256"], "unchanged_source_hash:" + record["path"])
    for asset in [manifest["schema"], manifest["vocabulary"], *manifest["bundles"], manifest["scoring_policy"]]:
        require(hashlib.sha256((preview / Path(asset["path"]).name).read_bytes()).hexdigest() == asset["sha256"],
                "preview_asset_hash:" + asset["path"])
    versions = manifest["source_snapshots"][0]["module_versions"]
    require(versions["11000267109"] == "20260615" and
            all(versions[module] == "20260501" for module in ("900000000000207008", "900000000000012004")),
            "international_korean_module_composition")
    policy = ScoringPolicy.model_validate_json((preview / "scoring_policy.json").read_text())
    graph = Graph()
    for name in ("schema.ttl", "vocabulary.ttl", "clinical.ttl"):
        graph.parse(preview / name, format="turtle")
    knowledge = ClinicalKnowledge(graph, policy=policy)
    knowledge.validate_graph()
    original_graph = set(graph)
    profiles = [knowledge._profile(a) for a in graph.subjects(RDF.type, OW.DiseasePatternAssociation)]
    require(len(profiles) == report["associations"], "loaded_association_count")
    shared = {}
    for profile in profiles:
        shared.setdefault(profile.id, []).append(profile)
    require(any(len({p.disease_id for p in group}) > 1 and len({p.score for p in group}) > 1
                for group in shared.values()), "shared_pattern_with_disease_specific_scores")

    dispositions = sources["dispositions"]
    excluded_ids = {d["source_id"] for d in dispositions if d.get("source_file") == "nodes_condition.csv"}
    admitted_ids = {entry["snomed_id"] for entry in registry["entries"] if entry["kind"] == "Disease"}
    require(not excluded_ids & admitted_ids and report["condition_dispositions"]["identifier_not_in_supplied_releases"] == 27,
            "invalid_and_non_disease_condition_dispositions")
    unresolved = {d["source_id"] for d in dispositions if d.get("source_file") == "nodes_symptom.csv"
                  and d["decision"] == "unresolved"}
    asserted = {a["raw"]["symptom_uuid"] for group in sources["assertions"].values() for a in group
                if a["relation_basis"] == "bodhi_present_in"}
    require(not unresolved & asserted and any(d.get("reason") == "linked_finding_deferred" for d in dispositions),
            "unresolved_and_linked_variants_never_asserted")
    require(any(d.get("dataset") == "SNOMED_CT" and d["decision"] == "unresolved" and d["qualifiers"]
                for d in dispositions), "required_rf2_conditions_preserved_when_unresolved")
    require(any(a["raw"]["symptom_row"]["snomed_id"] == "" for group in sources["assertions"].values() for a in group
                if a["relation_basis"] == "bodhi_present_in"), "uuid_and_nullable_sctid_preserved")
    require(any(entry.get("descriptions", {}).get("labels", {}).get("ko") for entry in registry["entries"]),
            "korean_names_retain_sctid_mapping")

    disease, target = str(OW.SnomedCT65275009), str(OW.AbdominalPain)
    candidates = [p for p in knowledge.get_disease_patterns(disease) if p.target == target]
    features = {p.association_id: knowledge.get_pattern_features(p.id) for p in candidates}
    baseline = next(p for p in candidates if all(f.expected is None for f in features[p.association_id]))
    locations = [p for p in candidates if all(not f.expected or f.attribute == str(OW.Location) for f in features[p.association_id])]
    upper = next(p for p in locations if p.score == 1 and len([f for f in features[p.association_id] if f.expected]) == 1)
    detailed = next(p for p in locations if p.score == 4 and knowledge.pattern_refines(p.id, upper.id))
    require((baseline.score, upper.score, detailed.score) == (2, 1, 4), "real_cholecystitis_source_labels")
    require(any(c.baseline_association == baseline.association_id and c.delta_score == -1 and c.kind == "atomic"
                for c in knowledge.get_feature_contributions(upper.association_id)) and
            any(c.baseline_association == upper.association_id and c.delta_score == 3 and c.kind == "atomic"
                for c in knowledge.get_feature_contributions(detailed.association_id)) and
            any(c.baseline_association == baseline.association_id and c.delta_score == 2 and c.kind == "joint"
                for c in knowledge.get_feature_contributions(detailed.association_id)), "real_conditional_atomic_and_joint_deltas")
    state = WorkflowState(session=SessionContext(session_id="synthetic-real-source-verification",
        deadline=datetime.now(timezone.utc) + timedelta(minutes=5), turns_remaining=50,
        current="DifferentialDiagnosis", initialized=True))

    def observe(ident, *, attribute=None, value=None, status="present", episode="episode-1"):
        state.case.put("S.hpi" if attribute else "S.cc", RecordItem(id=ident, scope="DifferentialDiagnosis", status="done",
            source_refs=["synthetic-observation:" + ident], value=ClinicalValue(kind="attribute" if attribute else "symptom",
            text=ident, status=status, concept_ids=[target], attribute_id=attribute, values=[value] if value else [],
            observation_id="abdominal-observation", episode_id=episode, time_context="current")))

    reasoner = ClinicalReasoner(knowledge)
    observe("abdominal-pain")
    reasoner.retrieve_candidates(state)
    score = lambda: next(h for h in state.differential.hypotheses if h.disease_id == disease).evidence_score
    sequence = [score()]
    upper_condition = next(f for f in features[upper.association_id] if f.expected)
    observe("upper-unknown", attribute=upper_condition.attribute, value=upper_condition.expected.concept, status="unknown")
    reasoner.refresh_hypotheses(state)
    require(score() == 2, "unknown_detail_does_not_activate_score")
    state.case.remove({"upper-unknown"})
    observe("upper-abdomen", attribute=upper_condition.attribute, value=upper_condition.expected.concept)
    reasoner.refresh_hypotheses(state)
    sequence.append(score())
    other = next(f for f in features[detailed.association_id] if f.expected and f.signature() != upper_condition.signature())
    observe("upper-right-quadrant", attribute=other.attribute, value=other.expected.concept)
    reasoner.refresh_hypotheses(state)
    sequence.append(score())
    require(sequence == [2, 1, 4], "real_graph_refinement_replaces_ancestor_2_1_4")
    observe("repeat-abdominal-pain", episode="episode-2")
    reasoner.refresh_hypotheses(state)
    require(score() == 4, "repeated_target_is_not_added")
    state.case.remove({"repeat-abdominal-pain"})
    state.case.get("upper-right-quadrant").value.episode_id = "episode-2"
    reasoner.refresh_hypotheses(state)
    require(score() == 1, "different_episode_cannot_complete_variant")
    require(set(graph) == original_graph, "scoring_leaves_graph_read_only")
    kinds = Counter(f.expected.kind for pattern in shared for f in knowledge.get_pattern_features(pattern) if f.expected)
    require(all(kinds[kind] for kind in ("concept", "concept_set", "quantity", "interval")), "all_four_value_types_in_real_preview")
    return {"status": "pass", "checks": checks, "check_count": len(checks), "source_files": len(files),
            "patterns": report["patterns"], "associations": len(profiles), "features": report["features"],
            "expected_value_kinds": dict(kinds), "cholecystitis_scores": sequence,
            "cholecystitis_associations": [baseline.association_id, upper.association_id, detailed.association_id],
            "condition_dispositions": report["condition_dispositions"], "network": "none", "model_calls": 0,
            "patient_observations": "synthetic", "clinical_review": "not_run", "runtime_admission": "not_run",
            "diagnostic_performance": "not_run", "authenticated_sdk": "not_run"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("preview", type=Path)
    args = parser.parse_args()
    result = verify(args.preview)
    output = args.preview / "verification.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, indent=2))


if __name__ == "__main__":
    main()
