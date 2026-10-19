"""Compile the maintained synthetic workflow vocabulary into a temporary bundle."""
import argparse
import shutil
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'submission'),str(ROOT/'Extraction')]
import fixtures as f
from ontoward_extraction.models import KINDS
from ontoward_extraction.compile import compile_bundle
from rdflib import RDF, SKOS


def stage(destination):
    destination=Path(destination)
    if destination.exists(): raise ValueError('Fixture destination must be fresh')
    shutil.copytree(ROOT/'submission',destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    knowledge=f.knowledge();graph=knowledge._graph;nodes=[];relations=[]
    for kind in KINDS:
        for subject in graph.subjects(RDF.type,f.OW[kind]):
            ident=str(subject);methods=knowledge.get_exam_methods(ident) if kind=='ExamFinding' else []
            nodes.append(dict(id=ident,kind=kind,name='Synthetic examination' if kind=='ExamMethod' else knowledge.term(ident),
                korean='가상진찰' if kind=='ExamMethod' else knowledge.label(ident),
                aliases=[str(value) for value in graph.objects(subject,SKOS.altLabel)],
                attributes=knowledge.get_symptom_attributes(ident),values=knowledge.get_attribute_values(ident),
                systems=knowledge.get_symptom_systems(ident),context_type=knowledge.get_context_type(ident) if kind=='ContextFactor' else None,
                exam_method=methods[0]['id'] if methods else None,
                exam_text=str(next(iter(graph.objects(subject,f.OW.examRequestText)))) if kind=='ExamMethod' else None,
                question=knowledge.questions[ident].model_dump() if ident in knowledge.questions else None,
                attribute_role=knowledge.attribute_roles[ident].model_dump() if ident in knowledge.attribute_roles else None))
    for profiles in knowledge._disease_profiles.values():
        for profile in profiles:
            relations.append(dict(disease_id=profile.disease_id,target_id=profile.target,
                target_scope=profile.target_scope.model_dump(),applicability=[c.model_dump() for c in profile.applicability],effect=profile.effect,
                features=[dict(status=feature.status,attribute=feature.attribute,
                    expected=feature.expected.model_dump() if feature.expected else None) for feature in knowledge.get_pattern_features(profile.id)]))
    return compile_bundle(destination/'knowledge','d49synthetic',nodes,relations)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path);args=parser.parse_args()
    print(stage(args.destination))
