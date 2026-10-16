from __future__ import annotations

from collections import Counter, defaultdict
import json
import unicodedata

from rdflib import Graph, Literal, RDF, RDFS, URIRef

from .database import file_hash, json_text
from .provenance import EvidenceSets
from .v5 import OW, ROOT, digest, write

DERIVED_CLASSES = {"ClinicalPattern", "ClinicalFeature", "ExpectedValue", "DiseasePatternAssociation", "ValueMatch"}
ROLE_RULES = {
    "Disease":"Active disorder used by a complete source association",
    "Symptom":"Explicit active BODHI symptom root or non-disorder finding descendant; exclude physical signs and preserve the SNOMED taxonomy role separately",
    "ExamFinding":"Active non-disorder finding with physical method clinical observable morphologic-site or Sign evidence; preserve uncertain acquisition roles",
    "FindingAttribute":"Source condition axis or clinical Observable comparison dimension; keep acquisition and Observable model metadata in their source roles",
    "AttributeValue":"A categorical value explicitly used in a selected source condition",
    "ContextFactor":"Explicit BODHI medical-history node; not unconditional disease support",
    "BodySystem":"Named immediate body-system subtype on a selected anatomical value's source ancestry",
    "ExamMethod":"Physical-examination procedure explicitly adjacent to selected source concepts",
    "Test":"Laboratory or imaging procedure explicitly adjacent to selected source concepts",
    "ClinicalPattern":"Complete source variant, independent of disease",
    "ClinicalFeature":"Pattern-local source status or attribute condition",
    "ExpectedValue":"Typed value of a selected source condition",
    "DiseasePatternAssociation":"Source disease-pattern-applicability assertion",
    "ValueMatch":"Exact RF2 is-a comparison between selected categorical concepts",
}


def clinical_question_status(kind, label):
    if kind in DERIVED_CLASSES or kind in {"Disease", "AttributeValue", "BodySystem", "Test"}:
        return "not_applicable_" + kind
    if kind in {"ExamFinding", "ExamMethod"}:
        return "unresolved_source_detection_or_maneuver_mapping"
    if kind == 'FindingAttribute':
        return 'not_directly_interviewed_attribute_dimension'
    if kind == "Symptom" and any(word in label.casefold() for word in
            ("due to", "secondary to", "caused by", "associated with")):
        return "not_directly_interviewable_diagnosis_qualified"
    return "pending_clinical_question"


