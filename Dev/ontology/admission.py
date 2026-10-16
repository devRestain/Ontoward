from __future__ import annotations

from datetime import datetime
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from rdflib import Graph, Literal, RDF, URIRef

from .database import DispositionRecords, SourceDatabase, file_hash, json_text
from .v5 import OW, ROOT, digest, workspace_path, write

RULES = ["verified_source_identifiers_and_roles","complete_variant_conditions",
         "source_group_scope_preserved","directional_likelihoods_and_conflicts_reviewed",
         "model_normalizations_reviewed","no_unreviewed_exam_methods"]


def candidate_set(database):
    return {"build_id":database.meta("build_id"),
            "associations":[dict(r) for r in database.connection.execute("SELECT * FROM associations ORDER BY id")],
            "registry":[dict(r) for r in database.connection.execute("SELECT * FROM registry ORDER BY uri")],
            "triples_sha256":digest([tuple(r) for r in database.connection.execute("SELECT * FROM triples ORDER BY graph,subject,predicate,object")])}


def review_material(database,output):
    candidates = candidate_set(database)
    review = {"build_id":database.meta("build_id"),"candidate_set_sha256":digest(candidates),
              "approved":False,"approver":"","approved_at":None,"approved_associations":[],
              "approved_registry":[],"reviewed_rules":[],"required_rules":RULES,
              "exceptions":[],"available_associations":[r["id"] for r in candidates["associations"]],
              "available_registry":[r["uri"] for r in candidates["registry"]]}
    write(output/"review-batch.json",review)
    write(output/"target-roles.json",database.meta("target_roles",{}))
    labels = {r["uri"]:json.loads(r["payload"])["label"]
              for r in database.connection.execute("SELECT uri,payload FROM registry")}
    with (output/"disease-target-coverage.csv").open("w",encoding="utf-8",newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["disease_id","disease_label","target_id","target_label","associations"])
        for row in database.connection.execute("""SELECT a.disease,p.target,COUNT(*) FROM associations a
                JOIN patterns p ON p.id=a.pattern GROUP BY a.disease,p.target ORDER BY a.disease,p.target"""):
            writer.writerow([row[0],labels.get(row[0],row[0]),row[1],labels.get(row[1],row[1]),row[2]])
    report = database.meta("report",{})
    lines = ["# v5.0 전체 원천 배치 검토", "", f"- 빌드: `{review['build_id']}`",
             f"- 후보 집합 SHA-256: `{review['candidate_set_sha256']}`",
             f"- Association 후보: {len(review['available_associations']):,}",
             f"- Registry 항목: {len(review['available_registry']):,}", "",
             "이 파일과 review-batch.json은 승인 요청 자료다. approved=false이며 자동 승인하지 않는다.","",
             "검토 대상은 식별자와 임상 역할, 변형의 모든 조건, 관계 그룹, 두 방향 likelihood와 충돌, 모델 정규화 후보다.",
             "보류된 연결 소견·단위·역할·진찰 방법은 실행 자산에 포함하지 않는다.","",
             "## 원천별 처리", "", "| 입력 | 행 수 |", "|---|---:|"]
    for name,count in sorted(report.get("source_counts",{}).items()):
        lines.append(f"| {name} | {count:,} |")
    lines += ["", "## 증상 변형 처리", "", "| 결과 | 수 |", "|---|---:|"]
    for reason,count in sorted(report.get("bodhi_variant_dispositions",{}).items()):
        lines.append(f"| {reason} | {count:,} |")
    lines += ["", "상세 원천 행·정규화·판단은 ontology.sqlite3의 source_rows, normalizations, dispositions, source_assertions에서 확인한다.",
              "sources.json은 정본 SQLite 감사 테이블과 입력 해시를 가리키며, registry.json은 매핑과 명칭을, target-roles.json은 전체 발견 역할을 담는다.",
              "disease-target-coverage.csv는 질환과 Target별 연관 수를 제공한다. source_assertions와 normalizations에서 선택 평가·정규화 규칙·예외를 대조한다.",
              "승인 시 approved_associations와 approved_registry에 실제 승인한 항목을 지정하고 required_rules를 검토한다.",
              "임상 문진·진찰 요청·치료·교육 문구 작성과 실제 진단 성능 검증은 이 배치에 포함하지 않는다.",""]
    (output/"review.md").write_text("\n".join(lines),encoding="utf-8")


