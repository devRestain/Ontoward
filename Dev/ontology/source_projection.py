from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import inspect
import json
from pathlib import Path
import re

from rdflib import Graph, RDF, RDFS

from .database import DispositionRecords, SourceDatabase, file_hash, json_text, source_rows
from .v5 import NORMALIZATION_VERSION, OW, PreviewBuilder, ROOT, digest, workspace_path, write
from submission.knowledge.conditions import ScoringPolicy

IS_A, DUE_TO, ASSOCIATED_WITH = "116680003", "42752001", "47429007"
INFERRED, FSN, PREFERRED = "900000000000011006", "900000000000003001", "900000000000548007"
ATTRIBUTE_MAP = {"363698007":"Location","246112005":"Severity","263502005":"Course","272741003":"Laterality"}
AXES = {"location":"Location","laterality":"Laterality","radiating":"RadiationLocation",
        "onset":"Onset","duration_since":"TimeSinceOnset","duration_lasts":"EpisodeDuration",
        "temporal_pattern":"TemporalPattern","severity":"Severity","pain_type":"PainQuality",
        "aggravated":"AggravatingFactor","relieved":"RelievingFactor"}
BODHI_FILES = ("nodes_condition.csv","nodes_symptom.csv","nodes_speciality.csv","edges_present_in.csv",
               "edges_treated_by.csv","edges_is_influenced_by.csv","edges_related_to.csv","edges_has_prerequisite.csv")


def composition(releases):
    versions, dependencies, packages = {}, [], []
    for directory in releases:
        metadata = json.loads((directory/"release_package_information.json").read_text(encoding="utf-8"))
        date = metadata["effectiveTime"]
        if not re.fullmatch(r"\d{8}",date):
            raise ValueError("Release metadata must declare an effective date")
        files = list((directory/"Snapshot/Refset/Metadata").glob("*ModuleDependencySnapshot*.txt"))
        if len(files)!=1:
            raise ValueError("Require one module dependency snapshot")
        latest = {}
        for _,row in source_rows(files[0],rf2=True):
            previous = latest.get(row["id"])
            if previous and row["effectiveTime"]==previous["effectiveTime"] and row!=previous:
                raise ValueError("Conflicting same-version module dependency")
            if previous is None or row["effectiveTime"]>previous["effectiveTime"]:
                latest[row["id"]] = row
        active = [r for r in latest.values() if r["active"]=="1"]
        if not active:
            raise ValueError("Release requires active module dependencies")
        for row in active:
            version = row["sourceEffectiveTime"]
            if version>date or (row["moduleId"] in versions and versions[row["moduleId"]]!=version):
                raise ValueError("Conflicting module version")
            versions[row["moduleId"]] = version
            dependencies.append(row)
        packages.append({"directory":directory.relative_to(ROOT).as_posix(),"effective_time":date,
                         "license":metadata.get("licenceStatement",""),"language_refsets":metadata.get("languageRefsets",[])})
    versions.setdefault("900000000000012004",packages[0]["effective_time"])
    for row in dependencies:
        if versions.get(row["referencedComponentId"])!=row["targetEffectiveTime"]:
            raise ValueError("Module dependency does not match supplied release")
    return {"module_versions":versions,"dependencies":dependencies,"packages":packages}


