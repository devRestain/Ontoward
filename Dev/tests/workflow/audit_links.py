"""Report vocabulary endpoint violations offline without modifying the bundle."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'submission'))
from rdflib import RDF
from knowledge.graph import ClinicalKnowledge, OW


def audit(knowledge):
    rows, counts = [], Counter()
    for predicate, domain, range_kind in ((OW.hasAttribute, None, 'FindingAttribute'),
                                         (OW.canHaveValue, 'FindingAttribute', 'AttributeValue')):
        for subject, target in sorted(knowledge._graph.subject_objects(predicate), key=lambda edge: tuple(map(str, edge))):
            violations = []
            for role, ident, expected in (('domain', subject, domain), ('range', target, range_kind)):
                if expected and not knowledge.has_type(str(ident), expected):
                    key = str(predicate).removeprefix(str(OW)) + '_' + role
                    counts[key] += 1
                    violations.append(dict(endpoint=role, expected_type=expected))
            if violations:
                rows.append(dict(subject=str(subject), predicate=str(predicate), object=str(target),
                    subject_label=knowledge.term(str(subject)), object_label=knowledge.term(str(target)),
                    subject_types=sorted(str(kind) for kind in knowledge._graph.objects(subject, RDF.type)),
                    object_types=sorted(str(kind) for kind in knowledge._graph.objects(target, RDF.type)),
                    violations=violations))
    return dict(violation_counts=dict(counts), invalid_edges=len(rows), violations=rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[3] / 'submission/knowledge/manifest.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(ClinicalKnowledge.load(args.manifest))
    result['build_id'] = json.loads(args.manifest.read_text())['build_id']
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'violations'}))
