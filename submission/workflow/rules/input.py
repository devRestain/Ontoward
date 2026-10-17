import re

from pydantic import ValidationError

from ..state.models import ClinicalValue, EmpathySignal, Fact, ParsedInput, ParseResult, WorkflowState


def fixed_reply(config, state: WorkflowState, text: str, knowledge=None) -> ParsedInput | None:
    question = state.interaction.pending.question
    texts = config.texts
    reply = text.strip().rstrip(texts.reply_trailing_punctuation)
    if reply in texts.unknown_replies:
        return ParsedInput(clinical_content=False)
    if question.purpose in {"education", "empathy"} and reply in texts.education_acknowledgements:
        return ParsedInput(clinical_content=False)
    if not state.session.gateway_successes:
        return None
    statuses = {**dict.fromkeys(texts.present_replies, "present"), **dict.fromkeys(texts.absent_replies, "absent")}
    if (question.affirmative_presence and question.answer_type == "presence" and question.target_id
            and question.purpose in {"context", "feature", "ros"} and not question.attribute_id
            and question.kind == "SAY" and reply in statuses):
        kind = "context" if question.purpose == "context" else "symptom"
        return ParsedInput(facts=[Fact(field=question.field, record_id=question.item_id, quote=text,
            value=ClinicalValue(kind=kind, text=text, status=statuses[reply], concept_ids=[question.target_id],
                observation_id=question.observation_id or question.item_id,
                episode_id=question.episode_id or question.item_id, subject=question.subject,
                time_context=question.time_context))])
    if question.kind != "SAY" or not question.target_id or not question.attribute_id:
        return None
    values, measurement = [], None
    if question.answer_type == "duration":
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(초|분|시간|일|주|개월|달|년)(?:이요|요)?", reply)
        if match:
            units = {"초": "s", "분": "min", "시간": "h", "일": "day", "주": "week", "개월": "month", "달": "month", "년": "year"}
            measurement = {"kind": "quantity", "value": float(match[1]), "unit": units[match[2]], "operator": "eq"}
    elif question.answer_type == "category" and knowledge is not None:
        values = [concept for concept in knowledge.resolve_concept(reply)
                  if concept in knowledge.get_attribute_values(question.attribute_id)]
        if len(values) != 1:
            values = []
    if not values and measurement is None:
        return None
    return ParsedInput(facts=[Fact(field=question.field, record_id=question.item_id, quote=text,
        value=ClinicalValue(kind="attribute", text=text, status="present", concept_ids=[question.target_id],
            attribute_id=question.attribute_id, values=values, measurement=measurement,
            observation_id=question.observation_id, episode_id=question.episode_id,
            subject=question.subject, time_context=question.time_context))])