def validated_selection(database,receipt):
    if receipt.get("approved") is not True or not isinstance(receipt.get("approver"),str) or not receipt["approver"].strip():
        raise ValueError("Explicit human batch approval is required")
    date = receipt.get("approved_at")
    if not isinstance(date,str) or datetime.fromisoformat(date).tzinfo is None:
        raise ValueError("Approval requires a timestamp with timezone")
    if receipt.get("build_id")!=database.meta("build_id") or receipt.get("candidate_set_sha256")!=digest(candidate_set(database)):
        raise ValueError("Review receipt differs from pinned candidate set")
    accepted = receipt.get("accepted_rules",[]) if receipt.get("approval_basis")=="explicit_user_candidate_acceptance" else []
    if set(receipt.get("reviewed_rules",[])) | set(accepted) != set(RULES):
        raise ValueError("Every source and normalization rule requires review")
    approved = receipt.get("approved_associations",[])
    registry = receipt.get("approved_registry",[])
    if (not isinstance(approved,list) or not approved or len(set(approved))!=len(approved)
            or not isinstance(registry,list) or len(set(registry))!=len(registry)):
        raise ValueError("Approval must name distinct associations and registry entries")
    candidates = {r[0] for r in database.connection.execute("SELECT id FROM associations")}
    registered = {r[0] for r in database.connection.execute("SELECT uri FROM registry")}
    if not set(approved)<=candidates or not set(registry)<=registered:
        raise ValueError("Approval names unavailable or unresolved candidates")
    builder = database.builder()
    for node in list(builder.graph.subjects(RDF.type,OW.DiseasePatternAssociation)):
        if str(node) not in approved:
            builder.graph.remove((None,OW.hasAssociation,node))
            builder.graph.remove((node,None,None))
    for child,parent in list(builder.graph.subject_objects(OW.refinesPattern)):
        builder.graph.remove((child,OW.refinesPattern,parent))
    needed = set(builder.graph.subjects(OW.hasAssociation,None))
    patterns = set(builder.graph.objects(None,OW.pattern))
    for pattern in patterns:
        needed.add(builder.graph.value(pattern,OW.targets))
        for feature in builder.graph.objects(pattern,OW.hasFeature):
            attribute = builder.graph.value(feature,OW.onAttribute)
            expected = builder.graph.value(feature,OW.expected)
            if attribute:
                needed.add(attribute)
            if expected:
                payload = json.loads(str(builder.graph.value(expected,OW.valueJSON)))
                needed.update(URIRef(v) for v in ([payload["concept"]] if payload.get("concept") else payload.get("concepts",[])))
    for payload in builder.graph.objects(None, OW.applicability):
        needed.update(URIRef(item["concept_id"]) for item in json.loads(str(payload)))
    pending = list(needed)
    while pending:
        for predicate, value in builder.vocabulary.predicate_objects(pending.pop()):
            if predicate in {OW.hasSupportingContext, OW.inSystem, OW.detectedBy, OW.evaluatedBy} and value not in needed:
                needed.add(value)
                pending.append(value)
    # Attributes themselves are structural vocabulary, while every mapped value needs approval.
    mapped = {str(node) for node in needed if str(node) in registered}
    if not mapped<=set(registry):
        raise ValueError("Required concept or value mapping is not approved")
    return builder


