from dataclasses import dataclass, field
import json
from typing import Literal

from pydantic import StrictStr, model_validator

from .assessment import graph_candidates
from .limits import LIMITS
from .normalization import strict_json
from ..model_context import compact_row, fact_record, messages
from ..state.models import Assessment, Model


class RankingReply(Model):
    ranked_disease_refs: list[StrictStr]


class NextAction(Model):
    kind: Literal['continue_required', 'ask', 'advance_stage', 'finish_collection']
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


def clinical_messages(config, work):
    return messages(config.clinical_prompt + '\n' + config.session_prompts[work.payload['stage']], work.payload)


def prepare_decision(state, knowledge, tools, *, mode='decision', closing=False):
    candidates = graph_candidates(state.case, knowledge, state.interview)
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
    refs = {ident: f'd_{index}' for index, ident in enumerate(ordered, 1)}
    facts = state.case.current_facts()
    fact_refs = {fact.id: f'f_{index}' for index, fact in enumerate(facts, 1)}
    observations = {fact.observation_id for fact in facts if fact.observation_id}
    scopes, scope_refs, observation_refs, episode_refs = {}, {}, {}, {}

    def scope(subject, member, time, observation, episode):
        observed = observation if observation in observations else None
        key = (subject, member, time, observed, episode)
        if key not in scope_refs:
            ident = f's_{len(scope_refs) + 1}'
            scope_refs[key] = ident
            row = dict(subject=subject, time=time)
            if member:
                row['member'] = member
            if observed:
                row['observation'] = observation_refs.setdefault(observed, f'o_{len(observation_refs) + 1}')
            if episode:
                row['episode'] = episode_refs.setdefault(episode, f'episode_{len(episode_refs) + 1}')
            scopes[ident] = compact_row(row)
        return scope_refs[key]

    patient_rows = {}
    for fact in facts:
        row = fact_record(fact)
        for key in ('id', 'subject', 'subject_member', 'time_context', 'observation_id', 'episode_id'):
            row.pop(key, None)
        row['scope'] = scope(fact.subject, fact.subject_member, fact.time_context, fact.observation_id, fact.episode_id)
        patient_rows[fact_refs[fact.id]] = compact_row(row)
    payload = dict(task={'rank': 'clinical_rank', 'action': 'clinical_action', 'decision': 'clinical_decision'}[mode],
        stage=state.interview.current, revision=state.case.revision,
        chief=fact_refs.get(state.case.chief_fact_id),
        facts=patient_rows, scopes=scopes, conditions={},
        prior_order=[refs[ident] for ident in protected], required=[],
        resources=dict(turns=tools.budget.action_capacity(state), calls=tools.budget.calls_left(state.session)),
        candidates=[], evidence={}, questions=[])
    evidence_refs = {}
    condition_refs = {}
    def expected(value):
        if not isinstance(value, dict):
            return value
        if value.get('kind') == 'concept':
            name = knowledge.term(value['concept'])
            return name if value.get('match', 'exact') == 'exact' else {'subsumption': name}
        if value.get('kind') == 'concept_set':
            return {value['selection']: [knowledge.term(v) for v in value['concepts']]}
        return {key: item for key, item in value.items() if item is not None and item != [] and
                key not in {'concept', 'concepts', 'selection', 'match'} and
                not (key in {'lower_inclusive', 'upper_inclusive'} and item is True)}

    def conditions(rows):
        if not rows:
            return None
        value = [dict(target=c['name'], status=c['status'], subject=c['subject'], time=c['time_context']) for c in rows]
        signature = json.dumps(value, sort_keys=True)
        if signature not in condition_refs:
            ident = f'condition_{len(condition_refs) + 1}'
            condition_refs[signature] = ident
            payload['conditions'][ident] = ' | '.join(compact_row(row) for row in value)
        return condition_refs[signature]

    def describe(ref, details):
        graph = ref.graph_ref
        detail = next((d for d in details if d['association'] == (graph.association_id or graph.id)), None)
        row = dict(level=graph.kind, facts=[fact_refs[i] for i in ref.fact_ids])
        if detail:
            row['target'] = detail['target']
            features = detail['features'] if graph.kind == 'association' else [f for f in detail['features'] if f['id'] == graph.id]
            row['expects'] = {f['attribute'] or 'presence': expected(f['expected']) for f in features}
            if detail['conditions']:
                row['if'] = conditions(detail['conditions'])
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
            payload['evidence'][ident] = compact_row(row)
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
            expected_by_disease={})
        for disease in sorted(diseases & included):
            entries = []
            for missing in candidates[disease].entry.unresolved:
                if missing.scope != question.semantic_key():
                    continue
                graph = missing.graph_ref
                detail = next((d for d in candidates[disease].details if d['association'] == graph.association_id), None)
                feature = next((f for f in detail['features'] if f['id'] == graph.id), None) if detail else None
                value = dict(expected=expected(feature['expected']) if feature else 'present',
                    applicability=[dict(target=c['name'], status=c['status'], subject=c['subject'], time=c['time_context'])
                        for c in detail['conditions']] if detail else [])
                if value not in entries:
                    entries.append(value)
            row['expected_by_disease'][refs[disease]] = entries
        payload['questions'].append({key: value for key, value in row.items() if value is not None})
        question_refs[ref] = spec
    work = DecisionWork(payload, {refs[i]: i for i in included}, candidates, question_refs)
    return work


def accept_ranking(state, raw, work):
    if not isinstance(raw, dict) or set(raw) - {'ranked_disease_refs', 'next_action'}:
        raise ValueError('invalid_clinical_response_fields')
    ranked = RankingReply.model_validate({'ranked_disease_refs': raw.get('ranked_disease_refs')}).ranked_disease_refs
    if (bool(work.refs) != bool(ranked) or len(ranked) != len(set(ranked))
            or any(ref not in work.refs for ref in ranked) or not set(work.payload['prior_order']) <= set(ranked)):
        raise ValueError('invalid_or_incomplete_ranking')
    state.case.assessment = Assessment(differential=tuple(work.candidates[work.refs[ref]].entry for ref in ranked),
        based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id)


def rank_exchange(state, client, brain, config, work, accept):
    error = None
    for attempt in range(2):
        response = brain.complete(state, client, role='clinical', messages=clinical_messages(config, work),
            max_tokens=LIMITS.gateway_recovery_tokens if attempt else LIMITS.gateway_tokens)
        if state.session.termination:
            return response.error
        try:
            raw = strict_json(response.content)
            if not isinstance(raw, dict) or set(raw) != {'ranked_disease_refs'}:
                raise ValueError('expected_rank_only_response')
            accept(raw)
            return None
        except (ValueError, TypeError) as failure:
            error = response.error or str(failure)
            if response.error and response.error not in {'OUTPUT_TRUNCATED', 'PROVIDER_RESPONSE_INVALID', 'CONTEXT_LIMIT_EXCEEDED'}:
                break
            work.payload['validation_error'] = error
    state.interview.collection[f'{state.interview.current}:decision'] = error
    return error
