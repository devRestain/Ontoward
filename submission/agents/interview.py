from uuid import uuid4

from knowledge.graph import ClinicalKnowledge, Plan

from .state import ActionSpec, ClinicalValue, Question, RecordItem, WorkflowState


class InterviewAgent:
    def __init__(self, knowledge: ClinicalKnowledge, config):
        self.knowledge = knowledge
        self.config = config

    def add_question(self, state: WorkflowState, question: Question) -> None:
        if state.case.get(question.item_id):
            return
        item = RecordItem(id=question.item_id, scope=state.session.current)
        if not question.text:
            item.status = "done"
            item.value = ClinicalValue(kind="text", text=self.config.texts.missing_question_text, status="unknown")
            state.interaction.issues.append(f"missing_template:{question.item_id}")
        else:
            state.questions.questions.append(question)
        state.case.put(question.field, item)

    @staticmethod
    def known(state: WorkflowState, target, attribute=None, observation=None, episode=None, subject="patient"):
        return any(item.status == "done" and item.value and target in item.value.concept_ids
                   and item.value.attribute_id == attribute and item.value.subject == subject
                   and (item.value.kind == "context" or item.value.time_context != "past")
                   and (observation is None or item.value.observation_id == observation)
                   and (episode is None or item.value.episode_id == episode)
                   for _, item in state.case.entries())

    def initiation(self, state: WorkflowState) -> None:
        self.add_question(state, Question(item_id="Initiation:chief", field="S.cc", purpose="chief",
            text=self.config.texts.chief_question, order=0, priority=1))

    def fixed_hpi(self, state: WorkflowState) -> None:
        order = 0
        for chief in state.case.chief_complaints():
            value = chief.value
            if not value or value.kind != "symptom" or value.subject != "patient" or value.time_context == "past" or value.status == "absent":
                continue
            concepts = value.concept_ids
            attributes = list(dict.fromkeys(attribute for target in concepts for attribute in self.knowledge.get_symptom_attributes(target)))
            if not concepts:
                self.add_question(state, Question(item_id=f"ChiefComplaint:{chief.id}:location", field="S.hpi",
                    purpose="hpi", text=self.config.texts.unmapped_question, observation_id=value.observation_id,
                    episode_id=value.episode_id, order=order, priority=10000 - order))
                order += 1
            for attribute in attributes:
                target = next(concept for concept in concepts if attribute in self.knowledge.get_symptom_attributes(concept))
                if self.known(state, target, attribute, value.observation_id, value.episode_id):
                    continue
                self.add_question(state, Question(item_id=f"ChiefComplaint:{chief.id}:{attribute}", field="S.hpi",
                    purpose="hpi", target_id=target, attribute_id=attribute, observation_id=value.observation_id,
                    episode_id=value.episode_id, text=self.knowledge.question(attribute, target),
                    order=order, priority=10000 - order))
                order += 1
        self.open_inquiry(state, order)
        self.focused_ros(state, order + 1)

    def open_inquiry(self, state: WorkflowState, order: int) -> None:
        self.add_question(state, Question(item_id="ChiefComplaint:open", field="S.ros", purpose="open_inquiry",
            text=self.config.texts.open_question, order=order, priority=1000000))

    def focused_ros(self, state: WorkflowState, order: int) -> None:
        targets = {target for item in state.case.chief_complaints(confirmed=True) for target in item.value.concept_ids}
        systems = {system for target in targets for system in self.knowledge.get_symptom_systems(target)}
        related = {target for system in systems for target in self.knowledge.get_system_symptoms(system)}
        unasked = [target for target in sorted(related - targets) if not self.known(state, target)]
        for index, target in enumerate(unasked[:6]):
            self.add_question(state, Question(item_id=f"ChiefComplaint:ros:{target}", field="S.ros", purpose="ros",
                target_id=target, text=self.config.texts.ros_question.format(symptom=self.knowledge.label(target)),
                affirmative_presence=self.config.texts.ros_question == "{symptom}도 있나요?",
                order=order + index, priority=900000 - index))

    def clarify(self, state: WorkflowState, original: Question | None = None) -> bool:
        session = state.session
        if (session.clarifications >= 2 or session.finalizing or session.calls_left() < 2
                or session.usage[session.current].actions >= session.limits[session.current].actions
                or session.turns_remaining == 0):
            return False
        session.clarifications += 1
        if original and (original.kind == "EXAM" or original.field.startswith("P.")):
            original = None
        values = original.model_dump() if original else {"field": "S.ros" if state.case.chief_complaints() else "S.cc"}
        values.update(item_id=f"{session.current}:clarification:{session.clarifications}", kind="SAY",
                      purpose="clarification", text=self.config.texts.clarification_question,
                      order=-session.clarifications, priority=2000000)
        self.add_question(state, Question(**values))
        return True

    def prepare_education(self, state: WorkflowState, *, replace=False, create_questions=True) -> None:
        remaining = [q for q in state.questions.questions if q.purpose == "education"
                     and (item := state.case.get(q.item_id)) and item.status == "unasked"]
        capacity = len(remaining) if replace else max(0, state.session.limits["Education"].actions - state.session.usage["Education"].actions)
        if replace:
            removed = {q.item_id for q in remaining}
            state.case.remove(removed)
            state.questions.questions = [q for q in state.questions.questions if q.item_id not in removed]
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
                self.add_question(state, Question(item_id=f"Education:{selected or 'symptom'}:{order}", field="P.education",
                    purpose="education", text=text, order=order, priority=capacity - order))

    def collect_context(self, state: WorkflowState) -> None:
        contexts = {}
        for hypothesis in state.differential.hypotheses:
            for context in self.knowledge.get_supporting_context(hypothesis.disease_id):
                entry = contexts.setdefault(context["id"], {"type": context["type"], "count": 0})
                entry["count"] += 1
        for order, (target, context) in enumerate(sorted(contexts.items(), key=lambda pair: (-pair[1]["count"], pair[0]))):
            kind = context["type"]
            subject = "family" if kind == "family_history" else "patient"
            if self.known(state, target, subject=subject):
                continue
            field = "S.fh" if subject == "family" else ("S.sh" if kind in {
                "social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh")
            self.add_question(state, Question(item_id=f"ContextFactor:{target}", field=field, purpose="context",
                target_id=target, subject=subject, text=self.knowledge.question(target),
                order=order, priority=context["count"]))

    def investigate(self, state: WorkflowState) -> None:
        options = []
        for rank, hypothesis in enumerate(state.differential.hypotheses):
            for pattern in self.knowledge.get_disease_patterns(hypothesis.disease_id):
                target = pattern["target"]
                for feature in self.knowledge.get_pattern_features(pattern["id"]):
                    characteristic = pattern["characteristic"] or feature["role"] == "characteristic"
                    options.append((rank, not characteristic, target, feature["attribute"] or ""))
        seen, methods_seen = set(), set()
        for rank, ordinary, target, attribute in sorted(options):
            attribute = attribute or None
            existing = [item.value for _, item in state.case.entries() if item.value and item.value.kind in {"symptom", "finding"}
                        and target in item.value.concept_ids and item.value.subject == "patient" and item.value.time_context != "past"]
            occurrences = [(value.observation_id, value.episode_id) for value in existing] or [(None, None)]
            for observation, episode in occurrences:
                key = (target, attribute, observation, episode)
                if key in seen or self.known(state, target, attribute, observation, episode):
                    continue
                seen.add(key)
                exam = self.knowledge.has_type(target, "ExamFinding")
                methods = self.knowledge.get_exam_methods(target) if exam else []
                method = methods[0] if methods else None
                if exam and (not method or (method["id"], episode) in methods_seen):
                    continue
                if method:
                    methods_seen.add((method["id"], episode))
                order = len(state.questions.questions)
                self.add_question(state, Question(item_id=f"DifferentialDiagnosis:{order}", field="O.exam" if exam else "S.ros",
                    kind="EXAM" if exam else "SAY", purpose="feature", target_id=target, attribute_id=attribute,
                    observation_id=observation, episode_id=episode,
                    text=method["text"] if method else self.knowledge.question(attribute or target, target),
                    order=order, priority=(len(state.differential.hypotheses) - rank) * 10 + int(not ordinary)))

    def select_question(self, state: WorkflowState) -> None:
        answered = {q.item_id for q in state.questions.questions if q.target_id and q.purpose != "clarification" and
                    (item := state.case.get(q.item_id)) and item.status == "unasked" and
                    self.known(state, q.target_id, q.attribute_id, q.observation_id, q.episode_id, q.subject)}
        state.case.remove(answered)
        state.questions.questions = [q for q in state.questions.questions if q.item_id not in answered]
        questions = [q for q in state.questions.questions
                     if (item := state.case.get(q.item_id)) and item.scope == state.session.current and item.status == "unasked"]
        if not questions:
            if state.case.unasked(state.session.current):
                state.stop("failed", "unplanned_unasked_record")
            return
        question = min(questions, key=lambda q: (q.order, q.item_id))
        state.interaction.selected = ActionSpec(question=question, content=question.text, request_id=str(uuid4()))
