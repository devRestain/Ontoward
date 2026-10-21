from pathlib import Path
from rdflib import RDF
from knowledge.graph import ClinicalKnowledge, OW


def verify(manifest, require_coverage=True):
    knowledge=ClinicalKnowledge.load(Path(manifest))
    knowledge.validate_vocabulary_endpoints()
    diseases={str(node) for node in knowledge._graph.subjects(RDF.type,OW.Disease)}
    if not diseases:
        raise ValueError('bundle_requires_diseases')
    gaps=[]
    for disease in sorted(diseases):
        profiles=knowledge.get_disease_patterns(disease)
        positive=[p for p in profiles if p.effect in {'support','strong_support'}]
        if not positive: gaps.append({'disease_id':disease,'missing':'positive_entry'})
        if not any(knowledge.question_contract(p.target) and knowledge.question_contract(p.target).interviewable
            or knowledge.has_type(p.target,'ExamFinding') and knowledge.get_exam_methods(p.target) for p in positive):
            gaps.append({'disease_id':disease,'missing':'executable_question'})
    for target in knowledge._graph.subjects(RDF.type,OW.Symptom):
        if knowledge.question_contract(str(target)) is None: gaps.append({'target_id':str(target),'missing':'presence_question'})
    if require_coverage and gaps:
        raise ValueError('incomplete_generation_contract:'+str(gaps))
    return {'status':'pass' if not gaps else 'incomplete','diseases':len(diseases),'gaps':gaps}
