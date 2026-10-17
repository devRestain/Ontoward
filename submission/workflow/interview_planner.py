import hashlib
import json

from knowledge.graph import ClinicalKnowledge, OW, Plan

from .clinical_reasoner import ClinicalReasoner
from .education import generate_plan
from .state.models import ClinicalValue, Question, RecordItem, WorkflowState
from .rules.limits import LIMITS


class InterviewPlanner:
    def __init__(self, knowledge: ClinicalKnowledge, config, questions, interactions, budget, usage, model):
        self.knowledge = knowledge
        self.config = config
        self.questions = questions
        self.interactions = interactions
        self.budget = budget
        self.usage = usage
        self.model = model

    @staticmethod
    def has_resolved_evidence(state: WorkflowState, target, attribute=None, observation=None, episode=None,
                              subject="patient", time_context=None):
        values = [item.value for _, item in state.case.current_entries() if item.status == "done" and item.source_refs
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


    def prepare_initiation(self, state):
        self.questions.register(state, Question(item_id="Initiation:chief", field="S.cc", purpose="chief",
            text=self.config.texts.chief_question, order=0, priority=1))

    def prepare_chief_complaint(self, state):
        chiefs = state.case.chief_complaints()
        slots = ["Location", "Laterality", "quality", "TimeSinceOnset", "EpisodeDuration", "Severity"]
        order = 0
        for slot in slots:
            for chief in chiefs:
                value = chief.value
                if not value.concept_ids:
                    if slot == "Location":
                        self.questions.register(state, Question(item_id=f"ChiefComplaint:{chief.id}:location", field="S.hpi",
                            purpose="hpi", text=self.config.texts.unmapped_question, observation_id=value.observation_id,
                            episode_id=value.episode_id, order=order, priority=LIMITS.hpi_priority))
                        order += 1
                    continue
                for target in value.concept_ids:
                    attrs = self.knowledge.get_symptom_attributes(target)
                    attribute = str(OW.PainQuality if str(OW.PainQuality) in attrs else OW.Quality) if slot == "quality" else str(OW[slot])
                    if attribute not in attrs or self._covered(state, target, attribute, value.observation_id, value.episode_id):
                        continue
                    spec = self._spec(state, target, attribute, value.observation_id, value.episode_id, purpose="hpi", field="S.hpi")
                    if spec:
                        self._register(state, spec, order, LIMITS.hpi_priority - order)
                        order += 1
        self.prepare_open_inquiry(state, order)
        if not state.questions.ros_initialized:
            targets = {target for item in state.case.chief_complaints(confirmed=True) for target in item.value.concept_ids}
            systems = {system for target in targets for system in self.knowledge.get_symptom_systems(target)}
            state.questions.ros_targets = sorted({t for system in systems for t in self.knowledge.get_system_symptoms(system)} - targets)
            state.questions.ros_initialized = True

    def prepare_open_inquiry(self, state, order):
        if not any(entry.delivered and entry.question and entry.question.purpose == "open_inquiry" for entry in state.interaction.history):
            self.questions.register(state, Question(item_id="ChiefComplaint:open", field="S.ros", purpose="open_inquiry",
                text=self.config.texts.open_question, order=order, priority=LIMITS.open_inquiry_priority))

    @staticmethod
    def open_done(state):
        return any(e.delivered and e.question and e.question.purpose == "open_inquiry" for e in state.interaction.history)

    def prepare_clarification(self, state, original=None):
        if not self.budget.can_clarify(state):
            return False
        if any(q.purpose == "clarification" and (item := state.case.get(q.item_id)) and item.status == "unasked"
               for q in state.questions.questions):
            return True
        self.usage.record_clarification(state)
        if original and (original.kind == "EXAM" or original.field.startswith("P.")):
            original = None
        values = original.model_dump() if original else {
            "field": "S.cc" if not state.differential.hypotheses and state.session.current != "Education" else "S.ros"}
        attribute = (original.attribute_id or "").rsplit(":", 1)[-1] if original else ""
        text = self.config.texts.clarification_questions.get(attribute, self.config.texts.clarification_question)
        values.update(item_id=f"{state.session.current}:clarification:{state.session.clarifications}", kind="SAY",
                      purpose="clarification", text=text, affirmative_presence=False, answer_type="free_text",
                      order=-state.session.clarifications, priority=LIMITS.clarification_priority)
        self.questions.register(state, Question(**values))
        return True

    def _spec(self, state, target, attribute=None, observation=None, episode=None, *, purpose="feature", field=None,
              subject="patient", time_context="current"):
        exam = self.knowledge.has_type(target, "ExamFinding")
        if exam:
            methods = self.knowledge.get_exam_methods(target)
            if not methods:
                return None
            text, answer_type, affirmative = methods[0]["text"], "free_text", False
        else:
            template = self.knowledge.question_contract(attribute or target, target)
            if template is None or not template.interviewable:
                issue = f"unavailable_question:{target}:{attribute or ''}"
                if issue not in state.interaction.issues:
                    state.interaction.issues.append(issue)
                return None
            text = self.knowledge.question(attribute or target, target)
            answer_type, affirmative = template.answer_type, template.affirmative
        return dict(target_id=target, attribute_id=attribute, observation_id=observation, episode_id=episode,
                    purpose=purpose, field=field or ("O.exam" if exam else "S.ros"),
                    kind="EXAM" if exam else "SAY", text=text, answer_type=answer_type,
                    affirmative_presence=affirmative and not attribute, subject=subject, time_context=time_context)

    @staticmethod
    def _key(spec):
        return json.dumps([spec["kind"], spec["target_id"], spec["attribute_id"], spec["subject"],
                           spec["time_context"], spec["observation_id"], spec["episode_id"]], separators=(",", ":"))

    def _register(self, state, spec, order, priority):
        key = self._key(spec)
        if key in state.questions.blocked_keys:
            return
        ident = "question:" + hashlib.sha256(key.encode()).hexdigest()[:24]
        selection_value = spec.get("value", [])
        spec = {k: v for k, v in spec.items() if k != "value"}
        self.questions.register(state, Question(item_id=ident, **spec, order=order, priority=priority, selection_value=selection_value))

    def _occurrences(self, state, target):
        values = [item.value for _, item in state.case.current_entries() if item.status == "done" and item.source_refs and item.value
                  and item.value.kind in {"symptom", "finding"} and target in item.value.concept_ids
                  and item.value.subject == "patient" and item.value.time_context != "past"]
        return list({(v.observation_id, v.episode_id, v.status, len(v.concept_ids)) for v in values})

    def _value(self, state, spec, match_index, supporting):
        target, attribute = spec["target_id"], spec["attribute_id"]
        current = {h.disease_id: h for h in state.differential.hypotheses}
        outcomes, unlock, typicality = {}, 0, 0
        leading = next(iter(current), None)
        if spec["purpose"] == "context":
            present = {(concept, item.value.subject) for _, item in state.case.current_entries()
                       if item.status == "done" and item.source_refs and item.value
                       and item.value.kind == "context" and item.value.status == "present"
                       for concept in item.value.concept_ids}
            for disease, contexts in supporting.items():
                keys = {(c["id"], "family" if c["type"] == "family_history" else "patient") for c in contexts}
                if (target, spec["subject"]) in keys and not keys & present:
                    outcomes.setdefault("supporting_context", {})[disease] = [1]
                    unlock = 1
        profiles = self.knowledge.get_patterns_by_target(target)
        if spec["purpose"] == "context":
            profiles = [p for disease in current for p in self.knowledge.get_disease_patterns(disease)
                        if any(c.concept_id == target and c.subject == spec["subject"] for c in p.applicability)]
        for profile in profiles:
            if profile.disease_id not in current:
                continue
            features = self.knowledge.get_pattern_features(profile.id)
            relevant = [f for f in features if f.attribute == attribute]
            if spec["purpose"] == "context":
                relevant = features
            if not relevant:
                continue
            results = [m for m in match_index.get(profile.id, [])
                       if (not spec["observation_id"] or m.observation_id == spec["observation_id"])
                       and (not spec["episode_id"] or m.episode_id == spec["episode_id"])]
            unknown = min((len(m.unresolved) for m in results if m.status != "contradicted"), default=len(features))
            if spec["purpose"] == "context":
                unknown += sum(not self.has_resolved_evidence(state, c.concept_id, subject=c.subject, time_context=c.time_context)
                               for c in profile.applicability)
            if results and all(m.status == "contradicted" for m in results):
                continue
            hypothesis = current[profile.disease_id]
            baseline = next((c.score for c in hypothesis.contributions if c.target_id == target), 0)
            change = profile.score - baseline
            unlock = max(unlock, abs(change) / max(1, unknown))
            typicality = max(typicality, self.knowledge.policy.labels.get(profile.typicality, 0))
            if unknown <= 1:
                for feature in relevant:
                    answer = repr(feature.signature())
                    outcomes.setdefault(answer, {}).setdefault(profile.disease_id, []).append(change)
        spread, rank_change = 0, False
        for changes in outcomes.values():
            deltas = {d: max(changes.get(d, [0]), key=abs) for d in current}
            spread = max(spread, max(deltas.values(), default=0) - min(deltas.values(), default=0))
            if leading:
                rank_change = rank_change or any(current[d].score + delta > current[leading].score + deltas[leading]
                                                 for d, delta in deltas.items() if d != leading)
        chiefs = {c for item in state.case.chief_complaints(confirmed=True) for c in item.value.concept_ids}
        return [float(rank_change), spread, unlock, float(target in chiefs), typicality]

    def _eligible(self, state, spec):
        target, attribute, observation, episode = spec["target_id"], spec["attribute_id"], spec["observation_id"], spec["episode_id"]
        if self._key(spec) in state.questions.blocked_keys:
            return False
        if self._covered(state, target, attribute, observation, episode, spec["subject"], spec["time_context"]):
            return False
        if attribute and spec["kind"] != "EXAM":
            return any(o == observation and e == episode and status == "present" and n == 1
                       for o, e, status, n in self._occurrences(state, target))
        return True

    def _useful(self, state, purpose, value):
        if purpose in {"chief", "open_inquiry", "clarification", "education", "empathy"}:
            return True
        if purpose == "hpi" and not self.open_done(state):
            return True
        if not any(number > 0 for number in value[:3]):
            return False
        if self.budget.interview_actions(state) < self.budget.interview_limits(state)[0]:
            return True
        return value[0] > 0 or value[1] > 0 or (not ClinicalReasoner.supported_hypotheses(state) and value[2] > 0)

    def _adaptive_options(self, state, supporting):
        options = {}
        chiefs = state.case.chief_complaints(confirmed=True)
        episode = chiefs[0].value.episode_id if len(chiefs) == 1 else None
        targets = {}
        hypotheses = state.differential.hypotheses
        if state.session.current == "ChiefComplaint":
            delivered = sum(e.delivered and e.question is not None and e.question.purpose == "ros" for e in state.interaction.history)
            if delivered < LIMITS.focused_ros:
                for target in state.questions.ros_targets:
                    targets[target] = "ros"
            for chief in chiefs:
                for target in chief.value.concept_ids:
                    targets[target] = "hpi"
        else:
            contexts = {}
            for hypothesis in hypotheses:
                for context in supporting[hypothesis.disease_id]:
                    contexts[(context["id"], "family" if context["type"] == "family_history" else "patient", "unspecified")] = True
                for profile in self.knowledge.get_disease_patterns(hypothesis.disease_id):
                    for condition in profile.applicability:
                        contexts[(condition.concept_id, condition.subject, condition.time_context)] = True
                    targets[profile.target] = "feature"
            for (target, subject, timing) in contexts:
                kind = self.knowledge.get_context_type(target)
                field = "S.fh" if subject == "family" else "S.sh" if kind in {
                    "social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh"
                spec = self._spec(state, target, purpose="context", field=field, subject=subject, time_context=timing)
                if spec:
                    options[self._key(spec)] = spec
        for target, purpose in sorted(targets.items()):
            occurrences = self._occurrences(state, target)
            exam = self.knowledge.has_type(target, "ExamFinding")
            if not occurrences or exam:
                spec = self._spec(state, target, episode=episode, purpose=purpose if purpose != "hpi" else "feature")
                if spec:
                    options[self._key(spec)] = spec
            for observation, occurrence, status, n in sorted(occurrences, key=str):
                if status == "uncertain" or n != 1:
                    is_chief = any(item.value.observation_id == observation and item.value.episode_id == occurrence
                                   and target in item.value.concept_ids for item in state.case.chief_complaints())
                    spec = self._spec(state, target, observation=observation, episode=occurrence,
                                      purpose="feature", field="S.cc" if is_chief else None)
                    if spec:
                        options[self._key(spec)] = spec
                if status != "present" or n != 1:
                    continue
                for attribute in self.knowledge.get_symptom_attributes(target):
                    spec = self._spec(state, target, attribute, observation, occurrence, purpose=purpose if purpose == "hpi" else "feature",
                                      field="S.hpi" if purpose == "hpi" else None)
                    if spec:
                        options[self._key(spec)] = spec
        return list(options.values())

    def replan(self, state, *, force=False):
        if state.interaction.pending or state.interaction.termination or state.session.current in {"Initiation", "Education"}:
            return
        if state.session.current == "ChiefComplaint" and not self.open_done(state):
            return
        mode = state.session.current
        if not force and (state.questions.last_planned_revision, state.questions.last_planned_scope) == (state.differential.clinical_revision, mode):
            return
        discard = {q.item_id for q in state.questions.questions if q.purpose not in {"clarification", "empathy"}
                   and (item := state.case.get(q.item_id)) and item.status == "unasked"}
        self.questions.discard_unasked(state, discard)
        supporting = {h.disease_id: self.knowledge.get_supporting_context(h.disease_id)
                      for h in state.differential.hypotheses}
        raw_options = self._adaptive_options(state, supporting)
        options = [spec for spec in raw_options if self._eligible(state, spec)]
        match_index = {}
        for match in state.differential.pattern_matches.values():
            match_index.setdefault(match.pattern_id, []).append(match)
        for spec in options:
            spec["value"] = self._value(state, spec, match_index, supporting)
        options = [spec for spec in options if self._useful(state, spec["purpose"], spec["value"])]
        if state.session.current == "DifferentialDiagnosis":
            for spec in raw_options:
                args = (state, spec["target_id"], spec["attribute_id"], spec["observation_id"], spec["episode_id"], spec["subject"])
                if not self.has_resolved_evidence(*args) and self.was_asked(*args):
                    previous = [entry.question for entry in state.interaction.history if entry.delivered and entry.question
                                and entry.question.target_id == spec["target_id"] and entry.question.attribute_id == spec["attribute_id"]
                                and entry.question.subject == spec["subject"]
                                and (not spec["observation_id"] or entry.question.observation_id == spec["observation_id"])
                                and (not spec["episode_id"] or entry.question.episode_id == spec["episode_id"])]
                    if previous and not any(q.purpose == "clarification" for q in previous):
                        self.prepare_clarification(state, previous[-1])
                        break
        options.sort(key=lambda spec: (*(-n for n in spec["value"]), spec["purpose"] == "context", self._key(spec)))
        if mode == "ContextFactor":
            # Continue with diagnostic acquisition as soon as it has greater utility.
            next_feature = next((i for i, spec in enumerate(options) if spec["purpose"] != "context"), len(options))
            options = options[:next_feature]
        capacity = min(self.budget.action_capacity(state), self.budget.calls_left(state.session))
        if mode == "ChiefComplaint":
            ros_left = LIMITS.focused_ros - sum(e.delivered and e.question is not None and e.question.purpose == "ros" for e in state.interaction.history)
            retained, ros_count = [], 0
            for spec in options:
                if spec["purpose"] == "ros":
                    if ros_count >= ros_left:
                        continue
                    ros_count += 1
                retained.append(spec)
            options = retained
        for order, spec in enumerate(options[:capacity]):
            self._register(state, spec, order, capacity - order)
        state.questions.last_planned_revision = state.differential.clinical_revision
        state.questions.last_planned_scope = mode

    def prepare_context_questions(self, state):
        self.replan(state, force=True)

    def prepare_differential_questions(self, state):
        self.replan(state, force=True)

    def prepare_education(self, state, client):
        if self.config.education_enabled:
            generate_plan(state, client, self.knowledge, self.config, self.model)
            return
        state.interaction.education.status = "disabled"
        if "education_skipped" not in state.interaction.issues:
            state.interaction.issues.append("education_skipped")
        selected = state.differential.selected_id
        if state.case.diagnosis_kind == "symptom":
            plan = Plan(education=[self.config.texts.symptom_education])
        elif selected:
            plan = self.knowledge.plans.get(selected, Plan())
            if selected not in self.knowledge.plans and f"missing_plan:{selected}" not in state.interaction.issues:
                state.interaction.issues.append(f"missing_plan:{selected}")
        else:
            state.stop("failed", "diagnosis_missing")
            return
        for field in ("tests", "treatment", "disposition", "follow_up", "education"):
            text = getattr(plan, field)
            if field == "tests" and not text and selected:
                text = self.config.texts.test_separator.join(self.knowledge.get_planned_tests(selected))
            elif field == "education":
                text = self.config.texts.record_separator.join(text) if self.config.education_enabled else ""
            item_id = f"plan:{field}"
            state.case.remove({item_id})
            if text:
                state.case.put(f"P.{field}", RecordItem(id=item_id, scope="Education", status="done",
                    value=ClinicalValue(kind="plan", text=text, status="present", concept_ids=[selected] if selected else [])))

    def select_question(self, state):
        if state.session.current == "Education":
            questions = state.pending_questions()
            if questions:
                self.interactions.select_question(state, min(questions, key=lambda q: (-q.priority, q.order, q.item_id)))
                state.interaction.selected.render_source = "education"
            return
        unnecessary = {q.item_id for q in state.questions.questions
                       if (item := state.case.get(q.item_id)) and item.scope == state.session.current
                       and item.status == "unasked" and not self._useful(state, q.purpose, q.selection_value)}
        self.questions.discard_unasked(state, unnecessary)
        answered = {q.item_id for q in state.questions.questions if q.target_id and q.purpose != "clarification" and
                    (item := state.case.get(q.item_id)) and item.status == "unasked" and (
                    self.has_resolved_evidence(state, q.target_id, q.attribute_id, q.observation_id, q.episode_id, q.subject,
                        None if q.time_context == "unspecified" else q.time_context)
                    or (q.attribute_id and q.kind == "SAY" and not any(
                        o == q.observation_id and e == q.episode_id and status == "present" and n == 1
                        for o, e, status, n in self._occurrences(state, q.target_id))))}
        self.questions.discard_unasked(state, answered)
        questions = [q for q in state.questions.questions
                     if (item := state.case.get(q.item_id)) and item.scope == state.session.current and item.status == "unasked"]
        if not questions:
            if state.case.unasked(state.session.current):
                state.stop("failed", "unplanned_unasked_record")
            return
        self.interactions.select_question(state, min(questions, key=lambda q: (q.order, q.item_id)))