def measure_prepare(submission, *, graph_only=False):
    code = """import json,resource,sys,time
sys.path.insert(0,sys.argv[1])
from workflow.runtime import prepare
started=time.perf_counter()
resources=prepare()
elapsed=time.perf_counter()-started
print(json.dumps({'prepare_seconds':elapsed,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'associations':len(resources.knowledge._profile_cache),'graph_triples':len(resources.knowledge._graph)}))
if elapsed>600 or resource.getrusage(resource.RUSAGE_SELF).ru_maxrss>8*1024*1024:
    raise RuntimeError('Runtime prepare exceeds the declared resource limit')
"""
    if graph_only:
        code = """import json,resource,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from rdflib import Graph
from knowledge.graph import ClinicalKnowledge
started=time.perf_counter()
root=Path(sys.argv[1])
manifest=json.loads((root/'knowledge/manifest.json').read_text())
graph=Graph()
for asset in [manifest['schema'],manifest['vocabulary'],*manifest['bundles']]:
    graph.parse(root/asset['path'],format='turtle')
knowledge=ClinicalKnowledge(graph)
knowledge.validate_graph(require_action_assets=False)
elapsed=time.perf_counter()-started
peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({'graph_load_seconds':elapsed,'peak_rss_kib':peak,
                  'associations':len(knowledge._profile_cache),'graph_triples':len(graph)}))
if elapsed>600 or peak>8*1024*1024:
    raise RuntimeError('Graph exceeds the declared resource limit')
"""
    result = subprocess.run([sys.executable,"-B","-c",code,str(submission)],capture_output=True,text=True,check=True)
    return json.loads(result.stdout)


def approved_text_assets(receipt, destination):
    assets = receipt.get("text_assets", {})
    if not isinstance(assets, dict) or set(assets) - {"questions", "labels", "exam_requests"}:
        raise ValueError("Admission permits approved questions, display labels and examination requests")
    result = {}
    for name, asset in assets.items():
        source = workspace_path(ROOT / asset["path"])
        owned = source.is_relative_to(ROOT / "data") or (destination.is_relative_to(ROOT / "Tmp") and source.is_relative_to(ROOT / "Tmp"))
        if source.suffix != ".json" or not owned or file_hash(source) != asset["sha256"]:
            raise ValueError("Clinical text differs from its data-owned approval pin")
        result[name] = source
    return result


def apply_exam_requests(builder, path):
    import unicodedata
    requests = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(requests, dict) or not requests:
        raise ValueError("Examination requests must map admitted method identifiers to text")
    for uri, text in requests.items():
        if ((URIRef(uri), RDF.type, OW.ExamMethod) not in builder.vocabulary or not isinstance(text, str)
                or unicodedata.normalize("NFC", text) != text or not 1 <= len(text) <= 30):
            raise ValueError("Prepared examination requires an admitted method and 1 to 30 NFC codepoints")
        builder.vocabulary.set((URIRef(uri), OW.examRequestText, Literal(text)))


