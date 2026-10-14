from ..state.models import ClinicalValue, Fact, ParsedInput, WorkflowState


def fixed_reply(config, state: WorkflowState, text: str) -> ParsedInput | None:
    question = state.interaction.pending.question
    texts = config.texts
    reply = text.strip().rstrip(texts.reply_trailing_punctuation)
    if reply in texts.unknown_replies:
        return ParsedInput()
    if question.purpose == "education" and reply in texts.education_acknowledgements:
        return ParsedInput()
    if state.interaction.pending.render_source == "doctor":
        return None
    statuses = {**dict.fromkeys(texts.present_replies, "present"), **dict.fromkeys(texts.absent_replies, "absent")}
    if (not question.affirmative_presence or question.purpose not in {"context", "feature", "ros"}
            or question.attribute_id or question.kind != "SAY" or reply not in statuses):
        return None
    kind = "context" if question.purpose == "context" else "symptom"
    return ParsedInput(facts=[Fact(field=question.field, record_id=question.item_id, quote=text,
        value=ClinicalValue(kind=kind, text=text, status=statuses[reply], concept_ids=[question.target_id],
            observation_id=question.observation_id or question.item_id,
            episode_id=question.episode_id or question.item_id, subject=question.subject,
            time_context=question.time_context))])


def validate_facts(raw, state, knowledge, text):
    parsed = ParsedInput.model_validate(raw)
    pending = state.interaction.pending
    dialogue_ids = {entry["id"] for entry in state.interaction.dialogue()}
    for fact in parsed.facts:
        value = fact.value
        if not set(fact.context_refs) <= dialogue_ids:
            raise ValueError("Unknown dialogue context reference")
        if fact.quote not in text or value.text != fact.quote or fact.field.startswith(("A.", "P.")) or fact.field == "O.tests":
            raise ValueError("Fact is not grounded in an allowed current input")
        if fact.field == "O.exam" and (pending is None or pending.question.kind != "EXAM"):
            raise ValueError("Patient speech cannot create examination findings")
        if value.kind == "finding" and fact.field != "O.exam":
            raise ValueError("Examination findings require an actual examination")
        if value.kind == "attribute" and not value.attribute_id:
            raise ValueError("Attribute fact requires an attribute")
        if value.kind in {"plan", "education"}:
            raise ValueError("Input cannot create plans or delivered education")
        if fact.record_id:
            existing = state.case.get(fact.record_id)
            question = next((q for q in state.questions.questions if q.item_id == fact.record_id), None)
            if existing is None or (existing.value and existing.value.kind in {"plan", "education"}) or (
                question and question.purpose == "education"
            ):
                raise ValueError("Invalid observation record reference")
            previous = existing.value
            if question and question.purpose in {"hpi", "context", "feature", "ros", "clarification"} and (
                value.subject != question.subject or value.attribute_id != question.attribute_id
                or (question.target_id and question.target_id not in value.concept_ids)
                or (question.observation_id and value.observation_id not in {None, question.observation_id})
                or (question.episode_id and value.episode_id not in {None, question.episode_id})
            ):
                raise ValueError("Answer does not match its question target and episode")
            if previous and previous.kind in {"symptom", "finding", "attribute"} and (
                value.subject != previous.subject or value.observation_id != previous.observation_id
                or value.episode_id != previous.episode_id
            ):
                raise ValueError("Correction must preserve its observation and episode")
        expected_type = {"symptom": "Symptom", "finding": "ExamFinding", "context": "ContextFactor"}
        for concept in value.concept_ids:
            if value.kind in expected_type and not knowledge.has_type(concept, expected_type[value.kind]):
                raise ValueError("Unknown or mistyped clinical concept")
            if value.kind == "attribute" and not any(knowledge.has_type(concept, kind) for kind in ("Symptom", "ExamFinding")):
                raise ValueError("Attribute requires a finding target")
        if len(value.concept_ids) > 1 and value.status == "present":
            raise ValueError("Multiple interpretations must remain uncertain")
        if value.attribute_id:
            if not value.concept_ids or not all(value.attribute_id in knowledge.get_symptom_attributes(c) for c in value.concept_ids):
                raise ValueError("Attribute is not applicable")
            if not set(value.values) <= set(knowledge.get_attribute_values(value.attribute_id)):
                raise ValueError("Categorical values are not admitted")
        elif value.values:
            raise ValueError("Categorical values require an attribute")
        if value.kind == "context" and value.concept_ids:
            context = value.concept_ids[0]
            context_type = knowledge.get_context_type(context)
            fact.field = "S.fh" if context_type == "family_history" else (
                "S.sh" if context_type in {"social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh")
            if (context_type == "family_history") != (value.subject == "family"):
                raise ValueError("Context subject does not match its clinical meaning")
    return parsed