class SnapshotSources:
    def __init__(self, database):
        self.database = database
        self.connection = database.connection
        self.concepts = {r["id"]:(r["active"],r["module_id"],r["effective_time"])
                         for r in self.connection.execute("SELECT id,active,module_id,effective_time FROM rf2_components WHERE kind='concept'")}
        self.parents, self.children = defaultdict(list), defaultdict(list)
        for row in self.connection.execute("""SELECT id,source_id,destination_id FROM rf2_components
                WHERE kind='relationship' AND active='1' AND type_id=? AND characteristic=?""",(IS_A,INFERRED)):
            child,parent = row["source_id"],row["destination_id"]
            if self.active(child) and self.active(parent):
                self.parents[child].append((parent,row["id"]))
                self.children[parent].append(child)
        for parents in self.parents.values():
            parents.sort()
        self.diseases = self.descendants({"64572001"})
        self.findings = self.descendants({"404684003"})
        self.signs = self.descendants({"72670004"}) if self.active("72670004") else set()
        self.fsns = {r["concept_id"]:r["term"] for r in self.connection.execute("""SELECT concept_id,term FROM rf2_components
            WHERE kind='description' AND active='1' AND language='en' AND type_id=? ORDER BY id""",(FSN,))}

    def active(self,cid):
        return cid in self.concepts and self.concepts[cid][0]=="1"

    def descendants(self,seeds):
        found,stack = {cid for cid in seeds if self.active(cid)}, [cid for cid in seeds if self.active(cid)]
        while stack:
            for child in self.children.get(stack.pop(),[]):
                if child not in found:
                    found.add(child)
                    stack.append(child)
        return found

    def ancestor_paths(self,cid):
        paths,queue = {cid:[]}, deque([cid])
        while queue:
            child = queue.popleft()
            for parent,relation in self.parents.get(child,[]):
                if parent not in paths:
                    paths[parent] = [*paths[child],relation]
                    queue.append(parent)
        return paths

    def descriptions(self,wanted):
        output,descriptions = {},defaultdict(list)
        ids = sorted(wanted)
        for offset in range(0,len(ids),700):
            batch = ids[offset:offset+700]
            marks = ",".join("?" for _ in batch)
            query = f"""SELECT c.*,r.payload,f.path,r.line FROM rf2_components c
                JOIN source_rows r ON r.id=c.row_id JOIN source_files f ON f.id=r.file_id
                WHERE c.kind='description' AND c.active='1' AND c.concept_id IN ({marks})"""
            for row in self.connection.execute(query,batch):
                descriptions[row["concept_id"]].append({**json.loads(row["payload"]),"file":row["path"],"line":row["line"]})
        description_ids = [r["id"] for members in descriptions.values() for r in members]
        preferred = {}
        for offset in range(0,len(description_ids),700):
            batch = description_ids[offset:offset+700]
            marks = ",".join("?" for _ in batch)
            query = f"SELECT source_id,refset_id FROM rf2_components WHERE kind='language' AND active='1' AND acceptability=? AND source_id IN ({marks})"
            for row in self.connection.execute(query,[PREFERRED,*batch]):
                priority = {"21000267104":0,"900000000000509007":0,"900000000000508004":1}.get(row["refset_id"],2)
                preferred[row["source_id"]] = min(priority,preferred.get(row["source_id"],priority))
        for cid,members in descriptions.items():
            labels, selected = {}, {}
            for language in ("en","ko"):
                options = sorted((r for r in members if r["languageCode"]==language),
                    key=lambda r:(preferred.get(r["id"],3),r["typeId"]!=FSN,r["term"],r["id"]))
                if options:
                    row = options[0]
                    labels[language] = re.sub(r"\s*\([^()]+\)$","",row["term"]) if row["typeId"]==FSN else row["term"]
                    selected[language] = row
            output[cid] = {"labels":labels,"selected":selected,"fsn":self.fsns.get(cid),"descriptions":sorted(members,key=lambda r:r["id"])}
        return output

    def relationships(self,wanted):
        selected = defaultdict(list)
        ids = sorted(wanted)
        for offset in range(0,len(ids),700):
            batch = ids[offset:offset+700]
            marks = ",".join("?" for _ in batch)
            query = f"""SELECT c.row_id,r.payload,f.path,r.line FROM rf2_components c
                JOIN source_rows r ON r.id=c.row_id JOIN source_files f ON f.id=r.file_id
                WHERE c.kind='relationship' AND c.active='1' AND c.characteristic=? AND c.source_id IN ({marks})"""
            for row in self.connection.execute(query,[INFERRED,*batch]):
                value = {**json.loads(row["payload"]),"file":row["path"],"line":row["line"],"row_id":row["row_id"]}
                selected[value["sourceId"]].append(value)
        for members in selected.values():
            members.sort(key=lambda r:r["id"])
        return selected


def temporal_value(raw):
    text = raw.strip().casefold()
    units = {"second":"s","sec":"s","s":"s","minute":"min","min":"min","hour":"h","h":"h",
             "day":"day","week":"week","month":"month","year":"year"}
    unit_pattern = r"(seconds?|secs?|s|minutes?|mins?|hours?|h|days?|weeks?|months?|years?)"
    unit = lambda value:units[value.rstrip("s") if value!="s" else value]
    interval = re.fullmatch(r"(\d+(?:\.\d+)?)\s*"+unit_pattern+r"\s+to\s+(\d+(?:\.\d+)?)\s*"+unit_pattern,text)
    shared = re.fullmatch(r"(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s*"+unit_pattern,text)
    if interval or shared:
        lower,a,upper,b = interval.groups() if interval else (shared[1],shared[3],shared[2],shared[3])
        return {"kind":"interval","lower":float(lower),"upper":float(upper),"unit":unit(a),"upper_unit":unit(b)}
    point = re.fullmatch(r"(?:(less than|more than|at least|at most|<=|>=|<|>)\s*)?(\d+(?:\.\d+)?|a|an)\s*"+unit_pattern,text)
    if point:
        comparator,value,a = point.groups()
        return {"kind":"quantity","value":1.0 if value in {"a","an"} else float(value),"unit":unit(a),
                "operator":{None:"eq","less than":"lt","more than":"gt","at least":"ge","at most":"le","<":"lt",">":"gt","<=":"le",">=":"ge"}[comparator]}
    raise ValueError("temporal_expression_unresolved")


