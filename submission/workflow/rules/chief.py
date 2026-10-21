from ..model_context import messages
from ..state.models import ChiefRoute
from .normalization import concept_rank, strict_json


def force_chief(state, knowledge, config, brain=None, client=None):
    """Fix a collection route once; never promote a selection into a patient fact."""
    if state.case.collection_chief():
        return True
    if 'chief:forced_selection' in state.interview.collection:
        return False
    state.interview.collection['chief:forced_selection'] = 'attempted'
    facts = [f for f in state.case.current_facts() if f.subject == 'patient'
             and f.time_context != 'past' and f.category == 'presentation']
    terms = [f.target or f.value for f in facts]
    quotes = [state.case.presenting_text] if state.case.presenting_text.strip() else []
    ranked = concept_rank(knowledge, [*terms, *quotes], ('Symptom',))
    lexical = bool(ranked)
    if not ranked:
        ranked = sorted(ident for (kind, _), ident in knowledge._term_ids.items() if kind == 'Symptom')
    candidates = list(dict.fromkeys(i for i in ranked if knowledge.has_type(i, 'Symptom')))[:8]
    if not candidates:
        raise ValueError('prepared_symptom_vocabulary_empty')
    refs = {f's_{index}': ident for index, ident in enumerate(candidates, 1)}
    chosen, method = candidates[0], 'lexical' if lexical else 'stable_order'
    if brain is not None and client is not None:
        response = brain.complete(state, client, role='gateway', messages=messages(
            config.prompt('chief.select'), dict(task='chief_selection', presentation=quotes,
                candidates=[dict(ref=ref, name=knowledge.term(ident)) for ref, ident in refs.items()])))
        try:
            raw = strict_json(response.content)
            if isinstance(raw, dict) and set(raw) == {'symptom_ref'} and isinstance(raw['symptom_ref'], str) and raw['symptom_ref'] in refs:
                chosen = refs[raw['symptom_ref']]
                if lexical:
                    method = 'model'
        except (ValueError, TypeError):
            pass
    name = knowledge.term(chosen)
    actual = next((f for f in state.case.chief_candidates(confirmed=True) if f.target == name), None)
    if actual:
        state.case.select_primary(actual.id)
    else:
        source = next((f for f in facts if f.target == name), None)
        state.case.chief_route = ChiefRoute(target=name, target_id=chosen, method=method,
            source_ref=source.source_ref if source else 'initial:opening' if lexical and quotes else None,
            observation_id=source.observation_id if source else None,
            episode_id=source.episode_id if source else None)
    state.case.revision += 1
    state.interview.collection['chief:forced_selection'] = method
    return True