def _validate_fact(fact, state, knowledge, text, dialogue_ids, supplied_records, allowed):
    pending = state.interaction.pending
    value = fact.value
    if allowed is not None and not set([*value.concept_ids, *value.values,
            *([value.attribute_id] if value.attribute_id else [])]) <= allowed:
        raise ValueError("Identifier outside supplied vocabulary")
    if not set(fact.context_refs) <= dialogue_ids:
        raise ValueError("Unknown dialogue context reference")
    if fact.quote not in text or value.text != fact.quote or fact.field.startswith(("A.", "P.")) or fact.field == "O.tests":
        raise ValueError("Fact is not grounded in an allowed current input")
    if any(detail.quote not in fact.quote or not detail.quote.strip() or not detail.english.strip()
           for detail in value.record_details):
        raise ValueError("Record keywords require exact current-input evidence")
    if ((value.measurement and value.measurement.unit.casefold() == "nrs"
            or any(re.search(r"\bNRS\b", detail.english, re.I) for detail in value.record_details))
            and not re.search(r"\bNRS\b", fact.quote + " " + (pending.content if pending else ""), re.I)):
        raise ValueError("NRS requires an explicitly reported or requested scale")
    category_fields = {
        "onset": "S.hpi", "duration": "S.hpi", "course": "S.hpi", "quality": "S.hpi",
        "aggravating_factor": "S.hpi", "relieving_factor": "S.hpi", "associated_symptoms": "S.hpi",
        "previous_care": "S.hpi", "presentation": "S.hpi", "medical_history": "S.pmh",
        "medication": "S.pmh", "allergy": "S.pmh", "surgery": "S.pmh", "family_history": "S.fh",
        "smoking": "S.sh", "alcohol": "S.sh", "occupation": "S.sh",
    }
    if value.record_category not in {None, "other"} and fact.field != category_fields[value.record_category]:
        raise ValueError("Record category does not match its SOAP field")
    if (value.kind == "text" and fact.field.startswith("S.") and value.status in {"present", "absent"}
            and not value.concept_ids and (not value.record_category or (
                value.status == "present" and not value.record_details))):
        raise ValueError("Unlinked text requires a record category and reported keywords")
    if fact.field == "O.exam" and (pending is None or pending.question.kind != "EXAM"):
        raise ValueError("Patient speech cannot create examination findings")
    if value.kind == "finding" and fact.field != "O.exam":
        raise ValueError("Examination findings require an actual examination")
    if value.kind == "attribute" and not value.attribute_id:
        raise ValueError("Attribute fact requires an attribute")
    if value.kind == "attribute" and value.status in {"present", "uncertain"} and not (value.values or value.measurement):
        raise ValueError("Substantive attribute answer requires a categorical or numeric value")
    if value.kind in {"plan", "education"}:
        raise ValueError("Input cannot create plans or delivered education")
    if fact.record_id:
        if supplied_records is not None and fact.record_id not in supplied_records:
            raise ValueError("missing_context_record")
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
        contract = knowledge.questions.get(concept)
        if contract and not contract.interviewable and (value.status == "present" or (
                fact.field == "S.cc" and value.status == "uncertain")):
            candidate = next(iter(knowledge.concepts([concept])), {})
            names = [knowledge.label(concept), *candidate.get("aliases", [])]
            if not any(knowledge.normalize_alias(name) in knowledge.normalize_alias(fact.quote) for name in names):
                raise ValueError("Unqualified wording cannot establish a diagnostic composite")
        if value.kind in expected_type and not knowledge.has_type(concept, expected_type[value.kind]):
            raise ValueError("Unknown or mistyped clinical concept")
        if value.kind == "attribute" and not any(knowledge.has_type(concept, kind) for kind in ("Symptom", "ExamFinding")):
            raise ValueError("Attribute requires a finding target")
    if len(value.concept_ids) > 1 and value.status == "present":
        raise ValueError("Multiple interpretations must remain uncertain")
    if fact.field == "S.cc" and value.kind == "symptom" and len(value.concept_ids) > 1:
        raise ValueError("A chief complaint requires one best existing Symptom")
    if value.attribute_id:
        if not value.concept_ids or not all(value.attribute_id in knowledge.get_symptom_attributes(c) for c in value.concept_ids):
            raise ValueError("Attribute is not applicable")
        if not set(value.values) <= set(knowledge.get_attribute_values(value.attribute_id)):
            raise ValueError("Categorical values are not admitted")
    elif value.values or value.measurement:
        raise ValueError("Typed values require an attribute")
    if value.kind == "context" and value.concept_ids:
        context = value.concept_ids[0]
        context_type = knowledge.get_context_type(context)
        fact.field = "S.fh" if context_type == "family_history" else (
            "S.sh" if context_type in {"social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh")
        if (context_type == "family_history") != (value.subject == "family"):
            raise ValueError("Context subject does not match its clinical meaning")



def validate_facts(raw, state, knowledge, text, *, dialogue_ids=None, supplied_records=None, allowed=None, frozen_facts=()):
    if (not isinstance(raw, dict) or set(raw) - {"facts", "needs_context", "lookup_terms", "clinical_content", "empathy"}
            or not isinstance(raw.get("facts", []), list) or type(raw.get("needs_context", False)) is not bool
            or type(raw.get("clinical_content", True)) is not bool):
        raise ValueError("Invalid fact envelope")
    empathy = None
    try:
        empathy = EmpathySignal.model_validate(raw["empathy"]) if raw.get("empathy") is not None else None
        if empathy and (not empathy.quote.strip() or empathy.quote not in text
                        or state.interaction.pending and state.interaction.pending.question.kind != "SAY"):
            raise ValueError("Empathy requires an exact current patient quote")
    except (ValidationError, ValueError, TypeError):
        empathy = None
        state.interaction.issues.append("invalid_empathy_signal")
    terms = raw.get("lookup_terms", [])
    if not isinstance(terms, list) or len(terms) > 8 or any(
            not isinstance(term, str) or not term.strip() or len(term) > 80 for term in terms):
        raise ValueError("Invalid lookup terms")
    dialogue_ids = set(dialogue_ids) if dialogue_ids is not None else {entry["id"] for entry in state.interaction.dialogue()}
    accepted, rejected = [], []
    for index, item in enumerate(raw.get("facts", [])):
        try:
            fact = Fact.model_validate(item)
            _validate_fact(fact, state, knowledge, text, dialogue_ids, supplied_records, allowed)
            accepted.append((index, fact))
        except (ValidationError, ValueError, TypeError) as error:
            rejected.append({"index": index, "raw": item, "reason": str(error)})

    def observation(value):
        return (value.subject, value.observation_id, value.episode_id)

    anchors = {(*observation(item.value), concept) for _, item in state.case.entries() if item.status == "done" and item.source_refs
               and item.value and item.value.kind in {"symptom", "finding"} for concept in item.value.concept_ids}
    anchors.update((*observation(f.value), concept) for _, f in accepted if f.value.kind in {"symptom", "finding"}
                   for concept in f.value.concept_ids)
    anchors.update((*observation(f.value), concept) for f in frozen_facts if f.value.kind in {"symptom", "finding"}
                   for concept in f.value.concept_ids)
    blocked = set()
    corrections = {}
    for index, fact in accepted:
        previous = state.case.get(fact.record_id) if fact.record_id else None
        if previous and previous.value:
            corrections.setdefault(fact.record_id, []).append((index, fact))
    for candidates in corrections.values():
        if len({f.value.model_dump_json() for _, f in candidates}) > 1:
            blocked.update(observation(f.value) for _, f in candidates)
    for item in rejected:
        raw_fact = item["raw"]
        record_id = raw_fact.get("record_id") if isinstance(raw_fact, dict) else None
        previous = state.case.get(record_id) if isinstance(record_id, str) else None
        if previous and previous.value and previous.value.kind in {"symptom", "finding", "attribute"}:
            blocked.add(observation(previous.value))
    anchor_statuses = {}
    for _, fact in accepted:
        if fact.value.kind in {"symptom", "finding"} and fact.value.status in {"present", "absent"}:
            key = (*observation(fact.value), tuple(sorted(fact.value.concept_ids)))
            anchor_statuses.setdefault(key, set()).add(fact.value.status)
    blocked.update(key[:3] for key, statuses in anchor_statuses.items() if len(statuses) > 1)
    facts = []
    for index, fact in accepted:
        value = fact.value
        question = state.interaction.pending.question if state.interaction.pending else None
        key = (value.subject, value.observation_id or (question.observation_id if question else None),
               value.episode_id or (question.episode_id if question else None))
        if key in blocked or (value.kind == "attribute" and not all((*key, concept) in anchors for concept in value.concept_ids)):
            rejected.append({"index": index, "raw": raw["facts"][index], "reason": "dependent_observation_or_correction"})
        else:
            facts.append(fact)
    return ParseResult(accepted_facts=facts, rejected_facts=rejected,
        unresolved_links=[i for i, fact in enumerate(facts) if fact.value.kind in {"symptom", "finding"}
                          and not fact.value.concept_ids and fact.value.status in {"present", "uncertain"}],
        needs_context=raw.get("needs_context", False) or any("missing_context" in str(item["reason"]) for item in rejected),
        lookup_terms=list(dict.fromkeys(term.strip() for term in terms)),
        clinical_content=raw.get("clinical_content", True) or bool(facts), empathy=empathy)
