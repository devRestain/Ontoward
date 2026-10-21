import hashlib
import re

from ..state.models import CaseFact, GraphBinding


def initial_objective(source):
    return source == 'initial:vital_signs'


def objective(acquisition, source):
    return acquisition == 'EXAM' or acquisition == 'initial' and initial_objective(source)


def fact_scope(statement, source, index, question=None, *, case=None, target=None):
    same = (question and (question.subject, question.subject_member) == (statement.subject, statement.subject_member)
            and question.time_context == statement.time_context
            and (not statement.observation_id or statement.observation_id == question.observation_id)
            and (not statement.episode_id or statement.episode_id == question.episode_id)
            and (question.target == target if target else not statement.target_terms or question.target in statement.target_terms))
    observation = statement.observation_id or (question.observation_id if same else None)
    episode = statement.episode_id or (question.episode_id if same else None)
    if case and target and statement.focus == 'attribute' and statement.anchor is None and not observation:
        acquisition = question.kind if question else 'initial'
        anchors = {(f.observation_id, f.episode_id) for f in case.current_facts()
            if f.target == target and f.kind in {'symptom', 'finding'}
            and (f.subject, f.subject_member, f.time_context) ==
                (statement.subject, statement.subject_member, statement.time_context)
            and (episode is None or f.episode_id == episode)
            and objective(f.acquisition, f.source_ref) == objective(acquisition, source)}
        if len(anchors) == 1:
            observation, episode = next(iter(anchors))
    occurrence = statement.anchor if statement.anchor is not None else index
    observation = observation or 'observation:' + hashlib.sha256(f'{source}:{occurrence}'.encode()).hexdigest()[:24]
    return observation, episode or observation


def note_fact(statement, source, index, turn, question=None):
    category = statement.record_category or (question.category if question else None) or 'other'
    value = statement.note_value or '; '.join(dict.fromkeys(statement.target_terms + statement.attribute_terms + statement.value_terms))
    if not value and statement.measurement is None:
        return None
    if value and (not re.search('[A-Za-z]', value) or re.search('[가-힣]', value)
                                  or value.startswith(('urn:', 'http://', 'https://'))):
        return None
    acquisition = question.kind if question else 'initial'
    if category == 'objective_observation' and (statement.subject!='patient' or not objective(acquisition, source)):
        return None
    observation, episode = fact_scope(statement, source, index, question)
    return CaseFact(id=f'{source}:note:{index}', category=category, value=value, measurement=statement.measurement,
        status=statement.assertion, subject=statement.subject, subject_member=statement.subject_member,
        reported_by=statement.reported_by, time_context=statement.time_context,
        observation_id=observation, episode_id=episode, source_ref=source, turn=turn,
        acquisition=acquisition, polarity_scope=statement.polarity_scope)


def make_fact(case, knowledge, statement, decoded, *, source, index, offset, turn, question, broader=False):
    target, attribute, values, measurement, status = decoded
    target_id = next((ident for kind in ('Symptom', 'ContextFactor', 'ExamFinding')
                      if (ident := knowledge.term_id(target, kind))), None)
    kind = 'attribute' if attribute else 'context' if knowledge.has_type(target_id, 'ContextFactor') else (
        'finding' if knowledge.has_type(target_id, 'ExamFinding') else 'symptom')
    contract = knowledge.questions.get(target_id)
    if contract and not contract.interviewable and status == 'present':
        names = [knowledge.term(target_id), *next(iter(knowledge.concepts([target_id])), {}).get('aliases', [])]
        quote = knowledge.normalize_alias(statement.quote)
        if not any(knowledge.normalize_alias(name) in quote for name in names if name):
            raise ValueError('Unqualified wording cannot establish a diagnostic composite')
    if kind == 'context' and (knowledge.get_context_type(target_id) == 'family_history') != (statement.subject == 'family'):
        raise ValueError('Context subject does not match its meaning')
    same = question and question.target == target and (question.subject, question.subject_member) == (statement.subject, statement.subject_member)
    observation, episode = fact_scope(statement, source, index, question, case=case, target=target)
    role = knowledge.attribute_category(knowledge.term_id(attribute, 'FindingAttribute')) if attribute else None
    category = role if role and role != 'other' else statement.record_category or role
    if category is None and question and (same or question.purpose in {'intake', 'history'}):
        category = question.category
    if kind == 'symptom' and status == 'present' and statement.subject == 'patient' and statement.time_context != 'past':
        if not case.chief_fact_id or statement.primary_concern or question and (question.purpose == 'chief' or question.primary_choice):
            category = 'presentation'
    if measurement and measurement.unit.casefold() == 'nrs' and not re.search(r'\bNRS\b',
            statement.quote + ' ' + (question.text if question else ''), re.I):
        raise ValueError('NRS requires an explicit reported or requested scale')
    previous = case.facts.get(statement.correction_id) if statement.correction_id else None
    if statement.correction_id and previous is None:
        raise ValueError('Correction requires an acquired fact')
    acquisition = question.kind if question else 'initial'
    ident = previous.id if previous else f'{source}:fact:{index}:{offset}'
    fact = CaseFact(id=ident, graph_binding=GraphBinding(target=target, attribute=attribute, values=tuple(values),
        kind=kind, method='broader' if broader else 'exact'), measurement=measurement or statement.measurement,
        value=statement.note_value or '', status=status, subject=statement.subject, subject_member=statement.subject_member,
        reported_by=statement.reported_by, time_context=statement.time_context,
        observation_id=observation, episode_id=episode, category=category,
        acquisition=acquisition, source_ref=source, turn=turn, polarity_scope=statement.polarity_scope)
    resolved = case.facts.get(question.clarifies_id) if question and question.clarifies_id else None
    if resolved and resolved.kind == fact.kind and resolved.key() == fact.key():
        fact = fact.model_copy(update={'resolves':(resolved.id,)})
    if previous:
        if (fact.kind, fact.target, fact.attribute, fact.subject, fact.subject_member,
                fact.observation_id, fact.episode_id, fact.time_context) != (
                previous.kind, previous.target, previous.attribute, previous.subject, previous.subject_member,
                previous.observation_id, previous.episode_id, previous.time_context):
            raise ValueError('Correction must preserve its target subject attribute occurrence and time')
        if previous.acquisition == 'initial' or previous.acquisition != acquisition:
            raise ValueError('Correction must preserve its acquisition channel')
    if knowledge.has_type(target_id, 'ExamFinding') and not objective(acquisition, source):
        raise ValueError('Finding requires an actual examination')
    return fact
