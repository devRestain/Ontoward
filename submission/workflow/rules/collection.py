INTAKE = ('onset', 'course', 'recurrence', 'previous_care')
HISTORY = ('medical_history', 'medication', 'allergy', 'family_history', 'social_history')
ATTRIBUTE_CATEGORIES = {'TimeSinceOnset':'onset', 'Onset':'onset', 'Course':'course',
    'EpisodeDuration':'duration', 'Quality':'quality', 'PainQuality':'quality',
    'AggravatingFactor':'aggravating_factor', 'RelievingFactor':'relieving_factor'}
CATEGORY_FIELDS = {**dict.fromkeys((*INTAKE, 'duration', 'quality', 'aggravating_factor', 'relieving_factor',
    'associated_symptoms', 'presentation', 'patient_context', 'measurement'), 'S.hpi'),
    **dict.fromkeys(('medical_history', 'medication', 'allergy', 'surgery', 'developmental_history'), 'S.pmh'),
    'family_history':'S.fh', 'review_of_systems':'S.ros',
    **dict.fromkeys(('smoking', 'alcohol', 'occupation', 'social_history'), 'S.sh')}


def slot_records(case, slot):
    chief = case.chief()
    return [f for f in case.current_facts() if f.category == slot
            and (slot not in INTAKE or f.subject == 'patient' and (not chief or not f.observation_id
                 or (f.observation_id, f.episode_id) == (chief.observation_id, chief.episode_id)))]


def slot_resolved(case, slot):
    return any(f.status in {'present', 'absent'} for f in slot_records(case, slot))


def answered(state, slot):
    if slot_resolved(state.case, slot):
        return True
    chief = state.case.chief()
    for answer in state.interview.answers:
        if answer.category != slot or answer.outcome == 'undelivered':
            continue
        if slot not in INTAKE or not chief or answer.key and (
                answer.key[1], answer.key[6], answer.key[7]) == (chief.target, chief.observation_id or '', chief.episode_id or ''):
            return True
    return slot in state.interview.collection