def extract_catalog(database, builder, output):
    from .source_projection import SnapshotSources, IS_A, INFERRED, BODHI_FILES
    terminology = SnapshotSources(database)
    connection = database.connection
    evidence_sets = EvidenceSets()
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS schema_nodes(
            uri TEXT NOT NULL,kind TEXT NOT NULL,snomed_id TEXT,label TEXT,korean TEXT,
            evidence TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(uri,kind));
        CREATE TABLE IF NOT EXISTS schema_edges(
            id TEXT PRIMARY KEY,subject TEXT NOT NULL,predicate TEXT NOT NULL,object TEXT NOT NULL,
            evidence TEXT NOT NULL,status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS selected_terms(
            concept_id TEXT,language TEXT,term TEXT,id TEXT,row_id INTEGER,type_id TEXT,
            PRIMARY KEY(concept_id,language));
        CREATE TABLE IF NOT EXISTS evidence_refs(id INTEGER PRIMARY KEY,ref TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS evidence_sets(id TEXT PRIMARY KEY,members TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS catalog_assertions(association_id TEXT,assertion_index INTEGER,payload TEXT,
            PRIMARY KEY(association_id,assertion_index));
        DELETE FROM schema_nodes;
        DELETE FROM schema_edges;
        DELETE FROM selected_terms;
        DELETE FROM evidence_refs;
        DELETE FROM evidence_sets;
        DELETE FROM catalog_assertions;
    """)
    entries = {uri:dict(entry) for uri, entry in builder.registry.items()}
    from .findings import project as project_findings, coverage as finding_coverage, PHYSICAL_METHOD_ROOTS
    source, source_proofs, finding_details = project_findings(database,terminology,builder)
    for uri, entry in source.registry.items():
        if uri in entries:
            entries[uri]['source_refs'] = sorted(set(entries[uri]['source_refs']) | set(entry['source_refs']))
        else:
            entries[uri] = dict(entry)
    symptom_rows = defaultdict(list)
    for row_id, _, row in database.bodhi_rows("nodes_symptom.csv"):
        symptom_rows[row["root_snomed_id"]].append(row_id)
    for entry in entries.values():
        if entry["kind"] != "Symptom":
            continue
        cid = entry["snomed_id"]
        paths = terminology.ancestor_paths(cid)
        roots = set(paths) & symptom_rows.keys()
        if not roots or cid in terminology.signs or (cid in terminology.diseases and cid not in symptom_rows):
            raise ValueError("Symptom lacks an explicit BODHI role or eligible finding path: " + cid)
        root = cid if cid in roots else min(roots, key=lambda key:(len(paths[key]), key))
        refs = [f"source_row:{row_id}:root_snomed_id" for row_id in symptom_rows[root]]
        refs += ["rf2:" + rid for rid in paths[root]]
        entry["source_refs"] = sorted(set(entry["source_refs"]) | set(refs))
        entry["source_role"] = "BODHI_symptom_record" if cid == root else "RF2_finding_descendant_of_BODHI_symptom"
        entry["snomed_taxonomy_role"] = "disorder" if cid in terminology.diseases else "finding"
        entry["role_path"] = {"bodhi_root":root, "relationship_ids":paths[root]}
    selected_ids = {entry["snomed_id"] for entry in entries.values() if entry.get("snomed_id")}
    candidate_entries = []
    for row_id, line, row in database.bodhi_rows("nodes_condition.csv"):
        cid = row["snomed_id"]
        if row["type_condition"] == "medical_history" and terminology.active(cid):
            candidate_entries.append({"uri":str(OW)+"BodhiContext"+cid, "kind":"ContextFactor",
                "label":row["name"], "snomed_id":None, "source_refs":[f"source_row:{row_id}:name"],
                "source_role":"BODHI medical_history", "referenced_snomed_id":cid})
    related = {}
    for row in connection.execute("""SELECT id,source_id,destination_id,type_id,relationship_group,row_id,characteristic,concrete_value
            FROM rf2_components WHERE kind='relationship' AND active='1' AND characteristic=?""", (INFERRED,)):
        if row["source_id"] in selected_ids or row["destination_id"] in selected_ids:
            related[row["id"]] = dict(row)
    method_ids = terminology.descendants(PHYSICAL_METHOD_ROOTS)
    test_ids = terminology.descendants({"108252007", "363679005"})
    adjacent = defaultdict(set)
    for rid, row in related.items():
        for cid in (row["source_id"], row["destination_id"]):
            if cid not in selected_ids and terminology.active(cid):
                adjacent[cid].add("rf2:" + rid)
    for cid, refs in sorted(adjacent.items()):
        kind = "ExamMethod" if cid in method_ids else "Test" if cid in test_ids else None
        if kind:
            candidate_entries.append({"uri":str(OW)+kind+"SnomedCT"+cid, "kind":kind,
                "snomed_id":cid, "label":terminology.fsns.get(cid, cid), "source_refs":sorted(refs),
                "source_role":"source_procedure_candidate_not_a_detection_or_test_plan_link"})
    systems = {child for child in terminology.children.get("91689009", ())
               if "system" in terminology.fsns.get(child, "").casefold()}
    for entry in list(entries.values()):
        cid = entry.get("snomed_id")
        if entry["kind"] != "AttributeValue" or not cid:
            continue
        paths = terminology.ancestor_paths(cid)
        for system in sorted(systems & paths.keys()):
            candidate_entries.append({"uri":str(OW)+"BodySystemSnomedCT"+system, "kind":"BodySystem",
                "label":terminology.fsns.get(system, system), "snomed_id":system,
                "source_refs":["rf2:concept:"+system, *["rf2:"+rid for parent,rid in terminology.parents.get(system,()) if parent=="91689009"],
                               *["rf2:" + rid for rid in paths[system]]],
                "source_role":"named_immediate_system_on_selected_value_ancestry", "selected_value":cid})
    for entry in candidate_entries:
        previous = entries.get(entry["uri"])
        if previous:
            previous["source_refs"] = sorted(set(previous["source_refs"]) | set(entry["source_refs"]))
        else:
            entries[entry["uri"]] = entry
    wanted = {entry["snomed_id"] for entry in entries.values() if entry.get("snomed_id")}
    descriptions = terminology.descriptions(wanted)
    for cid, record in descriptions.items():
        for language, selected in record.get("selected", {}).items():
            source_row = connection.execute("""SELECT r.id FROM source_rows r JOIN source_files f ON f.id=r.file_id
                WHERE f.path=? AND r.line=?""", (selected["file"], selected["line"])).fetchone()
            connection.execute("INSERT INTO selected_terms VALUES(?,?,?,?,?,?)",
                (cid, language, selected["term"], selected["id"], source_row[0], selected["typeId"]))
    lexical = []
    for uri, entry in sorted(entries.items()):
        if not entry.get("source_refs"):
            raise ValueError("Selected vocabulary lacks source evidence: " + uri)
        cid = entry.get("snomed_id")
        if cid and not terminology.active(cid):
            raise ValueError("Selected vocabulary contains an inactive identifier")
        term = connection.execute("SELECT * FROM selected_terms WHERE concept_id=? AND language='ko'", (cid,)).fetchone()
        korean = unicodedata.normalize("NFC", term["term"]) if term else None
        evidence = {"rule":"competition_source_dependency", "source_refs":entry["source_refs"],
                    "source_role":entry.get("source_role", entry.get("role_basis", entry["kind"])),
                    "snomed_record":entry.get("snomed_record"),
                    "snomed_taxonomy_role":entry.get("snomed_taxonomy_role"), "role_path":entry.get("role_path"),
                    "referenced_snomed_id":entry.get("referenced_snomed_id")}
        evidence_id = evidence_sets.intern(evidence.pop('source_refs'))
        evidence['evidence_id'] = evidence_id
        evidence['acquisition'] = entry.get('acquisition')
        evidence['execution_status'] = entry.get('execution_status')
        connection.execute("INSERT INTO schema_nodes VALUES(?,?,?,?,?,?,?)",
            (uri, entry["kind"], cid, entry["label"], korean, json_text(evidence),
             "runtime_dependency_candidate" if uri in builder.registry else "source_role_candidate"))
        lexical_entry = {key:value for key,value in entry.items() if key not in {'source_refs','descriptions','evidence'}}
        lexical.append({**lexical_entry, 'evidence_id':evidence_id, "korean_label":korean,
            "korean_origin":"Korean_SNOMED_CT" if term else None,
            "korean_source":{"description_id":term["id"], "source_row_id":term["row_id"]} if term else None,
            "question_status":clinical_question_status(entry["kind"], entry["label"])})
    proofs, link_proofs = defaultdict(set), defaultdict(set)
    for triple, refs in source_proofs.items():
        link_proofs[triple].update(refs)
    for association, assertions in source.assertions.items():
        connection.executemany('INSERT INTO catalog_assertions VALUES(?,?,?)',
            ((association,n,json_text(assertion)) for n,assertion in enumerate(assertions)))
    clinical = builder.graph + source.graph
    all_assertions = {**builder.assertions, **source.assertions}
    for association, assertions in all_assertions.items():
        node = URIRef(association)
        refs = {assertion["source_ref"] for assertion in assertions}
        proofs[association].update(refs)
        for disease in clinical.subjects(OW.hasAssociation, node):
            proofs[str(disease)].update(refs)
        pattern = clinical.value(node, OW.pattern)
        if pattern is not None:
            proofs[str(pattern)].update(refs)
            target = clinical.value(pattern, OW.targets)
            for feature in clinical.objects(pattern, OW.hasFeature):
                proofs[str(feature)].update(refs)
                attribute = clinical.value(feature, OW.onAttribute)
                if attribute is not None:
                    link_proofs[(target, OW.hasAttribute, attribute)].update(refs)
                for expected in clinical.objects(feature, OW.expected):
                    proofs[str(expected)].update(refs)
                    payload = json.loads(str(clinical.value(expected, OW.valueJSON)))
                    for value in ([payload["concept"]] if payload.get("concept") else payload.get("concepts", ())):
                        link_proofs[(attribute, OW.canHaveValue, URIRef(value))].update(refs)
    for node, kind in clinical.subject_objects(RDF.type):
        name = str(kind).removeprefix(str(OW))
        if name not in DERIVED_CLASSES:
            continue
        refs = sorted(proofs[str(node)])
        if not refs:
            raise ValueError("Derived expression has no source assertions: " + str(node))
        connection.execute("INSERT INTO schema_nodes VALUES(?,?,?,?,?,?,?)",
            (str(node), name, None, None, None,
             json_text({"rule":"complete_source_variant_expression", "evidence_id":evidence_sets.intern(refs)}), "derived_source_candidate"))
    for rid, row in sorted(related.items()):
        connection.execute("INSERT INTO schema_edges VALUES(?,?,?,?,?,?)",
            ("rf2:"+rid, "http://snomed.info/id/"+row["source_id"], "http://snomed.info/id/"+row["type_id"],
             json_text({"concept":"http://snomed.info/id/"+row["destination_id"] if row["destination_id"] else None,
                        "concrete_value":row["concrete_value"],
                        "relationship_group":row["relationship_group"], "characteristic":row["characteristic"]}),
             json_text({"rule":"exact_rf2_relationship", "source_row_id":row["row_id"]}), "source_relation"))
    for name in BODHI_FILES:
        if not name.startswith("edges_"):
            continue
        for row_id, line, raw in database.bodhi_rows(name):
            subject = raw.get("condition_snomed_id_src", raw.get("condition_snomed_id", raw.get("src_id", raw.get("symptom_uuid"))))
            connection.execute("INSERT INTO schema_edges VALUES(?,?,?,?,?,?)",
                (f"bodhi-s:{name}:{line}", "bodhi-s:"+str(subject), "bodhi-s:"+name.removesuffix(".csv"),
                 json_text(raw), json_text({"rule":"exact_bodhi_source_edge", "source_row_id":row_id}), "source_relation"))
    for name, graph in (("vocabulary", builder.vocabulary + source.vocabulary), ("clinical", clinical)):
        for subject, predicate, obj in graph:
            refs = sorted(link_proofs[(subject,predicate,obj)] or
                          (set(entries.get(str(subject), {}).get("source_refs", ())) | proofs[str(subject)]))
            if not refs:
                raise ValueError("Projected triple lacks source evidence: " + str(subject))
            connection.execute("INSERT INTO schema_edges VALUES(?,?,?,?,?,?)",
                (digest([name, subject.n3(), predicate.n3(), obj.n3()]), str(subject), str(predicate),
                 json_text({"n3":obj.n3()}), json_text({"rule":"v5_"+name+"_projection", "evidence_id":evidence_sets.intern(refs)}),
                 "derived_source_candidate"))
    values = {entry["snomed_id"]:entry["uri"] for entry in entries.values()
              if entry["kind"]=="AttributeValue" and entry.get("snomed_id")}
    for rid, row in sorted(related.items()):
        if row["type_id"] != IS_A or row["source_id"] not in values or row["destination_id"] not in values:
            continue
        uri = str(OW)+"ValueMatch"+digest(rid)[:24]
        evidence = {"rule":"exact_rf2_is_a_value_comparison", "source_row_id":row["row_id"], "evidence_id":evidence_sets.intern(["rf2:"+rid])}
        connection.execute("INSERT INTO schema_nodes VALUES(?,?,?,?,?,?,?)",
            (uri, "ValueMatch", None, None, None, json_text(evidence), "derived_source_candidate"))
        for predicate, obj in ((RDF.type, OW.ValueMatch), (OW.observedConcept, URIRef(values[row["source_id"]])),
                (OW.expectedConcept, URIRef(values[row["destination_id"]])), (OW.relationKind, Literal("is_a")),
                (OW.sourceRef, Literal("rf2:"+rid))):
            connection.execute("INSERT INTO schema_edges VALUES(?,?,?,?,?,?)",
                (digest([uri, str(predicate), obj.n3()]), uri, str(predicate), json_text({"n3":obj.n3()}),
                 json_text(evidence), "derived_source_candidate"))
    connection.commit()
    catalog = output / "catalog"
    catalog.mkdir(exist_ok=True)
    evidence_sets.save(catalog/'evidence.json')
    encoded = json.loads((catalog/'evidence.json').read_text())
    connection.executemany('INSERT INTO evidence_refs VALUES(?,?)',enumerate(encoded['refs']))
    connection.executemany('INSERT INTO evidence_sets VALUES(?,?)',
        ((key,json_text(members)) for key,members in encoded['sets'].items()))
    connection.commit()
    source_graph = source.vocabulary + source.graph
    (catalog/'source-findings.ttl').write_text(''.join(sorted(f'{s.n3()} {p.n3()} {o.n3()} .\n' for s,p,o in source_graph)),encoding='utf-8')
    finding_report = finding_coverage(database,terminology,source,finding_details,catalog)
    for filename, table in (("nodes.jsonl","schema_nodes"), ("relations.jsonl","schema_edges")):
        with (catalog / filename).open("w", encoding="utf-8") as stream:
            for row in connection.execute("SELECT * FROM "+table+" ORDER BY "+("kind,uri" if table=="schema_nodes" else "id")):
                record = dict(row)
                record["evidence"] = json.loads(record["evidence"])
                if "object" in record:
                    record["object"] = json.loads(record["object"])
                stream.write(json_text(record)+"\n")
    write(catalog / "lexical.json", lexical)
    classes = sorted(str(node).removeprefix(str(OW)) for node in
        Graph().parse(ROOT/"data/ontology/schema.ttl").subjects(RDF.type, RDFS.Class))
    counts = dict(connection.execute("SELECT kind,COUNT(*) FROM schema_nodes GROUP BY kind"))
    korean_counts = Counter(entry["kind"] for entry in lexical if entry["korean_label"])
    report = {"schema_version":"5.0", "scope":"competition_source_dependency_closure",
        "status":"source_candidates", "classes":{kind:{"nodes":counts.get(kind,0),
            "korean_source_labels":korean_counts[kind], "rule":ROLE_RULES[kind],
            "unresolved_reason":None if counts.get(kind,0) else "no_evidenced_node_in_selected_competition_dependencies"}
            for kind in classes},
        "lexical_entries":len(lexical), "relations":connection.execute("SELECT COUNT(*) FROM schema_edges").fetchone()[0],
        "raw_source_rows_retained":connection.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0],
        "real_codex_calls":0, "runtime_admission":"not_run",
        "question_status":dict(Counter(entry["question_status"] for entry in lexical)),
        "finding_projection":{key:finding_report[key] for key in ('exam_findings','finding_attributes','method_links','source_patterns','source_associations','executable_exam_requests')},
        "evidence_storage":{"distinct_refs":len(encoded['refs']),"shared_sets":len(encoded['sets'])},
        "unsupported_runtime_relations":{"detectedBy":"Exact source method links remain candidate-only until reviewed request wording and admission",
            "evaluatedBy":"Do not turn specialty or cooccurrence into a test plan",
            "hasSupportingContext":"Preserve influence/prerequisite roles without unconditional support",
            "inSystem":"Anatomical ancestry does not automatically grant interview grouping"}}
    write(catalog / "coverage.json", report)
    write(catalog / 'audit.json', database.audit_reference())
    write(catalog / "manifest.json", {"build_id":database.meta("build_id"),
        "generator_files":database.meta("identity")["generator_files"], "scope":report["scope"],
        "prompt_files":database.meta("identity").get("prompt_files",{}),
        "files":{path.name:file_hash(path) for path in sorted(catalog.iterdir()) if path.name!="manifest.json" and path.is_file()},
        "sources":database.source_snapshots(), "source_finding_projection":"candidate_only_not_a_runtime_bundle", "runtime_admission":"not_run"})
    return report