class Normalizer:
    def __init__(self,builder):
        self.builder = builder
        self.source_refs = []

    def value(self,attribute,text,*,cid=None):
        if not self.source_refs:
            raise ValueError("A categorical value requires an exact source row")
        uri = str(OW)+"SnomedCT"+cid if cid else str(OW)+"AttributeValue"+digest([attribute,text.casefold()])[:24]
        self.builder.concept(uri,"AttributeValue",text,snomed_id=cid,source_refs=self.source_refs)
        return uri

    def categorical(self,attribute,text,*,cid=None):
        self.builder.concept(str(OW[attribute]),"FindingAttribute",attribute,source_refs=self.source_refs)
        if " or " in text and " and " in text:
            raise ValueError("conjunction_scope_unresolved")
        separator = " or " if " or " in text else " and "
        pieces = text.split(separator)
        values = sorted({self.value(attribute,piece.strip(),cid=cid if len(pieces)==1 else None) for piece in pieces})
        expected = {"kind":"concept","concept":values[0]} if len(values)==1 else {
            "kind":"concept_set","concepts":values,"selection":"any_of" if separator==" or " else "all_of"}
        return {"attribute":str(OW[attribute]),"expected":expected}

    def qualifier(self,target,axis,raw):
        text = re.sub(r"\s+"," ",raw).strip().casefold()
        if axis=="characteristic":
            if target=="49727002":
                mapping = {"dry cough":("Quality","dry"),"productive cough":("Quality","productive"),
                           "yellow sputum":("SputumColour","yellow"),"green sputum":("SputumColour","green"),
                           "clear sputum":("SputumColour","clear"),"blood stained":("SputumContent","blood stained"),
                           "bark like sound":("CoughSound","bark like")}
                if text in mapping:
                    return self.categorical(*mapping[text])
            if any(k in text for k in ("chill","rigor","nausea","tender","with ","associated")):
                raise ValueError("linked_finding_deferred")
            raise ValueError("characteristic_meaning_unresolved")
        if axis not in AXES:
            raise ValueError("axis_unresolved")
        attribute = AXES[axis]
        if axis in {"duration_since","duration_lasts"}:
            self.builder.concept(str(OW[attribute]),"FindingAttribute",axis,source_refs=self.source_refs)
            return {"attribute":str(OW[attribute]),"expected":temporal_value(text)}
        if axis=="severity" and text not in {"mild","moderate","severe"}:
            raise ValueError("severity_conditions_or_units_unresolved")
        if axis=="temporal_pattern" and re.search(r"\d",text):
            raise ValueError("frequency_window_unresolved")
        if axis=="laterality" and text not in {"left","right","left side","right side","bilateral","unilateral","one side","both","both sides","alternating"}:
            raise ValueError("laterality_location_scope_unresolved")
        return self.categorical(attribute,text)


def target_uri(cid):
    return str(OW)+"SymptomSnomedCT"+cid


