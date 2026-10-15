from knowledge.graph import ClinicalKnowledge, Plan

from .state.models import ClinicalValue, Question, RecordItem, WorkflowState
from .rules.limits import LIMITS


class InterviewPlanner:
    def __init__(self, knowledge: ClinicalKnowledge, config, questions, interactions, budget, usage):
        self.knowledge = knowledge
        self.config = config
        self.questions = questions
        self.interactions = interactions
        self.budget = budget
        self.usage = usage

    @staticmethod
    def has_resolved_evidence(state: WorkflowState, target, attribute=None, observation=None, episode=None,
                              subject="patient", time_context=None):
        values = [item.value for _, item in state.case.entries() if item.status == "done" and item.source_refs
                  and item.value and target in item.value.concept_ids and item.value.attribute_id == attribute
                  and item.value.subject == subject
                  and (time_context is not None or item.value.kind == "context" or item.value.time_context != "past")
                  and (observation is None or item.value.observation_id == observation)
                  and (episode is None or item.value.episode_id == episode)
                  and (time_context is None or item.value.time_context == time_context)]
        values = [value for value in values if value.status in {"present", "absent"}]
        if not values:
            return False
        return len({value.status for value in values}) == 1 and all(
            len(value.concept_ids) == 1 and (attribute is None or value.values or value.measurement)
            and value.kind in {"symptom", "finding", "context", "attribute"} for value in values)

    @staticmethod
    def was_asked(state: WorkflowState, target, attribute=None, observation=None, episode=None,
                  subject="patient", time_context=None):
        for entry in state.interaction.history:
            q = entry.question
            if not entry.delivered or not q or (q.target_id, q.attribute_id, q.subject) != (target, attribute, subject):
                continue
            contexts = [(q.observation_id, q.episode_id, q.time_context)]
            contexts.extend((value.observation_id, value.episode_id, value.time_context)
                            for _, item in state.case.entries() if entry.id in item.source_refs and (value := item.value)
                            and target in value.concept_ids and value.attribute_id == attribute and value.subject == subject)
            if any((observation is None or observed == observation) and (episode is None or occurrence == episode)
                   and (time_context is None or timing == time_context) for observed, occurrence, timing in contexts):
                return True
        return False

    @classmethod
    def _covered(cls, state, *args, **kwargs):
        return cls.has_resolved_evidence(state, *args, **kwargs) or cls.was_asked(state, *args, **kwargs)

    def prepare_initiation(self, state: WorkflowState) -> None:
        self.questions.register(state, Question(item_id="Initiation:chief", field="S.cc", purpose="chief",
            text=self.config.texts.chief_question, order=0, priority=1))

    def prepare_chief_complaint(self, state: WorkflowState) -> None:
        order = 0
        for chief in state.case.chief_complaints():
            value = chief.value
            if not value or value.kind != "symptom" or value.subject != "patient" or value.time_context == "past" or value.status == "absent":
                continue
            concepts = value.concept_ids
            attributes = list(dict.fromkeys(attribute for target in concepts for attribute in self.knowledge.get_symptom_attributes(target)))
            if not concepts:
                self.questions.register(state, Question(item_id=f"ChiefComplaint:{chief.id}:location", field="S.hpi",
                    purpose="hpi", text=self.config.texts.unmapped_question, observation_id=value.observation_id,
                    episode_id=value.episode_id, order=order, priority=LIMITS.hpi_priority - order))
                order += 1
            for attribute in attributes:
                target = next(concept for concept in concepts if attribute in self.knowledge.get_symptom_attributes(concept))
                if self._covered(state, target, attribute, value.observation_id, value.episode_id):
                    continue
                self.questions.register(state, Question(item_id=f"ChiefComplaint:{chief.id}:{attribute}", field="S.hpi",
                    purpose="hpi", target_id=target, attribute_id=attribute, observation_id=value.observation_id,
                    episode_id=value.episode_id, text=self.knowledge.question(attribute, target),
                    order=order, priority=LIMITS.hpi_priority - order))
                order += 1
        self.prepare_open_inquiry(state, order)
        self.prepare_focused_ros(state, order + 1)

    def prepare_open_inquiry(self, state: WorkflowState, order: int) -> None:
        self.questions.register(state, Question(item_id="ChiefComplaint:open", field="S.ros", purpose="open_inquiry",
            text=self.config.texts.open_question, order=order, priority=LIMITS.open_inquiry_priority))

    def prepare_focused_ros(self, state: WorkflowState, order: int) -> None:
        targets = {target for item in state.case.chief_complaints(confirmed=True) for target in item.value.concept_ids}
        systems = {system for target in targets for system in self.knowledge.get_symptom_systems(target)}
        related = {target for system in systems for target in self.knowledge.get_system_symptoms(system)}
        unasked = [target for target in sorted(related - targets) if not self._covered(state, target)]
        for index, target in enumerate(unasked[:LIMITS.focused_ros]):
            self.questions.register(state, Question(item_id=f"ChiefComplaint:ros:{target}", field="S.ros", purpose="ros",
                target_id=target, text=self.config.texts.ros_question.format(symptom=self.knowledge.label(target)),
                affirmative_presence=self.config.texts.ros_question == "{symptom}도 있나요?",
                order=order + index, priority=LIMITS.ros_priority - index))

    def prepare_clarification(self, state: WorkflowState, original: Question | None = None) -> bool:
        session = state.session
        if not self.budget.can_clarify(state):
            return False
        self.usage.record_clarification(state)
        if original and (original.kind == "EXAM" or original.field.startswith("P.")):
            original = None
        values = original.model_dump() if original else {"field": "S.ros" if state.case.chief_complaints() else "S.cc"}
        values.update(item_id=f"{session.current}:clarification:{session.clarifications}", kind="SAY",
                      purpose="clarification", text=self.config.texts.clarification_question,
                      order=-session.clarifications, priority=LIMITS.clarification_priority)
        self.questions.register(state, Question(**values))
        return True

    def prepare_education(self, state: WorkflowState, *, replace=False, create_questions=True) -> None:
        remaining = [q for q in state.questions.questions if q.purpose == "education"
                     and (item := state.case.get(q.item_id)) and item.status == "unasked"]
        capacity = len(remaining) if replace else max(0, state.session.limits["Education"].actions - state.session.usage["Education"].actions)
        if replace:
            removed = {q.item_id for q in remaining}
            self.questions.discard_unasked(state, removed)
        selected = state.differential.selected_id
        if state.case.diagnosis_kind == "symptom":
            plan = Plan(education=[self.config.texts.symptom_education])
        elif selected:
            plan = self.knowledge.plans.get(selected, Plan())
            if selected not in self.knowledge.plans:
                state.interaction.issues.append(f"missing_plan:{selected}")
        else:
            state.stop("failed", "diagnosis_missing")
            return
        for field in ("tests", "treatment", "disposition", "follow_up", "education"):
            text = getattr(plan, field)
            if field == "tests" and not text and selected:
                text = self.config.texts.test_separator.join(self.knowledge.get_planned_tests(selected))
            elif field == "education":
                text = self.config.texts.record_separator.join(text)
            item_id = f"plan:{field}"
            state.case.remove({item_id})
            if text:
                state.case.put(f"P.{field}", RecordItem(id=item_id, scope="Education", status="done",
                    value=ClinicalValue(kind="plan", text=text, status="present", concept_ids=[selected] if selected else [])))
        if create_questions:
            for order, text in enumerate(plan.education[:capacity]):
                self.questions.register(state, Question(item_id=f"Education:{selected or 'symptom'}:{order}", field="P.education",
                    purpose="education", text=text, order=order, priority=capacity - order))

    def prepare_context_questions(self, state: WorkflowState) -> None:
        contexts = {}
        for hypothesis in state.differential.hypotheses:
            required = set()
            for context in self.knowledge.get_supporting_context(hypothesis.disease_id):
                subject = "family" if context["type"] == "family_history" else "patient"
                required.add((context["id"], subject, "unspecified"))
            for profile in self.knowledge.get_disease_patterns(hypothesis.disease_id):
                required.update((condition.concept_id, condition.subject, condition.time_context) for condition in profile.applicability)
            for key in required:
                contexts[key] = contexts.get(key, 0) + 1
        for order, ((target, subject, time_context), count) in enumerate(sorted(contexts.items(), key=lambda pair: (-pair[1], pair[0]))):
            kind = self.knowledge.get_context_type(target)
            if self._covered(state, target, subject=subject, time_context=None if time_context == "unspecified" else time_context):
                continue
            field = "S.fh" if subject == "family" else ("S.sh" if kind in {
                "social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh")
            suffix = "" if time_context == "unspecified" else f":{subject}:{time_context}"
            self.questions.register(state, Question(item_id=f"ContextFactor:{target}{suffix}", field=field, purpose="context",
                target_id=target, subject=subject, time_context=time_context, text=self.knowledge.question(target),
                order=order, priority=count))

    def prepare_differential_questions(self, state: WorkflowState) -> None:
        options = []
        for rank, hypothesis in enumerate(state.differential.hypotheses):
            for pattern in self.knowledge.get_disease_patterns(hypothesis.disease_id):
                target = pattern.target
                typicality = self.knowledge.policy.labels.get(pattern.typicality, 0)
                deltas = self.knowledge.get_feature_contributions(pattern.association_id)
                for feature in self.knowledge.get_pattern_features(pattern.id):
                    delta = max((abs(c.delta_score) for c in deltas if feature.id in c.changed_feature_ids), default=0)
                    options.append((rank, -typicality, -delta, target, feature.attribute or ""))
        seen, methods_seen = set(), set()
        for rank, typicality, delta, target, attribute in sorted(options):
            attribute = attribute or None
            existing = [item.value for _, item in state.case.entries() if item.value and item.value.kind in {"symptom", "finding"}
                        and target in item.value.concept_ids and item.value.subject == "patient" and item.value.time_context != "past"]
            occurrences = [(value.observation_id, value.episode_id) for value in existing] or [(None, None)]
            for observation, episode in occurrences:
                key = (target, attribute, observation, episode)
                if key in seen or self.has_resolved_evidence(state, target, attribute, observation, episode):
                    continue
                seen.add(key)
                if self.was_asked(state, target, attribute, observation, episode):
                    previous = [entry.question for entry in state.interaction.history if entry.delivered and entry.question
                                and entry.question.target_id == target and entry.question.attribute_id == attribute
                                and ((entry.question.observation_id == observation and entry.question.episode_id == episode) or any(
                                    entry.id in item.source_refs and item.value and item.value.observation_id == observation
                                    and item.value.episode_id == episode for _, item in state.case.entries()))]
                    if previous and not any(q.purpose == "clarification" for q in previous):
                        original = previous[-1].model_copy(update={"observation_id": observation, "episode_id": episode})
                        self.prepare_clarification(state, original)
                    continue
                exam = self.knowledge.has_type(target, "ExamFinding")
                methods = self.knowledge.get_exam_methods(target) if exam else []
                method = methods[0] if methods else None
                if exam and (not method or (method["id"], episode) in methods_seen):
                    continue
                if method:
                    methods_seen.add((method["id"], episode))
                order = len(state.questions.questions)
                self.questions.register(state, Question(item_id=f"DifferentialDiagnosis:{order}", field="O.exam" if exam else "S.ros",
                    kind="EXAM" if exam else "SAY", purpose="feature", target_id=target, attribute_id=attribute,
                    observation_id=observation, episode_id=episode,
                    text=method["text"] if method else self.knowledge.question(attribute or target, target),
                    order=order, priority=(len(state.differential.hypotheses) - rank) * LIMITS.differential_rank_weight))

    def select_question(self, state: WorkflowState) -> None:
        answered = {q.item_id for q in state.questions.questions if q.target_id and q.purpose != "clarification" and
                    (item := state.case.get(q.item_id)) and item.status == "unasked" and
                    self.has_resolved_evidence(state, q.target_id, q.attribute_id, q.observation_id, q.episode_id, q.subject,
                               None if q.time_context == "unspecified" else q.time_context)}
        self.questions.discard_unasked(state, answered)
        questions = [q for q in state.questions.questions
                     if (item := state.case.get(q.item_id)) and item.scope == state.session.current and item.status == "unasked"]
        if not questions:
            if state.case.unasked(state.session.current):
                state.stop("failed", "unplanned_unasked_record")
            return
        question = min(questions, key=lambda q: (q.order, q.item_id))
        self.interactions.select_question(state, question)