def admit(database_path,review_path,*,destination=None,report_path=None):
    database_path,review_path = workspace_path(database_path),workspace_path(review_path)
    destination = workspace_path(destination or ROOT/"submission/knowledge")
    if destination!=ROOT/"submission/knowledge" and not destination.is_relative_to(ROOT/"Tmp"):
        raise ValueError("Admission destination must be runtime knowledge or isolated test scratch")
    database = SourceDatabase(database_path)
    try:
        if database.meta("stage")!="complete":
            raise ValueError("Admission requires a complete build")
        identity = database.meta("identity")
        for source in identity["inputs"]:
            if file_hash(ROOT/source["path"])!=source["sha256"]:
                raise ValueError("Admission source pin changed")
        if file_hash(ROOT/"data/ontology/schema.ttl")!=identity["schema"] or file_hash(ROOT/"submission/knowledge/scoring_policy.json")!=identity["scoring_policy"]:
            raise ValueError("Admission schema or policy changed")
        receipt = json.loads(review_path.read_text(encoding="utf-8"))
        graph_only = receipt.get("admission_scope") == "graph"
        if database.meta("admission_scope") == "graph" and not graph_only and not receipt.get("text_assets"):
            raise ValueError("D20 consultation admission requires prepared text assets")
        if database.meta("admission_scope") == "graph" and receipt.get("accepted_connection_policy") != identity.get("connection_policy"):
            raise ValueError("Graph admission requires acceptance of its exact connection policy")
        builder = validated_selection(database,receipt)
        text_sources = approved_text_assets(receipt, destination)
        if "exam_requests" in text_sources:
            apply_exam_requests(builder, text_sources["exam_requests"])
        receipt_hash = digest(receipt)
        staging = ROOT/"Tmp"/"ontology-v5-admission"/receipt_hash/str(uuid4())
        runtime = staging/"submission"
        shutil.copytree(ROOT/"submission",runtime,ignore=shutil.ignore_patterns("__pycache__","*.pyc","manifest.json"))
        output = staging/"export"
        report = builder.export(output,source_snapshots=database.source_snapshots(),report=database.meta("report"),
                                dispositions=DispositionRecords(database),require_action_assets=not graph_only)
        manifest = json.loads((output/"manifest.json").read_text())
        text_assets = receipt.get("text_assets",{})
        for name,source in text_sources.items():
            if name == "exam_requests":
                continue
            shutil.copyfile(source,output/source.name)
            manifest[name] = {"path":"knowledge/"+source.name,"sha256":text_assets[name]["sha256"]}
        text_status = ("patient_actions_prepared" if "exam_requests" in text_assets else
                       "minimal_questions_prepared" if text_assets else "not_prepared_in_this_slice")
        manifest.update(preparation_status="graph_admitted_text_pending" if graph_only else "admitted",
                        build_id=database.meta("build_id"),review_receipt_sha256=receipt_hash,
                        approval_basis=receipt.get("approval_basis","reviewed_batch"),
                        independent_clinical_validation=receipt.get("independent_clinical_validation","not_run"),
                        clinical_text_status=text_status)
        assets = [manifest["schema"],manifest["vocabulary"],*manifest["bundles"],manifest["scoring_policy"],manifest["reasoning_policy"]]
        assets.extend(manifest[name] for name in text_assets if name != "exam_requests")
        staged_knowledge = runtime/"knowledge"
        for asset in assets:
            source = output/Path(asset["path"]).name
            fixed = staged_knowledge/source.name
            structural = source.name in {"schema.ttl","scoring_policy.json"}
            new_name = source.name if structural and fixed.is_file() and file_hash(fixed)==asset["sha256"] else f"{receipt_hash[:16]}-{source.name}"
            asset["path"] = "knowledge/"+new_name
            if new_name != source.name:
                shutil.copyfile(source,staged_knowledge/new_name)
        write(staged_knowledge/"manifest.json",manifest)
        metrics = measure_prepare(runtime,graph_only=graph_only)
        destination.mkdir(parents=True,exist_ok=True)
        for asset in assets:
            source = staged_knowledge/Path(asset["path"]).name
            target = destination/source.name
            if target.exists() and file_hash(target)!=asset["sha256"]:
                raise ValueError("Existing admission asset has conflicting bytes")
            if not target.exists():
                temporary = target.with_suffix(target.suffix+".tmp")
                shutil.copyfile(source,temporary)
                temporary.replace(target)
        write(destination/"manifest.json",manifest)
        with database.connection:
            database.connection.execute("INSERT OR REPLACE INTO review_batches VALUES(?,?)",(receipt_hash,json_text(receipt)))
        result = {"status":manifest["preparation_status"],"build_id":database.meta("build_id"),"receipt_sha256":receipt_hash,
                  "associations":report["associations"],"metrics":metrics,"clinical_text":text_status,
                  "approval_basis":manifest["approval_basis"],"independent_clinical_validation":manifest["independent_clinical_validation"]}
        write(workspace_path(report_path) if report_path else database_path.parent/"admission.json",result)
        return result
    finally:
        database.close()
