from __future__ import annotations

from collections import Counter, defaultdict
import json
import re

from rdflib import RDF, URIRef

from .v5 import OW, PreviewBuilder, digest, write

METHOD, INFORMER, INTERPRETS, INTERPRETATION = '418775008', '419066007', '363714003', '363713009'
OBSERVABLE, CLINICAL_OBSERVABLE = '363787002', '363788007'
PHYSICAL_METHOD_ROOTS = {'37931006','113011001','75180006','32750006'}
AXES = {'363698007':'Location', '246112005':'Severity', '263502005':'Course', '272741003':'Laterality',
        '116676008':'SourceAttribute116676008', '246454002':'SourceAttribute246454002'}
OBSERVABLE_METADATA = {'370130000','370132008','370134009','246501002','246514001','704319004',
                       '704327008','704326004','718497002','246093002','424226004'}


def finding_uri(cid):
    return str(OW)+'ExamFindingSnomedCT'+cid


def observable_uri(cid):
    return str(OW)+'ObservableSnomedCT'+cid


def discover(database, terminology):
    from .source_projection import INFERRED
    clinical = terminology.findings - terminology.diseases
    observables = terminology.descendants({CLINICAL_OBSERVABLE})
    history = terminology.descendants({'84100007'})
    physical = terminology.descendants(PHYSICAL_METHOD_ROOTS)
    laboratory = terminology.descendants({'108252007','363679005','117259009'})
    relations = defaultdict(list)
    for raw in database.connection.execute("""SELECT id,source_id,destination_id,type_id,relationship_group,row_id,concrete_value
        FROM rf2_components WHERE kind='relationship' AND active='1' AND characteristic=? ORDER BY id""",(INFERRED,)):
        if raw['source_id'] in clinical or raw['source_id'] in observables:
            relations[raw['source_id']].append(dict(raw))
    candidates, excluded = {}, Counter()
    for cid in sorted(clinical):
        members = relations[cid]
        methods = [row for row in members if row['type_id']==METHOD]
        provider = [row for row in members if row['type_id']==INFORMER]
        measured = [row for row in members if row['type_id']==INTERPRETS and row['destination_id'] in observables]
        morphology = [row for row in members if row['type_id']=='116676008']
        sites = [row for row in members if row['type_id']=='363698007']
        direct = [row for row in methods if row['destination_id'] in physical]
        report_only = any(row['destination_id'] in history for row in methods)
        test_only = any(row['destination_id'] in laboratory for row in methods)
        if report_only or test_only:
            excluded['patient_history_method' if report_only else 'laboratory_or_imaging_method'] += 1
            continue
        if not (direct or measured or (morphology and sites) or cid in terminology.signs):
            excluded['no_examination_or_observation_role_evidence'] += 1
            continue
        basis = 'explicit_physical_finding_method' if direct else 'interpreted_clinical_observable' if measured else \
                'morphologic_finding_with_site' if morphology and sites else 'source_sign_hierarchy'
        proof = direct + measured + morphology + sites + provider
        candidates[cid] = {'basis':basis, 'methods':direct, 'informer':provider,
            'acquisition':'physical_exam_evidenced' if direct else 'acquisition_unresolved',
            'source_refs':['rf2:concept:'+cid]+['rf2:'+row['id'] for row in proof]}
    return candidates, observables, relations, dict(excluded)


