INTAKE = ('onset', 'course', 'recurrence', 'previous_care')
HISTORY = ('medical_history', 'medication', 'allergy', 'family_history', 'social_history')
CATEGORY_FIELDS = {**dict.fromkeys((*INTAKE, 'duration', 'quality', 'aggravating_factor', 'relieving_factor',
    'associated_symptoms', 'presentation', 'patient_context', 'measurement'), 'S.hpi'),
    **dict.fromkeys(('medical_history', 'medication', 'allergy', 'surgery', 'developmental_history'), 'S.pmh'),
    'family_history':'S.fh', 'review_of_systems':'S.ros',
    **dict.fromkeys(('smoking', 'alcohol', 'occupation', 'social_history'), 'S.sh')}


def slot_records(case, slot):
    chief = case.collection_chief()
    return [f for f in case.current_facts() if f.category == slot
            and f.polarity_scope == 'general'
            and (slot not in HISTORY or not (f.id.startswith('patient_context:') or f.context_key)
                 and (slot == 'family_history' or f.subject == 'patient' and f.subject_member is None))
            and (slot not in INTAKE or chief and f.subject == chief.subject and f.subject_member == chief.subject_member
                 and f.time_context == chief.time_context
                 and f.acquisition != 'EXAM' and f.source_ref != 'initial:vital_signs'
                 and f.observation_id and f.episode_id
                 and (f.observation_id, f.episode_id) == (chief.observation_id, chief.episode_id)
                 and (not f.target or f.target == chief.target))]


def slot_resolved(case, slot):
    return any(f.status in {'present', 'absent'} for f in slot_records(case, slot))


def answered(state, slot):
    if slot_resolved(state.case, slot):
        return True
    chief = state.case.collection_chief()
    for answer in state.interview.answers:
        if answer.category != slot or answer.outcome == 'undelivered':
            continue
        if slot in HISTORY:
            # Only a delivered whole-domain history question can complete a slot
            # without a decisive fact. A focused family or demographic answer cannot.
            if (answer.purpose != 'history' or not answer.source_ref or len(answer.key) != 8
                    or answer.key[:3] != ('SAY', '', '')
                    or answer.key[3:] != ('family' if slot == 'family_history' else 'patient', '', 'unspecified', '', '')):
                continue
            linked = [f for f in state.case.facts.values()
                      if f.id in answer.fact_ids or f.source_ref == answer.source_ref]
            if linked and not any(f in slot_records(state.case, slot) for f in linked):
                continue
            return True
        if slot not in INTAKE or chief and answer.key and (
                answer.key[0], answer.key[1], answer.key[3], answer.key[4], answer.key[5], answer.key[6], answer.key[7]) == (
                'SAY', chief.target, chief.subject, chief.subject_member or '', chief.time_context,
                chief.observation_id or '', chief.episode_id or ''):
            return True
    if slot in INTAKE:
        key = '|'.join(('SAY', chief.target, '', chief.subject, chief.subject_member or '', chief.time_context,
                        chief.observation_id or '', chief.episode_id or '', slot)) if chief else None
        return bool(key and key in state.interview.collection)
    return slot in state.interview.collection