def projection(database, *, llm=False, max_calls=0, daily_remaining=0, allowance_date=None):
    terminology = SnapshotSources(database)
    builder,dispositions = PreviewBuilder(),DispositionRecords(database)
    variant_counts,condition_counts,snomed_counts = Counter(),Counter(),Counter()
    normalizer = Normalizer(builder)
    conditions = {r["snomed_id"]:(rid,line,r) for rid,line,r in database.bodhi_rows("nodes_condition.csv")}
    symptoms = {r["uuid"]:(rid,line,r) for rid,line,r in database.bodhi_rows("nodes_symptom.csv")}
    if len(conditions)!=len(database.bodhi_rows("nodes_condition.csv")) or len(symptoms)!=len(database.bodhi_rows("nodes_symptom.csv")):
        raise ValueError("Duplicate BODHI node identity")
    roots = {r["root_snomed_id"] for _,_,r in symptoms.values()}
    supported_symptoms = terminology.descendants({cid for cid in roots
        if terminology.fsns.get(cid, "").endswith("(finding)") and cid not in terminology.signs})
    target_roles = {}
    for cid in sorted((terminology.findings-terminology.diseases)|roots):
        if not terminology.active(cid):
            continue
        if cid in terminology.signs:
            target_roles[cid] = (None,"exam_method_not_reviewed")
        elif cid in supported_symptoms:
            target_roles[cid] = ("Symptom","source_symptom_role_candidate")
        else:
            target_roles[cid] = (None,"target_role_unresolved")
    model_packets = {}
    parsed,variant_reasons = {},{}
    for uuid,(rid,line,row) in sorted(symptoms.items()):
        features,reasons = [],[]
        for n in range(1,4):
            axis,raw = row[f"relation{n}_type"],row[f"child{n}_name"]
            if bool(axis)!=bool(raw):
                reasons.append("incomplete_qualifier")
                continue
            if not axis:
                continue
            packet = {"kind":"qualifier","target_id":row["root_snomed_id"],"target_label":row["root_snomed_name"],"axis":axis,"text":raw}
            packet_id = digest(packet)
            normalizer.source_refs = [f"source_row:{rid}:relation{n}_type:child{n}_name"]
            try:
                feature = normalizer.qualifier(row["root_snomed_id"],axis,raw)
                features.append(feature)
                result,reason,decision = feature,None,"normalized"
            except ValueError as error:
                reason,result,decision = str(error),None,"unresolved"
                reasons.append((packet_id,reason))
                if reason=="characteristic_meaning_unresolved" and not re.search(r"\d",raw):
                    model_packets[packet_id] = {**packet,"packet_id":packet_id}
            database.connection.execute("INSERT OR REPLACE INTO normalizations VALUES(?,?,?,?,?,?)",
                (packet_id,json_text(packet),decision,reason,json_text(result) if result else None,"deterministic"))
        parsed[uuid],variant_reasons[uuid] = features,reasons
    for cid in sorted(roots):
        if target_roles.get(cid)==(None,"target_role_unresolved") and terminology.active(cid):
            packet = {"kind":"role","target_id":cid,"text":terminology.fsns.get(cid,cid),
                      "source_role":"BODHI Symptom node","source_labels":sorted({r["root_snomed_name"] for _,_,r in symptoms.values() if r["root_snomed_id"]==cid})}
            pid = digest(packet)
            model_packets[pid] = {**packet,"packet_id":pid}
    database.connection.commit()
    model_results,model_stats = {},{"calls_this_run":0,"stopped":None}
    if llm and model_packets:
        from .model_normalization import ModelNormalizer
        model = ModelNormalizer(ROOT/"data/preparation/v5/llm-ledger.sqlite3",max_calls=max_calls,
            daily_remaining=daily_remaining,day=allowance_date,namespace=database.meta("build_id"))
        try:
            model_results = model.normalize(list(model_packets.values()))
            model_stats = {"calls_this_run":model.calls,"stopped":model.stopped}
        finally:
            model.close()
    ledger = ROOT/"data/preparation/v5/llm-ledger.sqlite3"
    model_audit = []
    if ledger.exists():
        import sqlite3
        from .model_normalization import ATTRIBUTES, MODEL, PROMPT, ModelNormalizer
        namespace = digest([database.meta("build_id"),MODEL,PROMPT,sorted(ATTRIBUTES)])
        connection = sqlite3.connect(ledger.as_uri()+"?mode=ro",uri=True)
        try:
            for request_id,day,state,request,response,error in connection.execute("SELECT * FROM calls"):
                packets = json.loads(request)["packets"]
                keys = {digest([namespace,p]) for p in packets}
                owned = {row[0] for row in connection.execute("SELECT cache_key FROM packets WHERE request_id=?",(request_id,))}
                if keys != owned:
                    continue
                detail = None
                if response is not None and error:
                    try:
                        choice = json.loads(response)["choices"][0]
                        ModelNormalizer.validate(json.loads(choice["message"]["content"]),packets)
                    except Exception as failure:
                        detail = str(failure)
                model_audit.append({"request_id":request_id,"day":day,"state":state,"error":error,"validation_reason":detail,
                                    "packet_count":len(packets)})
        finally:
            connection.close()
    if not llm and any(item["error"] for item in model_audit):
        model_stats["stopped"] = "preserve_prior_model_failure_without_replay"
    for pid,result in model_results.items():
        packet = model_packets[pid]
        database.connection.execute("INSERT OR REPLACE INTO normalizations VALUES(?,?,?,?,?,?)",
            (pid,json_text(packet),result["decision"],result.get("reason"),json_text(result),"llm_candidate"))
        if packet["kind"]=="role" and result["decision"]=="normalized":
            cid = packet["target_id"]
            target_roles[cid] = ("Symptom","llm_role_candidate") if result["role"]=="Symptom" else (None,"exam_method_not_reviewed")
    targets = {cid for cid,(role,_) in target_roles.items() if role=="Symptom"}
    needed = targets|roots
    descendants = terminology.descendants(targets)
    supported_sources = {r[0] for r in database.connection.execute("""SELECT DISTINCT source_id FROM rf2_components
        WHERE kind='relationship' AND active='1' AND characteristic=? AND type_id IN (?,?)""",(INFERRED,DUE_TO,ASSOCIATED_WITH))}
    sources = descendants|supported_sources
    relations = terminology.relationships(sources)
    needed.update(sources)
    needed.update(r["destinationId"] for members in relations.values() for r in members if "destinationId" in r)
    descriptions = terminology.descriptions(needed)
    disease_uris,patterns = {},{}
    for cid in sorted(terminology.diseases):
        if cid in terminology.fsns or "en" in descriptions.get(cid,{}).get("labels",{}):
            disease_uris[cid] = str(OW)+"SnomedCT"+cid
    valid_conditions = set()
    for cid,(rid,line,row) in conditions.items():
        reason = None
        if not terminology.active(cid):
            reason = "inactive_snomed_identifier" if cid in terminology.concepts else "identifier_not_in_supplied_releases"
        elif cid not in disease_uris or row["concept_type"]!="Disorder" or row["type_condition"]=="medical_history" or re.match(r"^(h/o|fh)\b",row["name"],re.I):
            reason = "context_or_non_disease_entity"
        if reason is None:
            valid_conditions.add(cid)
        payload = {"dataset":"bodhi-s","source_file":"nodes_condition.csv","line":line,"source_id":cid,
                   "decision":"excluded" if reason else "accepted_preview","reason":reason,"raw":row}
        condition_counts[reason or "accepted_preview"] += 1
        database.disposition(payload,row_id=rid)
    for cid in sorted(targets):
        labels = descriptions.get(cid,{}).get("labels",{})
        if "en" not in labels:
            target_roles[cid] = (None,"english_description_missing")
            continue
        builder.concept(target_uri(cid),"Symptom",labels["en"],korean=labels.get("ko"),snomed_id=cid,
                        aliases=[r["root_snomed_name"] for _,_,r in symptoms.values() if r["root_snomed_id"]==cid],source_refs=["rf2:concept:"+cid])
        builder.registry[target_uri(cid)]["role_basis"] = target_roles[cid][1]
    targets = {cid for cid in targets if target_roles[cid][0] is not None}
    def disease(cid):
        uri = disease_uris[cid]
        if cid not in descriptions:
            descriptions.update(terminology.descriptions({cid}))
        labels = descriptions[cid]["labels"]
        aliases = [conditions[cid][2]["name"]] if cid in conditions else []
        builder.concept(uri,"Disease",labels["en"],korean=labels.get("ko"),aliases=aliases,snomed_id=cid,
                        source_refs=["rf2:concept:"+cid])
        return uri
    for uuid,(rid,line,row) in sorted(symptoms.items()):
        cid = row["root_snomed_id"]
        reason = None if cid in targets else target_roles.get(cid,(None,"target_identifier_unverified"))[1]
        features = list(parsed[uuid])
        for unresolved in variant_reasons[uuid]:
            if isinstance(unresolved,str):
                reason = reason or unresolved
                continue
            pid,failure = unresolved
            result = model_results.get(pid)
            if result and result["decision"]=="normalized":
                normalizer.source_refs = [f"source_row:{rid}:codex_normalization:{pid}"]
                for feature in result["features"]:
                    builder.concept(str(OW[feature["attribute"]]),"FindingAttribute",feature["attribute"],source_refs=normalizer.source_refs)
                    values = [normalizer.value(feature["attribute"],v.casefold()) for v in feature["values"]]
                    expected = {"kind":"concept","concept":values[0]} if len(values)==1 else {
                        "kind":"concept_set","concepts":sorted(values),"selection":feature["selection"]}
                    features.append({"attribute":str(OW[feature["attribute"]]),"expected":expected})
            else:
                reason = reason or failure
        if reason is None:
            patterns[uuid] = builder.pattern(target_uri(cid),features)
        payload = {"dataset":"bodhi-s","source_file":"nodes_symptom.csv","line":line,"source_id":uuid,
                   "decision":"unresolved" if reason else "accepted_preview","reason":reason,"raw":row,
                   "pattern_id":patterns.get(uuid),"verified_root_sctid":cid if terminology.active(cid) else None}
        variant_counts[reason or "accepted_preview"] += 1
        database.disposition(payload,row_id=rid)
    policy,conflicts = ScoringPolicy.load_default(),[]
    for rid,line,row in database.bodhi_rows("edges_present_in.csv"):
        uuid,cid = row["symptom_uuid"],row["condition_snomed_id"]
        reason = None
        if uuid not in symptoms or cid not in conditions:
            reason = "dangling_source_endpoint"
        elif uuid not in patterns or cid not in valid_conditions:
            reason = "dependent_variant_or_disease_unresolved"
        prediction,typicality = row["likelihood_condition_given_symptom"].casefold(),row["likelihood_symptom_given_condition"].casefold()
        if prediction not in policy.labels or typicality not in policy.labels or row["strong_predictor"] not in {"","0","1"}:
            reason = reason or "source_label_unresolved"
        payload = {"dataset":"bodhi-s","source_file":"edges_present_in.csv","line":line,"raw":row,
                   "decision":"excluded" if reason else "accepted_preview","reason":reason}
        if reason is None:
            payload["association_id"] = builder.association(disease(cid),patterns[uuid],
                source_ref=f"bodhi-s:{database.meta('build_id')}:edges_present_in.csv:{line}",relation_basis="bodhi_present_in",
                predictiveness=prediction,typicality=typicality,strong_predictor=None if row["strong_predictor"]=="" else row["strong_predictor"]=="1",
                raw={"edge_row_id":rid,"symptom_uuid":uuid,"symptom_row_id":symptoms[uuid][0],"condition_row_id":conditions[cid][0]})
            if row["strong_predictor"]=="1" and prediction in {"zero","rare","low"}:
                conflicts.append({"reason":"strong_predictor_likelihood_conflict","line":line,"raw":row})
        database.disposition(payload,row_id=rid)
    packets = 0
    for cid,members in sorted(relations.items()):
        paths = terminology.ancestor_paths(cid)
        target_paths = [(tid,paths[tid]) for tid in sorted(targets & paths.keys())]
        if not target_paths:
            continue
        links = [(r["destinationId"],"due_to" if r["typeId"]==DUE_TO else "associated_with",r)
                 for r in members if r["typeId"] in {DUE_TO,ASSOCIATED_WITH} and r.get("destinationId") in disease_uris]
        if cid in terminology.diseases:
            links.extend((did,"subtype_intersection",None) for did in sorted(paths.keys() & disease_uris.keys()) if did!=cid)
        qualified = [r for r in members if r["typeId"] not in {IS_A,DUE_TO,ASSOCIATED_WITH}]
        expression_id = database.expression({"source_concept_id":cid,
            "relationship_ids":[r['id'] for r in members]})
        groups = {r["relationshipGroup"] for r in qualified if r["relationshipGroup"]!="0"}
        features,reasons = [],[]
        if len(groups)>1:
            reasons.append("relationship_group_scope_unresolved")
        for row in qualified:
            attribute,value = ATTRIBUTE_MAP.get(row["typeId"]),row.get("destinationId")
            label = descriptions.get(value,{}).get("labels",{}).get("en")
            if not attribute or not value or not terminology.active(value) or not label:
                reasons.append("required_rf2_condition_unresolved")
            else:
                normalizer.source_refs = ["rf2:"+row["id"]]
                builder.concept(str(OW[attribute]),"FindingAttribute",attribute,source_refs=normalizer.source_refs)
                concept = normalizer.value(attribute,label,cid=value)
                features.append({"attribute":str(OW[attribute]),"expected":{"kind":"concept","concept":concept}})
        for target,target_path in target_paths:
            for did,basis,link in links:
                packet = {"dataset":"SNOMED_CT","source_concept_id":cid,"disease_id":did,"target_id":target,
                          "relation_basis":basis,"target_path":target_path,"disease_path":paths.get(did),
                          "expression_id":expression_id,"relationship_id":link['id'] if link else None,
                          "decision":"unresolved" if reasons else "accepted_preview",
                          "reasons":sorted(set(reasons))}
                if not reasons:
                    pattern = builder.pattern(target_uri(target),features)
                    packet["pattern_id"] = pattern
                    packet["association_id"] = builder.association(disease(did),pattern,
                        source_ref="rf2:"+(link["id"] if link else digest([cid,did,target,target_path,paths[did]])),
                        relation_basis=basis,derivation_scope="descendant" if basis=="subtype_intersection" else "exact",raw=packet.copy())
                snomed_counts[packet["decision"]] += 1
                database.disposition(packet,row_id=link["row_id"] if link else None)
                packets += 1
                if packets % 10000 == 0:
                    database.connection.commit()
                    print(json_text({"stage":"rf2_projection","packets":packets}),flush=True)
    for entry in builder.registry.values():
        cid = entry["snomed_id"]
        if cid in terminology.concepts:
            record = terminology.concepts[cid]
            entry["snomed_record"] = {"id":cid,"active":record[0],"moduleId":record[1],"effectiveTime":record[2]}
            entry["descriptions"] = descriptions.get(cid,{})
            entry["mapping_status"] = "identifier_verified_semantic_review_pending"
    database.set_meta("target_roles",{cid:{"role":role,"reason":reason} for cid,(role,reason) in target_roles.items()})
    for name in BODHI_FILES:
        if name not in {"nodes_condition.csv","nodes_symptom.csv","edges_present_in.csv"}:
            database.connection.execute("""UPDATE source_rows SET reason='no_lossless_v5_execution_role'
                WHERE file_id=(SELECT id FROM source_files WHERE path LIKE ?)""",("%/"+name,))
    database.connection.commit()
    report = {"build_id":database.meta("build_id"),"database":"ontology.sqlite3","scope":"full_snapshot_and_bodhi_s",
              "targets":{cid:target_uri(cid) for cid in sorted(targets)},"discovered_target_roles":dict(Counter(reason for _,reason in target_roles.values())),
              "source_counts":{Path(f["path"]).name:f["row_count"] for f in database.inventory()},
              "bodhi_selected_variants":len(symptoms),"bodhi_projected_variants":len(patterns),
              "bodhi_variant_dispositions":dict(variant_counts),
              "condition_dispositions":dict(condition_counts),
              "snomed_packets":packets,"snomed_dispositions":dict(snomed_counts),
              "exceptions":conflicts,"model_calls":len(model_audit),"model_stage":model_stats,"model_audit":model_audit,
              "model_pending_packets":len(set(model_packets)-set(model_results)),"normalization_version":NORMALIZATION_VERSION}
    return builder,report,dispositions


