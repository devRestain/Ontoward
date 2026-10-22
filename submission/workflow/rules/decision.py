from dataclasses import dataclass, field
import json
from typing import Literal

from pydantic import StrictStr, model_validator

from .assessment import graph_candidates
from .clinical_wire import compact_clinical_payload
from .dd import requirements
from .limits import LIMITS
from .normalization import strict_json
from ..model_context import fact_record, messages
from ..state.models import Assessment, Model
from ..wire import table_payload
from .coverage import CoverageWork, question_record, unknown_answers


class RankingReply(Model):
    ranked_disease_refs: list[StrictStr]


class NextAction(Model):
    kind: Literal['ask', 'finish_collection']
    question_ref: StrictStr | None = None

    @model_validator(mode='after')
    def question(self):
        if (self.kind == 'ask') != (self.question_ref is not None):
            raise ValueError('Only ask requires a question reference')
        return self


class ActionReply(Model):
    next_action: NextAction


@dataclass
class DecisionWork:
    payload: dict
    refs: dict
    candidates: dict
    options: dict = field(default_factory=dict)
    coverage: CoverageWork = field(default_factory=CoverageWork)


def clinical_messages(config, work):
    route = {'clinical_rank': 'clinical.rank', 'clinical_decision': 'clinical.decision',
             'clinical_action': 'clinical.action'}[work.payload['task']]
    routes = [route, 'session.' + work.payload['stage']]
    if 'validation_error' in work.payload:
        routes.append('clinical.repair')
    return messages(config.prompt(*routes), table_payload(compact_clinical_payload(work.payload),
        ('facts', 'scopes', 'candidates', 'evidence', 'relations', 'questions', 'asked_questions', 'pending_questions')))


def latest_response(state):
    answer = next((row for row in reversed(state.interview.answers)
                   if row.scope != 'Education' and row.source_ref
                   and row.outcome not in {'undelivered', 'delivered'}), None)
    return answer.source_ref if answer else 'entry'


