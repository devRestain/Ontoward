import hashlib
import json
import os
from pathlib import Path

from rdflib import Graph, Literal, RDF, RDFS, SKOS, URIRef
from knowledge.graph import ClinicalKnowledge, OW
from .models import Relation, Concept, ValuePath, CONTRACT, canonical, identifier
from .normalize import concepts as normalize_concepts, relation as normalize_relation


def compile_bundle(directory, build_id, raw_concepts, raw_relations, value_paths=(), guidelines=None, schema_path=None,
                   *, preserve_ids=False, question_overrides=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if preserve_ids:
        # Offline maintenance starts with registered runtime identities, including
        # finding-specific ExamMethods and attribute-owned values with equal names.
        nodes=[Concept.model_validate(row).model_dump() for row in raw_concepts]
        if len({node['id'] for node in nodes}) != len(nodes):
            raise ValueError('duplicate_registered_identity')
        mapping={node['id']:node['id'] for node in nodes}
        values={(value,node['id']):value for node in nodes if node['kind']=='FindingAttribute' for value in node['values']}
    else:
        nodes,mapping,values=normalize_concepts(raw_concepts)
    vocabulary,clinical=Graph(),Graph()
    questions,roles={},{}
    by_id={node['id']:node for node in nodes}
    for node in list(nodes):
        if node['kind']!='ExamFinding':continue
        method=by_id.get(node['exam_method'])
        if method and method['kind']=='ExamMethod' and not method['exam_text'] and node['exam_text']:
            # Keep the supplied finding-specific action rather than assigning one finding's text to a shared method.
            ident=identifier('ExamMethod',[method['id'],node['id'],node['exam_text']])
            executable=dict(method,id=ident,exam_text=node['exam_text'])
            nodes.append(executable);by_id[ident]=executable;node['exam_method']=ident
    for raw in nodes:
        node=Concept.model_validate(raw);subject=URIRef(node.id)
        vocabulary.add((subject,RDF.type,OW[node.kind]))
        vocabulary.add((subject,RDFS.label,Literal(node.name,lang='en')))
        vocabulary.add((subject,RDFS.label,Literal(node.korean,lang='ko')))
        for alias in node.aliases:
            vocabulary.add((subject,SKOS.altLabel,Literal(alias)))
        for predicate,ids in ((OW.hasAttribute,node.attributes if node.kind in {'Symptom','ExamFinding'} else []),
                (OW.canHaveValue,node.values if node.kind=='FindingAttribute' else []),
                (OW.inSystem,node.systems if node.kind in {'Symptom','ExamFinding'} else [])):
            for ident in ids: vocabulary.add((subject,predicate,URIRef(ident)))
        if node.context_type: vocabulary.add((subject,OW.contextType,Literal(node.context_type)))
        if node.exam_method: vocabulary.add((subject,OW.detectedBy,URIRef(node.exam_method)))
        if node.exam_text: vocabulary.add((subject,OW.examRequestText,Literal(node.exam_text)))
        if node.question: questions[node.id]=node.question.model_dump()
        elif node.kind=='ExamFinding' and node.exam_method in by_id:
            from knowledge.conditions import QuestionTemplate
            if not by_id[node.exam_method]['exam_text']:
                raise ValueError('missing_executable_exam_text:'+canonical(dict(finding=node.model_dump(),method=by_id[node.exam_method])))
            questions[node.id]=QuestionTemplate(text=by_id[node.exam_method]['exam_text'],time_context='current').model_dump()
        if node.attribute_role: roles[node.id]=node.attribute_role.model_dump()
    seen={}
    counts={key:0 for key in ('support','strong_support','against','strong_against','neutral')}
    for raw in raw_relations:
        row=Relation.model_validate(normalize_relation(raw,mapping,values))
        key=row.meaning()
        if key in seen:
            if seen[key]!=row.effect: raise ValueError('conflicting_effect_requires_final_classification')
            continue
        seen[key]=row.effect;counts[row.effect]+=1
        if row.effect=='neutral': continue
        features=sorted([feature.model_dump(exclude_none=True) for feature in row.features],key=canonical)
        pattern=URIRef(identifier('Pattern',[row.target_id,features]))
        association=URIRef(identifier('Association',key))
        clinical.add((URIRef(row.disease_id),OW.hasAssociation,association))
        for predicate,value in ((RDF.type,OW.DiseasePatternAssociation),(OW.pattern,pattern),
            (OW.targetScope,Literal(canonical(row.target_scope.model_dump()),datatype=RDF.JSON)),
            (OW.applicability,Literal(canonical(sorted([c.model_dump() for c in row.applicability],key=canonical)),datatype=RDF.JSON)),
            (OW.diagnosticEffect,Literal(row.effect))):
            clinical.add((association,predicate,value))
        clinical.add((pattern,RDF.type,OW.ClinicalPattern));clinical.add((pattern,OW.targets,URIRef(row.target_id)))
        for value in features:
            feature=URIRef(identifier('Feature',[str(pattern),value]))
            clinical.add((pattern,OW.hasFeature,feature));clinical.add((feature,RDF.type,OW.ClinicalFeature))
            if value.get('status'): clinical.add((feature,OW.expectedStatus,Literal(value['status'])))
            if value.get('attribute'):
                expected=URIRef(identifier('Expected',value['expected']))
                clinical.add((feature,OW.onAttribute,URIRef(value['attribute'])))
                clinical.add((feature,OW.expected,expected));clinical.add((expected,RDF.type,OW.ExpectedValue))
                clinical.add((expected,OW.valueJSON,Literal(canonical(value['expected']),datatype=RDF.JSON)))
    for raw in value_paths:
        row=ValuePath.model_validate(raw)
        observed,expected=mapping.get(row.observed,row.observed),mapping.get(row.expected,row.expected)
        path=URIRef(identifier('ValueMatch',[observed,expected,row.relation]))
        for predicate,value in ((RDF.type,OW.ValueMatch),(OW.observedConcept,URIRef(observed)),
            (OW.expectedConcept,URIRef(expected)),(OW.relationKind,Literal(row.relation))):
            vocabulary.add((path,predicate,value))
    from knowledge import graph as graph_module
    schema_path=Path(schema_path or Path(graph_module.__file__).with_name('schema.ttl'))
    (directory/'schema.ttl').write_bytes(schema_path.read_bytes())
    for name,graph in [('vocabulary.ttl',vocabulary),('clinical.ttl',clinical)]:
        (directory/name).write_text('\n'.join(sorted(graph.serialize(format='nt').splitlines()))+'\n')
    questions.update(question_overrides or {})
    (directory/'questions.ko.json').write_text(canonical({'questions':questions,'attribute_roles':roles}))
    diseases={node['id'] for node in nodes if node['kind']=='Disease'}
    index={'version':'guideline-runtime-1','build_id':build_id,'diseases':[
        {'disease_id':ident,'selections':(guidelines or {}).get(ident,[])} for ident in sorted(diseases)]}
    (directory/'guideline-index.json').write_text(canonical(index))
    manifest={'schema_version':'5.0','knowledge_contract':CONTRACT,'build_id':build_id}
    for key,name in [('schema','schema.ttl'),('vocabulary','vocabulary.ttl'),('clinical','clinical.ttl'),
        ('questions','questions.ko.json'),('guidelines','guideline-index.json')]:
        manifest[key]={'path':name,'sha256':hashlib.sha256((directory/name).read_bytes()).hexdigest()}
    temporary=directory/'manifest.json.tmp';temporary.write_text(canonical(manifest));os.replace(temporary,directory/'manifest.json')
    ClinicalKnowledge.load(directory/'manifest.json').validate_vocabulary_endpoints()
    return {'build_id':build_id,'concepts':len(nodes),'effects':counts,'questions':len(questions),'manifest':str(directory/'manifest.json')}
