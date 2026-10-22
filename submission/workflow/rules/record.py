"""SOAP classification from accepted facts and actual DD SAY provenance."""
from .collection import CATEGORY_FIELDS
from .dd import received_answers


def dd_ros_facts(case, interview):
    answers = {a.source_ref: a for a in received_answers(interview) if a.key[0] == 'SAY'}
    symptom_targets = {f.target for f in case.facts.values() if f.kind == 'symptom'}
    symptom_categories = {category for category, field in CATEGORY_FIELDS.items() if field == 'S.hpi'} - {
        'patient_context', 'previous_care'}
    symptom_categories.add('review_of_systems')
    result = set()
    for fact in case.facts.values():
        answer = answers.get(fact.source_ref)
        if (not answer or fact.acquisition != 'SAY' or fact.subject != 'patient'
                or fact.context_key or fact.kind == 'context'
                or CATEGORY_FIELDS.get(fact.category) in {'S.pmh', 'S.fh', 'S.sh'}):
            continue
        if (fact.kind == 'symptom' or fact.kind == 'attribute' and (
                fact.target in symptom_targets or fact.category in symptom_categories)
                or fact.kind == 'note' and (fact.category in symptom_categories
                    or fact.category == 'other' and (answer.purpose == 'ros' or answer.key[1] in symptom_targets))):
            result.add(fact.id)
    return result