def build(international,korean,bodhi,output,*,resume=False,llm=False,max_calls=0,daily_remaining=0,allowance_date=None):
    releases = [workspace_path(international),*([workspace_path(korean)] if korean else [])]
    bodhi,output = workspace_path(bodhi),workspace_path(output)
    if not output.is_relative_to(ROOT/"data/preparation/v5") and not output.is_relative_to(ROOT/"Tmp"):
        raise ValueError("Build output must be data-owned preparation or project scratch")
    inputs = [(directory/"release_package_information.json","SNOMED_CT",None) for directory in releases]
    composed = composition(releases)
    for directory,package in zip(releases,composed["packages"]):
        inputs.extend((path,"SNOMED_CT",package["effective_time"]) for path in sorted((directory/"Snapshot").rglob("*.txt")))
    inputs.extend((bodhi/name,"bodhi-s",None) for name in BODHI_FILES)
    inputs.extend((bodhi.parent.parent/name,"bodhi-s",None) for name in ("LICENSE","original_readme.md")
                  if (bodhi.parent.parent/name).is_file())
    identity = {"inputs":[{"path":p.relative_to(ROOT).as_posix(),"sha256":file_hash(p)} for p,_,_ in inputs],
                "schema":file_hash(ROOT/"data/ontology/schema.ttl"),"scoring_policy":file_hash(ROOT/"submission/knowledge/scoring_policy.json"),
                "normalization_version":NORMALIZATION_VERSION,"normalization_policy":digest([AXES,ATTRIBUTE_MAP,inspect.getsource(Normalizer),inspect.getsource(temporal_value)]),
                "schema_version":"5.0","composition":composed,
                "generator_files":{p.name:file_hash(p) for p in sorted((ROOT/"Dev/ontology").glob("*.py"))},
                "prompt_files":{p.name:file_hash(p) for p in sorted((ROOT/"Dev/ontology/prompts").glob("*.txt"))}}
    build_id = digest(identity)
    path = output/"ontology.sqlite3"
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError("Use a new build directory or explicit --resume")
    database = SourceDatabase(path)
    try:
        previous = database.meta("build_id")
        if previous and previous!=build_id:
            raise ValueError("Resume identity differs from source/schema/normalization pins")
        database.set_meta("build_id",build_id)
        database.set_meta("identity",identity)
        database.set_meta("composition",composed)
        if database.meta("stage")=="complete":
            return database.meta("report")
        for path,dataset,date in inputs:
            database.import_file(path,dataset=dataset,release_date=date,versions=composed["module_versions"])
        if database.meta("stage") != "projection_complete":
            if database.meta("stage") != "ingested":
                database.index_sources()
                database.set_meta("stage","ingested")
            for table in ("normalizations","dispositions"):
                database.connection.execute("DELETE FROM "+table)
            builder,report,dispositions = projection(database,llm=llm,max_calls=max_calls,daily_remaining=daily_remaining,allowance_date=allowance_date)
            database.save_builder(builder)
            database.set_meta("projection_conflicts",sorted(builder.conflicts))
            database.set_meta("projection_report",report)
            database.set_meta("stage","projection_complete")
        else:
            builder,report = database.builder(),database.meta("projection_report")
        dispositions = DispositionRecords(database)
        preview = output/"preview"
        if preview.exists() and any(preview.iterdir()):
            manifest = preview/'manifest.json'
            if not manifest.is_file() or json.loads(manifest.read_text()).get('build_id') != build_id:
                raise ValueError('Preserve an unrecognized preview; select a new build directory')
            import shutil
            shutil.rmtree(preview)
        result = builder.export(preview,source_snapshots=database.source_snapshots(),report=report,dispositions=dispositions)
        result["model_calls"] = report["model_calls"]
        write(preview/"report.json",result)
        database.save_builder(builder)
        database.set_meta("projection_conflicts",[])
        coverage = {"source_rows":database.connection.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0],
            "source_files":len(database.inventory()),"row_dispositions":{r[0]:r[1] for r in database.connection.execute("SELECT disposition,COUNT(*) FROM source_rows GROUP BY disposition")},
            "inactive_latest_components":database.connection.execute('SELECT COUNT(*) FROM inactive_rf2_rows').fetchone()[0],
            "inactive_classification":"read_only_view_without_raw_row_rewrites"}
        result["coverage"] = coverage
        write(output/"report.json",result)
        write(preview/"report.json",result)
        database.set_meta("report",result)
        from .source_catalog import extract_catalog
        result["catalog"] = extract_catalog(database, builder, output)
        database.set_meta("report", result)
        write(output/"report.json", result)
        database.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        from .admission import review_material
        review_material(database,preview)
        database.set_meta("stage","complete")
        return result
    finally:
        database.close()


