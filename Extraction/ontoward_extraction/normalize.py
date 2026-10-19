from .models import Concept, identifier


def concepts(rows):
    raw = [Concept.model_validate(row) for row in rows]
    mapping, by_id = {}, {}
    for node in raw:
        if node.kind != 'AttributeValue':
            mapping[node.id] = identifier(node.kind,node.name.casefold().strip())
    owners = {}
    for node in raw:
        if node.kind == 'FindingAttribute':
            for value in node.values:
                owners.setdefault(value,set()).add(mapping[node.id])
    value_map = {}
    for node in raw:
        if node.kind == 'AttributeValue':
            parents=owners.get(node.id,{None})
            for parent in parents:
                value_map[(node.id,parent)] = identifier(node.kind,[parent,node.name.casefold().strip()])
            if len(parents)==1:
                mapping[node.id]=value_map[(node.id,next(iter(parents)))]
    for node in raw:
        values=node.model_dump()
        values['id']=mapping.get(node.id,node.id)
        values['attributes']=[mapping.get(value,value) for value in node.attributes]
        values['systems']=[mapping.get(value,value) for value in node.systems]
        values['values']=[value_map.get((value,values['id']),mapping.get(value,value)) for value in node.values]
        values['exam_method']=mapping.get(node.exam_method,node.exam_method)
        variants=[values]
        if node.kind=='AttributeValue':
            variants=[dict(values,id=ident) for (old,_),ident in value_map.items() if old==node.id]
        for value in variants:
            previous=by_id.get(value['id'])
            if previous:
                for key in ('aliases','attributes','values','systems'):
                    value[key]=sorted(set(previous[key]+value[key]))
                for key in ('question','attribute_role','context_type','exam_method','exam_text'):
                    value[key]=value[key] or previous[key]
            by_id[value['id']]=value
    return list(by_id.values()),mapping,value_map


def relation(value, mapping, value_map):
    value={**value,'disease_id':mapping.get(value['disease_id'],value['disease_id']),
        'target_id':mapping.get(value['target_id'],value['target_id'])}
    value['applicability']=[dict(item,concept_id=mapping.get(item['concept_id'],item['concept_id'])) for item in value.get('applicability',[])]
    features=[]
    for item in value['features']:
        item=dict(item)
        if item.get('attribute'):
            attribute=item['attribute']=mapping.get(item['attribute'],item['attribute'])
            expected=dict(item['expected'])
            if expected.get('concept'):
                old=expected['concept'];expected['concept']=value_map.get((old,attribute),mapping.get(old,old))
            expected['concepts']=[value_map.get((old,attribute),mapping.get(old,old)) for old in expected.get('concepts',[])]
            item['expected']=expected
        features.append(item)
    value['features']=features
    return value