def prepare_decision(state, knowledge, tools, *, mode='decision', closing=False, candidates=None):
    candidates = graph_candidates(state.case, knowledge, state.interview) if candidates is None else candidates
    prior = [knowledge.term_id(e.name, 'Disease') for e in state.case.assessment.differential] if state.case.assessment else []
    protected = [ident for ident in prior if ident in candidates]
    remaining = set(candidates) - set(protected)
    buckets = {}
    for ident in sorted(remaining):
        for route in sorted(candidates[ident].routes):
            buckets.setdefault(route, []).append(ident)
    ordered = list(protected)
    while remaining and any(buckets.values()):
        for bucket in buckets.values():
            if bucket:
                ident = bucket.pop(0)
                if ident in remaining:
                    ordered.append(ident)
                    remaining.remove(ident)
    # Candidate membership is independent of the bounded graph detail tables.
    ordered.extend(sorted(remaining))
    candidates = {ident: candidates[ident] for ident in ordered}
    refs = {ident: f'd_{index}' for index, ident in enumerate(ordered, 1)}
    facts = state.case.current_facts()
    fact_refs = {fact.id: f'f_{index}' for index, fact in enumerate(facts, 1)}
    scopes, scope_refs, observation_refs, episode_refs = {}, {}, {}, {}

    def scope(subject, member, time, observation, episode):
        key = (subject, member, time, observation, episode)
        if key not in scope_refs:
            ident = f's_{len(scope_refs) + 1}'
            scope_refs[key] = ident
            row = dict(subject=subject, time=time)
            if member:
                row['member'] = member
            if observation:
                row['observation'] = observation_refs.setdefault(observation, f'o_{len(observation_refs) + 1}')
            if episode:
                row['episode'] = episode_refs.setdefault(episode, f'episode_{len(episode_refs) + 1}')
            scopes[ident] = row
        return scope_refs[key]

    patient_rows = {}
    for fact in facts:
        row = fact_record(fact)
        for key in ('id', 'subject', 'subject_member', 'time_context', 'observation_id', 'episode_id'):
            row.pop(key, None)
        row['scope'] = scope(fact.subject, fact.subject_member, fact.time_context, fact.observation_id, fact.episode_id)
        patient_rows[fact_refs[fact.id]] = row
    payload = dict(task={'rank': 'clinical_rank', 'action': 'clinical_action', 'decision': 'clinical_decision'}[mode],
        stage=state.interview.current, revision=state.case.revision,
        chief=fact_refs.get(state.case.chief_fact_id),
        facts=patient_rows, scopes=scopes, conditions={}, relations={},
        prior_order=[refs[ident] for ident in protected], required=[],
        resources=dict(turns=tools.budget.action_capacity(state), calls=tools.budget.calls_left(state.session)),
        candidates=[], evidence={}, questions=[],
        input_limits=dict(omitted_question_options=0))
    if state.case.chief_route:
        payload['chief_route'] = dict(target=state.case.chief_route.target, routing_only=True)
    evidence_refs = {}
    condition_refs = {}
    def expected(value):
        if not isinstance(value, dict):
            return value
        if value.get('kind') == 'concept':
            name = knowledge.term(value['concept'])
            return name if value.get('match', 'exact') == 'exact' else {'subsumption': name}
        if value.get('kind') == 'concept_set':
            return {value['selection']: [knowledge.term(v) for v in value['concepts']], 'match': value.get('match','exact')}
        return {key: item for key, item in value.items() if item is not None and item != [] and
                key not in {'concept', 'concepts', 'selection', 'match'} and
                not (key in {'lower_inclusive', 'upper_inclusive'} and item is True)}

    def conditions(rows):
        if not rows:
            return None
        value = [dict(target=c['name'], status=c['status'], subject=c['subject'], member=c.get('subject_member'), time=c['time_context']) for c in rows]
        signature = json.dumps(value, sort_keys=True)
        if signature not in condition_refs:
            ident = f'condition_{len(condition_refs) + 1}'
            condition_refs[signature] = ident
            payload['conditions'][ident] = value
        return condition_refs[signature]

    relation_refs, relation_definitions = {}, {}
    def relation(detail):
        ident = detail['association']
        if ident not in relation_refs:
            row = dict(target=detail['target'], effect=detail['effect'],
                rule_scope=detail['target_scope'],
                full_pattern=[dict(attribute=f['attribute'], expected_status=f['expected_status'],
                                   expected=expected(f['expected'])) for f in detail['features']],
                applicability=conditions(detail['conditions']))
            # Disease associations can carry identical definitions. Share only their
            # wire representation; retain disease membership and scoped fact matches.
            signature = json.dumps(row, sort_keys=True, ensure_ascii=False)
            if signature not in relation_definitions:
                ref = f'r_{len(relation_definitions) + 1}'
                relation_definitions[signature] = ref
                payload['relations'][ref] = row
            relation_refs[ident] = relation_definitions[signature]
        return relation_refs[ident]

    def describe(ref, details):
        graph = ref.graph_ref
        detail = next((d for d in details if d['association'] == (graph.association_id or graph.id)), None)
        row = dict(level=graph.kind, facts=[fact_refs[i] for i in ref.fact_ids])
        if detail:
            row['relation'] = relation(detail)
            feature = next((i for i, f in enumerate(detail['features']) if f['id'] == graph.id), None)
            if graph.kind == 'feature' and feature is not None:
                row['feature'] = feature
            elif getattr(ref, 'reason', None) == 'presence_required':
                row['expects'] = {'presence': 'present'}
            elif graph.kind == 'context':
                row['expects'] = {'presence': next(c['status'] for c in detail['conditions'] if c['concept_id'] == graph.id)}
            elif graph.kind != 'association':
                raise ValueError('evidence_feature_outside_relation')
        if graph.kind == 'context':
            row['context'] = knowledge.term(graph.id)
        if hasattr(ref, 'scope'):
            kind, target, attr, subject, member, timing, observation, episode = ref.scope
            row.update(target=target, attribute=attr or None,
                scope=scope(subject, member or None, timing, observation or None, episode or None), reason=ref.reason)
        row = {key: value for key, value in row.items() if value is not None and value != []}
        signature = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if signature not in evidence_refs:
            ident = f'e_{len(evidence_refs) + 1}'
            evidence_refs[signature] = ident
            payload['evidence'][ident] = row
        return evidence_refs[signature]

    # A current accepted ranking is enough for action selection; no full graph evidence is resent.
    shown = protected if mode == 'action' else ordered
    for ident in shown:
        candidate = candidates[ident]
        row = dict(ref=refs[ident], name=candidate.entry.name)
        if mode != 'action':
            for category in ('supports', 'against', 'unresolved'):
                row[category] = list(dict.fromkeys(describe(ref, candidate.details) for ref in getattr(candidate.entry, category)))
        payload['candidates'].append(row)
    included = set(shown)
    options = tools._options(state, {i: candidates[i] for i in shown}) if mode != 'rank' and not closing else {}
    question_refs = {}
    for spec, diseases in options.values():
        ref = f'q_{len(question_refs) + 1}'
        question = tools._question(spec, '', 0, 0)
        row = dict(ref=ref, kind=question.kind, target=question.target, attribute=question.attribute,
            subject=question.subject, member=question.subject_member, time=question.time_context,
            scope=scope(question.subject, question.subject_member, question.time_context,
                        question.observation_id, question.episode_id),
            expected_by_disease={})
        for disease in sorted(diseases & included):
            entries = []
            for missing in candidates[disease].entry.unresolved:
                if question.semantic_key() not in tools.collection_keys(missing.scope):
                    continue
                graph = missing.graph_ref
                detail = next((d for d in candidates[disease].details if d['association'] == graph.association_id), None)
                feature = next((f for f in detail['features'] if f['id'] == graph.id), None) if detail else None
                if detail and feature:
                    value = dict(relation=relation(detail),
                        feature=next(i for i, f in enumerate(detail['features']) if f['id'] == graph.id))
                else:
                    context_expected = next((c['status'] for c in detail['conditions'] if c['concept_id'] == graph.id), 'present') if detail else 'present'
                    value = dict(expected=context_expected, relation=relation(detail) if detail else None, feature=None)
                if missing.scope != question.semantic_key():
                    value['collection_only'] = True
                if value not in entries:
                    entries.append(value)
            row['expected_by_disease'][refs[disease]] = entries
        payload['questions'].append({key: value for key, value in row.items() if value is not None})
        question_refs[ref] = spec
    coverage = CoverageWork(questions={ref: tools._question(spec, '', 0, 0) for ref, spec in question_refs.items()},
        fact_refs={ref: ident for ident, ref in fact_refs.items()}, answer_refs=unknown_answers(state, tools.config))
    next_stage = {'Initiation': 'ChiefComplaint', 'ChiefComplaint': 'ContextFactor'}.get(state.interview.current)
    if mode == 'rank' and next_stage:
        coverage.questions = {f'p_{index}': question for index, question in enumerate(
            tools.pending_questions(state, stage=next_stage, candidates=candidates), 1)}
        if coverage.questions:
            payload['pending_questions'] = []
            for ref, question in coverage.questions.items():
                row = question_record(ref, question)
                for key in ('subject', 'subject_member', 'time_context', 'observation_id', 'episode_id'):
                    row.pop(key)
                row['scope'] = scope(question.subject, question.subject_member, question.time_context,
                    question.observation_id, question.episode_id)
                payload['pending_questions'].append(row)
    if state.interview.current == 'DifferentialDiagnosis' and mode != 'rank' or coverage.questions and coverage.answer_refs:
        payload['asked_questions'] = []
        for index, answer in enumerate(state.interview.answers, 1):
            if len(answer.key) != 8 or answer.outcome == 'undelivered':
                continue
            if mode == 'rank' and f'a_{index}' not in coverage.answer_refs:
                continue
            kind, target, attribute, subject, member, timing, observation, episode = answer.key
            payload['asked_questions'].append(dict(ref=f'a_{index}', kind=kind, target=target, attribute=attribute or None,
                outcome=answer.outcome, scope=scope(subject, member or None, timing,
                    observation or None, episode or None)))
    close_graph_input(payload)
    if state.interview.current == 'DifferentialDiagnosis' and mode != 'rank':
        payload['resources'].update(requirements(state, question_refs))
    work = DecisionWork(payload, {refs[i]: i for i in included}, candidates, question_refs, coverage)
    return work