def project(database, terminology, runtime):
    from .source_projection import Normalizer
    from submission.knowledge.conditions import ScoringPolicy
    candidates, observables, relations, excluded = discover(database, terminology)
    builder = PreviewBuilder()
    bindings, proofs, metadata, unresolved_groups = [], defaultdict(set), {}, []
    def concept(cid, kind, uri, refs, role):
        label = terminology.fsns.get(cid,cid).rsplit(' (',1)[0]
        builder.concept(uri,kind,label,snomed_id=cid,source_refs=refs)
        builder.registry[uri]['source_role'] = role
        return uri
    reported_ids = {entry.get('snomed_id') for entry in runtime.registry.values() if entry['kind']=='Symptom'}
    for cid, record in candidates.items():
        uri = concept(cid,'ExamFinding',finding_uri(cid),record['source_refs'],record['basis'])
        builder.registry[uri]['acquisition'] = record['acquisition']
        builder.registry[uri]['patient_report_role'] = cid in reported_ids
        builder.registry[uri]['execution_status'] = 'reviewed_request_text_missing' if record['methods'] else 'detection_method_missing'
        for row in record['methods']:
            method = concept(row['destination_id'],'ExamMethod',str(OW)+'ExamMethodSnomedCT'+row['destination_id'],
                             ['rf2:'+row['id']], 'exact_finding_method_pending_request_wording')
            triple = (URIRef(uri),OW.detectedBy,URIRef(method))
            builder.vocabulary.add(triple)
            proofs[triple].add('rf2:'+row['id'])
    observable_users = defaultdict(list)
    for cid in candidates:
        for row in relations[cid]:
            if row['type_id']==INTERPRETS and row['destination_id'] in observables:
                observable_users[row['destination_id']].append(row)
    # Keep the supplied clinical observation axes across domains, including primitive axes with no numeric definition.
    for cid in sorted(observables):
        refs = ['rf2:concept:'+cid]+['rf2:'+row['id'] for row in observable_users[cid]]
        concept(cid,'FindingAttribute',observable_uri(cid),refs,'clinical_observable_comparison_dimension')
        metadata[cid] = {'relationships':[row['id'] for row in relations[cid] if row['type_id'] in OBSERVABLE_METADATA],
                        'units_specified':any(row['type_id']=='246514001' for row in relations[cid]),
                        'numeric_limits':'not_inferred', 'acquisition':'source_dependent'}
    for cid in sorted(candidates):
        target = finding_uri(cid)
        groups = defaultdict(list)
        for row in relations[cid]:
            groups[row['relationship_group']].append(row)
            if row['type_id'] in AXES and row['destination_id'] and terminology.active(row['destination_id']):
                axis_id = row['type_id']
                attribute = str(OW[AXES[axis_id]])
                canonical = axis_id not in {'116676008','246454002'}
                if canonical:
                    builder.concept(attribute,'FindingAttribute',AXES[axis_id],source_refs=['rf2:'+row['id']])
                else:
                    concept(axis_id,'FindingAttribute',attribute,['rf2:'+row['id']],'source_defining_attribute')
                value = concept(row['destination_id'],'AttributeValue',str(OW)+'SnomedCT'+row['destination_id'],
                                ['rf2:'+row['id']], 'exact_source_attribute_value')
                bindings.append({'target':target,'attribute':attribute,'value':value,'group':row['relationship_group'],
                                 'source_refs':['rf2:'+row['id']],'role':'defining_attribute'})
        for group, members in groups.items():
            interpreted = [row for row in members if row['type_id']==INTERPRETS and row['destination_id'] in observables]
            values = [row for row in members if row['type_id']==INTERPRETATION]
            for row in interpreted:
                attribute = observable_uri(row['destination_id'])
                triple = (URIRef(target),OW.hasAttribute,URIRef(attribute))
                builder.vocabulary.add(triple)
                proofs[triple].add('rf2:'+row['id'])
            if len(interpreted)==1 and len(values)==1 and terminology.active(values[0]['destination_id']):
                row, value_row = interpreted[0], values[0]
                value = concept(value_row['destination_id'],'AttributeValue',str(OW)+'SnomedCT'+value_row['destination_id'],
                    ['rf2:'+value_row['id']],'same_group_interpretation_value')
                bindings.append({'target':target,'attribute':observable_uri(row['destination_id']),'value':value,'group':group,
                    'source_refs':['rf2:'+row['id'],'rf2:'+value_row['id']],'role':'same_group_observable_interpretation'})
            elif values:
                unresolved_groups.append({'target':target,'group':group,
                    'relationship_ids':[row['id'] for row in interpreted+values],
                    'reason':'interpretation_pair_not_unique_in_same_group'})
    for binding in bindings:
        for triple in ((URIRef(binding['target']),OW.hasAttribute,URIRef(binding['attribute'])),
                       (URIRef(binding['attribute']),OW.canHaveValue,URIRef(binding['value']))):
            builder.vocabulary.add(triple)
            proofs[triple].update(binding['source_refs'])
    conditions = {row['snomed_id']:(rid,row) for rid,_,row in database.bodhi_rows('nodes_condition.csv')}
    symptoms = {row['uuid']:(rid,row) for rid,_,row in database.bodhi_rows('nodes_symptom.csv')}
    normalizer = Normalizer(builder)
    policy = ScoringPolicy.load_default()
    variants, variant_status = {}, Counter()
    for uuid,(rid,row) in symptoms.items():
        cid = row['root_snomed_id']
        if cid not in candidates:
            continue
        features, errors = [], []
        for n in range(1,4):
            axis, raw = row[f'relation{n}_type'],row[f'child{n}_name']
            if not axis and not raw:
                continue
            normalizer.source_refs = [f'source_row:{rid}:relation{n}_type:child{n}_name']
            try:
                if not axis or not raw:
                    raise ValueError('incomplete_qualifier')
                features.append(normalizer.qualifier(cid,axis,raw))
            except ValueError as error:
                errors.append(str(error))
        if errors:
            variant_status.update(errors)
        else:
            variants[uuid] = builder.pattern(finding_uri(cid),features)
            variant_status['complete_source_variant'] += 1
    for rid,line,row in database.bodhi_rows('edges_present_in.csv'):
        uuid,disease_id = row['symptom_uuid'],row['condition_snomed_id']
        condition = conditions.get(disease_id)
        if uuid not in variants or not condition or disease_id not in terminology.diseases:
            continue
        raw = condition[1]
        if (raw['type_condition']=='medical_history' or raw['concept_type']!='Disorder'
                or re.match(r'^(h/o|fh)\b',raw['name'],re.I)):
            continue
        if (row['likelihood_condition_given_symptom'].casefold() not in policy.labels
                or row['likelihood_symptom_given_condition'].casefold() not in policy.labels
                or row['strong_predictor'] not in {'','0','1'}):
            variant_status['source_association_label_unresolved'] += 1
            continue
        disease = concept(disease_id,'Disease',str(OW)+'SnomedCT'+disease_id,
            [f'source_row:{condition[0]}:snomed_id'],'BODHI_current_disorder')
        builder.association(disease,variants[uuid],source_ref=f'source_row:{rid}:examination_variant',
            relation_basis='bodhi_present_in',predictiveness=row['likelihood_condition_given_symptom'].casefold(),
            typicality=row['likelihood_symptom_given_condition'].casefold(),
            strong_predictor=None if row['strong_predictor']=='' else row['strong_predictor']=='1',
            raw={'edge_row_id':rid,'symptom_row_id':symptoms[uuid][0],'condition_row_id':condition[0],
                 'acquisition_role':'alternative_source_channel_not_additive_runtime_support'})
    # Exact RF2 associations retain the complete finding concept as target; no ancestor decomposition or numeric thresholds.
    for cid in sorted(candidates):
        for row in relations[cid]:
            if row['type_id'] not in {'42752001','47429007'} or row['destination_id'] not in terminology.diseases:
                continue
            disease_id = row['destination_id']
            disease = concept(disease_id,'Disease',str(OW)+'SnomedCT'+disease_id,['rf2:'+row['id']],'exact_RF2_disorder_link')
            pattern = builder.pattern(finding_uri(cid),[])
            builder.association(disease,pattern,source_ref='rf2:'+row['id'],
                relation_basis='due_to' if row['type_id']=='42752001' else 'associated_with',
                raw={'source_concept_id':cid,'relationship_id':row['id'],
                     'identity_scope':'exact_precoordinated_finding_not_generalized',
                     'definition_relationship_ids':[member['id'] for member in relations[cid]],
                     'runtime_status':'source_candidate_only'})
    for association in builder.conflicts:
        builder.graph.remove((None,OW.hasAssociation,URIRef(association)))
        builder.graph.remove((URIRef(association),None,None))
        builder.selected.pop(association,None)
    active_patterns = set(builder.graph.objects(None,OW.pattern))
    for pattern in list(builder.graph.subjects(RDF.type,OW.ClinicalPattern)):
        if pattern not in active_patterns:
            for feature in list(builder.graph.objects(pattern,OW.hasFeature)):
                builder.graph.remove((feature,None,None))
            builder.graph.remove((pattern,None,None))
    expected = set(builder.graph.objects(None,OW.expected))
    for node in list(builder.graph.subjects(RDF.type,OW.ExpectedValue)):
        if node not in expected:
            builder.graph.remove((node,None,None))
    return builder, proofs, {'candidates':candidates,'bindings':bindings,'observable_metadata':metadata,
        'excluded':excluded,'variant_status':dict(variant_status),'unresolved_groups':unresolved_groups}


