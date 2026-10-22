"""Evidence-backed question suppression; never assert a fact or graph match."""
from dataclasses import dataclass, field
import hashlib
import json

from ..state.models import QuestionCoverage
from .limits import LIMITS


def signature(value):
    return hashlib.sha256(json.dumps(value.model_dump(mode='json'), ensure_ascii=False,
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def key(question):
    slot = question.category or '' if question.purpose in {'intake', 'history'} else ''
    return (*question.semantic_key(), slot)


def status(state, question_key):
    ident = '|'.join(question_key)
    record = state.interview.question_coverage.get(ident)
    if record is None:
        return None
    current = {fact.id: fact for fact in state.case.current_facts()}
    answers = {answer.source_ref: answer for answer in state.interview.answers if answer.source_ref}
    valid = all(ident in current and current[ident].status in {'present', 'absent'}
                and signature(current[ident]) == digest for ident, digest in record.fact_signatures.items())
    valid &= all(ident in answers and signature(answers[ident]) == digest
                 and not any(f.source_ref == ident for f in state.case.facts.values())
                 for ident, digest in record.answer_signatures.items())
    if record.outcome == 'asked_unknown':
        valid &= record.revision == state.case.revision
    if not valid:
        state.interview.question_coverage.pop(ident, None)
        return None
    return record.outcome


def covered(state, question):
    return status(state, key(question)) is not None


def exact_unknown(answer, case, config):
    raw = answer.response or {}
    text = raw.get('content')
    return (answer.outcome == 'unknown' and not answer.reason and not answer.fact_ids
        and bool(answer.source_ref) and len(answer.key) == 8 and answer.key[0] == 'SAY'
        and raw.get('status') == 'OK' and not raw.get('error')
        and isinstance(text, str) and type(answer.turn) is int and 1 <= answer.turn <= LIMITS.turns
        and type(raw.get('turn')) is int and raw['turn'] == answer.turn
        and type(raw.get('turns_remaining')) is int
        and raw['turns_remaining'] == LIMITS.turns - answer.turn
        and not any(f.source_ref == answer.source_ref for f in case.facts.values())
        and text.strip().rstrip(config.texts.reply_trailing_punctuation) in config.texts.unknown_replies)


@dataclass
class CoverageWork:
    questions: dict = field(default_factory=dict)
    fact_refs: dict = field(default_factory=dict)
    answer_refs: dict = field(default_factory=dict)
    proposals: list = field(default_factory=list)


def question_record(ref, question):
    return dict(ref=ref, kind=question.kind, target=question.target, attribute=question.attribute,
        text=question.text, purpose=question.purpose, category=question.category,
        answer_type=question.answer_type, subject=question.subject, subject_member=question.subject_member,
        time_context=question.time_context, observation_id=question.observation_id, episode_id=question.episode_id)


def unknown_answers(state, config):
    return {f'a_{index}': answer for index, answer in enumerate(state.interview.answers, 1)
            if exact_unknown(answer, state.case, config)}


def answer_record(ref, answer):
    kind, target, attribute, subject, member, timing, observation, episode = answer.key
    return dict(ref=ref, kind=kind, target=target, attribute=attribute or None, outcome='unknown',
        subject=subject, subject_member=member or None, time_context=timing,
        observation_id=observation or None, episode_id=episode or None)


def same_scope(question, subject, member, timing, observation, episode, knowledge):
    if (question.subject, question.subject_member, question.time_context) != (subject, member, timing):
        return False
    if question.episode_id is not None:
        return episode == question.episode_id and (observation == question.observation_id or bool(episode))
    target = knowledge.term_id(question.target, 'ContextFactor') if question.target else None
    # A general Context question has no requested event identity. No source identity is merged.
    return bool(target) or (question.observation_id is not None and observation == question.observation_id)


def accept(state, work, knowledge, config, statement_facts=None):
    """Ignore optional bad entries independently of the main response contract."""
    accepted = set()
    current = {fact.id: fact for fact in state.case.current_facts()}
    statement_facts = statement_facts or {}
    for proposal in work.proposals:
        if (not isinstance(proposal, dict) or set(proposal) - {
                'question_ref', 'outcome', 'fact_refs', 'answer_refs', 'statement_indices'}):
            continue
        ref = proposal.get('question_ref')
        question = work.questions.get(ref) if isinstance(ref, str) else None
        if question is None or question.purpose in {'chief', 'clarification', 'open_inquiry', 'history', 'education'}:
            continue
        if question.purpose == 'intake' and not question.target:
            chief = state.case.collection_chief()
            if chief is None:
                continue
            question = question.model_copy(update=dict(target=chief.target, subject=chief.subject,
                subject_member=chief.subject_member, time_context=chief.time_context,
                observation_id=chief.observation_id, episode_id=chief.episode_id))
        outcome = proposal.get('outcome')
        fact_refs, answer_refs, indices = (proposal.get(name, []) for name in
                                         ('fact_refs', 'answer_refs', 'statement_indices'))
        if (not all(isinstance(rows, list) for rows in (fact_refs, answer_refs, indices))
                or not all(isinstance(item, str) and item in work.fact_refs for item in fact_refs)
                or not all(isinstance(item, str) and item in work.answer_refs for item in answer_refs)
                or not all(type(index) is int and index in statement_facts and statement_facts[index] for index in indices)):
            continue
        fact_ids = list(dict.fromkeys([*(work.fact_refs[ref] for ref in fact_refs),
                                      *(ident for index in indices for ident in statement_facts[index])]))
        facts = [current[ident] for ident in fact_ids if ident in current]
        answers = [work.answer_refs[ref] for ref in answer_refs]
        if outcome == 'known':
            if not facts or len(facts) != len(fact_ids) or answers:
                continue
            if any(f.status not in {'present', 'absent'} or f.polarity_scope != 'general' or f.context_key
                   or not same_scope(question, f.subject, f.subject_member, f.time_context,
                                     f.observation_id, f.episode_id, knowledge)
                   or (f.acquisition == 'EXAM' or f.source_ref == 'initial:vital_signs') != (question.kind == 'EXAM')
                   for f in facts):
                continue
            if question.purpose == 'intake' and any(f.category != question.category for f in facts):
                continue
            if question.attribute and not any(f.kind in {'attribute', 'note'} for f in facts):
                continue
            if question.answer_type in {'quantity', 'duration'} and not any(f.measurement for f in facts):
                continue
        elif outcome == 'asked_unknown':
            if facts or not answers or question.kind != 'SAY' or any(
                    not exact_unknown(a, state.case, config) or not same_scope(question,
                        a.key[3], a.key[4] or None, a.key[5], a.key[6] or None, a.key[7] or None, knowledge)
                    for a in answers):
                continue
            if question.purpose == 'intake' and any(a.category != question.category for a in answers):
                continue
        else:
            continue
        state.interview.question_coverage['|'.join(key(question))] = QuestionCoverage(outcome=outcome,
            fact_signatures={f.id: signature(f) for f in facts},
            answer_signatures={a.source_ref: signature(a) for a in answers}, revision=state.case.revision)
        accepted.add(ref)
    return accepted
