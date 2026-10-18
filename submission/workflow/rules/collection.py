INTAKE = ("onset", "course", "recurrence", "previous_care")
HISTORY = ("medical_history", "medication", "allergy", "family_history", "social_history")
ATTRIBUTE_CATEGORIES = {"TimeSinceOnset": "onset", "Onset": "onset", "Course": "course",
    "EpisodeDuration": "duration", "Quality": "quality", "PainQuality": "quality",
    "AggravatingFactor": "aggravating_factor", "RelievingFactor": "relieving_factor"}
CATEGORY_FIELDS = {**dict.fromkeys((*INTAKE, "duration", "quality", "aggravating_factor", "relieving_factor",
    "associated_symptoms", "presentation", "patient_context", "measurement"), "S.hpi"),
    **dict.fromkeys(("medical_history", "medication", "allergy", "surgery", "developmental_history"), "S.pmh"),
    "family_history": "S.fh", "review_of_systems": "S.ros",
    **dict.fromkeys(("smoking", "alcohol", "occupation", "social_history"), "S.sh")}


def category(value):
    return value.record_category or ATTRIBUTE_CATEGORIES.get((value.attribute_id or "").rsplit(":", 1)[-1])


def slot_records(case, slot):
    anchor = case.primary_chief
    return [item for _, item in case.current_entries() if item.status == "done" and item.source_refs and item.value
        and category(item.value) == slot and (slot not in INTAKE or item.value.subject == "patient"
            and (not anchor or not item.value.observation_id or
                 (item.value.observation_id, item.value.episode_id) == (anchor.observation_id, anchor.episode_id)))]


def slot_resolved(case, slot):
    return any(item.value.concept_ids and (item.value.not_applicable or item.value.status in {"present", "absent"})
               for item in slot_records(case, slot))


def answered(state, slot):
    return slot_resolved(state.case, slot) or any(o.record_category == slot and o.state != "conflict" for o in state.case.outcomes) or any(e.delivered and e.question and e.question.record_category == slot
        and e.question.purpose in {"intake", "history"} for e in state.interaction.history)