def coverage(database, terminology, source, details, output):
    candidates = details['candidates']
    by_target = defaultdict(set)
    for pattern in source.graph.subjects(RDF.type,OW.ClinicalPattern):
        by_target[str(source.graph.value(pattern,OW.targets))].add(str(pattern))
    disease_targets = defaultdict(set)
    for disease,association in source.graph.subject_objects(OW.hasAssociation):
        pattern = source.graph.value(association,OW.pattern)
        disease_targets[str(disease).removeprefix(str(OW)+'SnomedCT')].add(str(source.graph.value(pattern,OW.targets)))
    specialties = {}
    diseases = defaultdict(set)
    for _,_,row in database.bodhi_rows('edges_treated_by.csv'):
        diseases[row['speciality_id']].add(row['condition_snomed_id'])
    for row_id,_,row in database.bodhi_rows('nodes_speciality.csv'):
        targets = set().union(*(disease_targets[cid] for cid in diseases[row['id']]))
        ids = {uri.removeprefix(str(OW)+'ExamFindingSnomedCT') for uri in targets}
        bindings = [binding for binding in details['bindings'] if binding['target'] in targets]
        specialties[row['id']] = {'name':row['name'],'source_row_id':row_id,'source_diseases':len(diseases[row['id']]),
            'source_exam_findings':len(ids),'attributes':len({binding['attribute'] for binding in bindings}),
            'values':len({binding['value'] for binding in bindings}),
            'source_patterns':len(set().union(*(by_target[uri] for uri in targets))),
            'findings_with_method':sum(bool(candidates[cid]['methods']) for cid in ids),
            'executable_exam_requests':0,'gap':'reviewed_request_wording_and_runtime_admission_required' if ids else 'no_complete_source_examination_association'}
    branches = {}
    for root in sorted(terminology.children.get(CLINICAL_OBSERVABLE,())):
        axes = terminology.descendants({root}) & details['observable_metadata'].keys()
        axis_uris = {observable_uri(cid) for cid in axes}
        linked = {str(target) for axis in axis_uris for target in source.vocabulary.subjects(OW.hasAttribute,URIRef(axis))}
        branches[root] = {'label':terminology.fsns[root],'comparison_dimensions':len(axes),'linked_findings':len(linked),
            'findings_with_method':sum(bool(candidates[uri.removeprefix(str(OW)+'ExamFindingSnomedCT')]['methods']) for uri in linked),
            'clinical_sufficiency':'not_assessed'}
    result = {'discovery_rules':dict(Counter(record['basis'] for record in candidates.values())),
        'exam_findings':len(candidates),'finding_attributes':sum(entry['kind']=='FindingAttribute' for entry in source.registry.values()),
        'method_links':len(list(source.vocabulary.triples((None,OW.detectedBy,None)))),
        'source_patterns':len(by_target) and sum(len(values) for values in by_target.values()),
        'source_associations':len(source.selected),'specialties':specialties,'observable_domains':branches,
        'excluded':details['excluded'],'variant_status':details['variant_status'],
        'unresolved_interpretation_groups':len(details['unresolved_groups']),
        'numeric_thresholds_inferred':0,'executable_exam_requests':0,'runtime_admission':'not_run',
        'acquisition_warning':'Source channels are alternatives; do not sum duplicate clinical support across roles'}
    write(output/'finding-coverage.json',result)
    write(output/'observable-metadata.json',details['observable_metadata'])
    write(output/'finding-bindings.json',details['bindings'])
    write(output/'unresolved-finding-groups.json',details['unresolved_groups'])
    return result