def export(database_path,output):
    output = workspace_path(output)
    if not output.is_relative_to(ROOT/"data/preparation/v5") and not output.is_relative_to(ROOT/"Tmp"):
        raise ValueError("Candidate exports must stay in preparation or scratch until admission")
    database = SourceDatabase(database_path,readonly=True)
    try:
        if database.meta("stage")!="complete":
            raise ValueError("Export requires a completed build")
        dispositions = DispositionRecords(database)
        result = database.builder().export(output,source_snapshots=database.source_snapshots(),report=database.meta("report"),
            dispositions=dispositions, require_action_assets=database.meta("admission_scope") != "graph")
        result["model_calls"] = database.meta("report")["model_calls"]
        write(workspace_path(output)/"report.json",result)
        from .admission import review_material
        review_material(database,workspace_path(output))
        return result
    finally:
        database.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ontoward-source-projection")
    commands = parser.add_subparsers(dest="command",required=True)
    prepare = commands.add_parser("build")
    prepare.add_argument("--international",type=Path,required=True)
    prepare.add_argument("--korean",type=Path)
    prepare.add_argument("--bodhi",type=Path,required=True)
    prepare.add_argument("--output",type=Path,required=True)
    prepare.add_argument("--resume",action="store_true")
    prepare.add_argument("--llm",action="store_true")
    prepare.add_argument("--max-calls",type=int,default=0)
    prepare.add_argument("--daily-remaining",type=int,default=0)
    prepare.add_argument("--allowance-date")
    for name in ("export","admit"):
        command = commands.add_parser(name)
        command.add_argument("--database",type=Path,required=True)
        if name=="export":
            command.add_argument("--output",type=Path,required=True)
        else:
            command.add_argument("--review",type=Path,required=True)
    connections = commands.add_parser("connections")
    connections.add_argument("--database", type=Path, required=True)
    connections.add_argument("--output", type=Path, required=True)
    connections.add_argument("--accept-competition", action="store_true")
    korean_plan = commands.add_parser("korean-freeze")
    korean_plan.add_argument("--catalog", type=Path, required=True)
    korean_plan.add_argument("--output", type=Path, required=True)
    korean = commands.add_parser("korean")
    korean.add_argument("--workset", type=Path, required=True)
    korean.add_argument("--output", type=Path, required=True)
    korean.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.command=="build":
        if args.llm and (not args.allowance_date or args.max_calls<=0 or args.daily_remaining<=0):
            parser.error("Live normalization requires current --allowance-date and explicit positive budgets")
        result = build(args.international,args.korean,args.bodhi,args.output,resume=args.resume,llm=args.llm,
                       max_calls=args.max_calls,daily_remaining=args.daily_remaining,allowance_date=args.allowance_date)
    elif args.command=="connections":
        from .connections import build as build_connections
        result = build_connections(args.database, args.output, accept_competition=args.accept_competition)
    elif args.command=="korean-freeze":
        from .korean import freeze
        result = freeze(args.catalog,args.output)
    elif args.command=="korean":
        from .korean import run
        result = run(args.workset,args.output,resume=args.resume)
    elif args.command=="export":
        result = export(args.database,args.output)
    else:
        from .admission import admit
        result = admit(args.database,args.review)
    print(json.dumps({k:v for k,v in result.items() if k not in {"source_counts","targets","exceptions","excluded_context_edges"}},indent=2,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