def close_graph_input(payload):
    """Keep every evidence/question record and remove only unused definitions."""
    fact_scopes = {row['scope'] for row in payload['facts'].values()}
    evidence, questions = payload['evidence'], payload['questions']
    used_relations = {row['relation'] for row in evidence.values() if 'relation' in row}
    used_relations.update(entry['relation'] for row in questions for entries in row['expected_by_disease'].values()
                          for entry in entries if entry.get('relation'))
    used_scopes = fact_scopes | {row['scope'] for row in evidence.values() if 'scope' in row} | {row['scope'] for row in questions}
    used_scopes.update(row['scope'] for row in payload.get('asked_questions', []))
    used_scopes.update(row['scope'] for row in payload.get('pending_questions', []))
    if not used_relations <= payload['relations'].keys() or not used_scopes <= payload['scopes'].keys():
        raise ValueError('clinical_input_missing_definition')
    payload['relations'] = {ref: row for ref, row in payload['relations'].items() if ref in used_relations}
    used_conditions = {row['applicability'] for row in payload['relations'].values() if row.get('applicability')}
    if not used_conditions <= payload['conditions'].keys():
        raise ValueError('clinical_input_missing_condition')
    payload['conditions'] = {ref: row for ref, row in payload['conditions'].items() if ref in used_conditions}
    payload['scopes'] = {ref: row for ref, row in payload['scopes'].items() if ref in used_scopes}
    payload['input_limits'].update(omitted_evidence=0, omitted_questions=0)


def accept_ranking(state, raw, work):
    if not isinstance(raw, dict) or set(raw) - {'ranked_disease_refs', 'next_action', 'covered_questions'}:
        raise ValueError('invalid_clinical_response_fields')
    ranked = RankingReply.model_validate({'ranked_disease_refs': raw.get('ranked_disease_refs')}).ranked_disease_refs
    if (bool(work.refs) != bool(ranked) or len(ranked) != len(set(ranked))
            or any(ref not in work.refs for ref in ranked) or not set(work.payload['prior_order']) <= set(ranked)):
        raise ValueError('invalid_or_incomplete_ranking')
    state.case.assessment = Assessment(differential=tuple(work.candidates[work.refs[ref]].entry for ref in ranked),
        based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id,
        based_on_response=latest_response(state))


def rank_exchange(state, client, brain, config, work, accept):
    error = None
    for attempt in range(2):
        response = brain.complete(state, client, role='clinical', messages=clinical_messages(config, work),
            max_tokens=LIMITS.gateway_recovery_tokens if attempt else LIMITS.gateway_tokens)
        if state.session.termination:
            return response.error
        try:
            raw = strict_json(response.content)
            if not isinstance(raw, dict) or set(raw) - {'covered_questions'} != {'ranked_disease_refs'}:
                raise ValueError('expected_rank_only_response')
            accept(raw)
            return None
        except (ValueError, TypeError) as failure:
            error = response.error or str(failure)
            if response.error and response.error not in {'OUTPUT_TRUNCATED', 'PROVIDER_RESPONSE_INVALID'}:
                break
            work.payload['validation_error'] = error
    state.interview.collection[f'{state.interview.current}:decision'] = error
    return error
