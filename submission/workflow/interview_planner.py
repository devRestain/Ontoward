import hashlib
import json

from knowledge.graph import ClinicalKnowledge, Plan

from .clinical_reasoner import ClinicalReasoner
from .education import generate_plan
from .state.models import ClinicalValue, Question, RecordItem, WorkflowState
from .rules.limits import LIMITS, SESSION_INTERVIEW_LIMITS
from .rules.selection import QuestionEvaluation, QuestionPath, question_key, eligible
from .state.evidence import EvidenceIndex
from .rules.collection import INTAKE, HISTORY, ATTRIBUTE_CATEGORIES, CATEGORY_FIELDS, answered, slot_resolved, slot_records


class InterviewPlanner:
    def __init__(self, knowledge: ClinicalKnowledge, config, questions, interactions, budget, usage, model):
        self.knowledge = knowledge
        self.config = config
        self.questions = questions
        self.interactions = interactions
        self.budget = budget
        self.usage = usage
        self.model = model
        self.reasoner = ClinicalReasoner(knowledge)
        self.budget.knowledge = knowledge

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
        return (attribute is not None or len({value.status for value in values}) == 1) and all(
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

    def prepare_initiation(self, state):
        if not any(e.delivered and e.question and e.question.purpose == "greeting" for e in state.interaction.history):
            self.questions.register(state, Question(item_id="Initiation:greeting", field="S.hpi", purpose="greeting",
                text=self.config.texts.greeting, order=-1, priority=LIMITS.clarification_priority, coverage=True))
        self._prepare_common(state, INTAKE, self.config.texts.intake_questions, "intake", state.questions.intake)

    def _prepare_common(self, state, categories, texts, purpose, ledger):
        anchor = state.case.primary_chief
        for order, slot in enumerate(categories):
            if answered(state, slot):
                outcome = next((o for o in reversed(state.case.outcomes) if o.record_category == slot), None)
                ledger[slot] = ("acquired" if slot_resolved(state.case, slot) else
                                outcome.state if outcome and outcome.state not in {"mapped", "forced"} else "unknown")
                ident = f"{state.session.current}:{slot}"
                if (item := state.case.get(ident)) and item.status == "unasked":
                    self.questions.discard_unasked(state, {ident})
                continue
            ledger[slot] = "unasked"
            self.questions.register(state, Question(item_id=f"{state.session.current}:{slot}",
                purpose=purpose, field=CATEGORY_FIELDS[slot], text=texts[slot], order=order,
                priority=LIMITS.hpi_priority, coverage=True, record_category=slot,
                subject="family" if slot == "family_history" else "patient",
                observation_id=anchor.observation_id if anchor and slot in INTAKE else None,
                episode_id=anchor.episode_id if anchor and slot in INTAKE else None,
                answer_type="presence" if slot in {"course", "recurrence", "medical_history", "medication", "allergy", "family_history"} else "free_text"))

    def prepare_chief_complaint(self, state):
        anchor = state.case.select_primary()
        chief = state.case.chief(confirmed=True)
        if anchor is None or chief is None:
            original = None
            candidate = state.case.chief()
            if candidate and len(candidate.value.concept_ids) == 1:
                value = candidate.value
                spec = self._spec(state, value.concept_ids[0], observation=value.observation_id, episode=value.episode_id,
                                  field="S.cc", time_context=value.time_context)
                if spec:
                    original = Question(item_id="chief_confirmation", order=0, priority=1, clarifies_id=candidate.id, **spec)
            if not self.prepare_clarification(state, original, primary_choice=len(state.case.chief_complaints()) > 1):
                state.stop("failed", "primary_chief_unresolved")
            return False
        self.questions.discard_unasked(state, {q.item_id for q in state.questions.questions if q.primary_choice
            and (item := state.case.get(q.item_id)) and item.status == "unasked"})
        key = anchor.model_dump_json()
        if state.questions.chief_anchor_key != key:
            stale = {q.item_id for q in state.questions.questions if q.purpose not in {"clarification", "empathy"}
                     and (item := state.case.get(q.item_id)) and item.status == "unasked"}
            self.questions.discard_unasked(state, stale)
            state.questions.chief_anchor_key = key
            state.questions.chief_attributes = {}
            state.questions.chief_attribute_reasons = {}
            systems = self.knowledge.get_symptom_systems(anchor.target_id)
            state.questions.ros_targets = sorted({target for system in systems
                for target in self.knowledge.get_system_symptoms(system)} - {anchor.target_id})
            state.questions.ros_initialized = True
        timing = chief.value.time_context
        attributes = self.knowledge.get_symptom_attributes(anchor.target_id)
        specs = []
        for attribute in attributes:
            args = (state, anchor.target_id, attribute, anchor.observation_id, anchor.episode_id, "patient", timing)
            if self.has_resolved_evidence(*args):
                status = "acquired"
            elif any(o.state == "not_applicable" and o.target_id == anchor.target_id and o.attribute_id == attribute
                     for o in state.case.outcomes) or any(item.value.not_applicable for _, item in state.case.current_entries()
                     if item.status == "done" and item.source_refs and item.value and item.value.kind == "attribute"
                     and item.value.concept_ids == [anchor.target_id] and item.value.subject == "patient"
                     and item.value.time_context == timing and item.value.attribute_id == attribute
                     and item.value.observation_id == anchor.observation_id and item.value.episode_id == anchor.episode_id):
                status = "not_applicable"
            elif self.was_asked(*args):
                status = "unknown"
            else:
                spec = self._spec(state, anchor.target_id, attribute, anchor.observation_id, anchor.episode_id,
                                  purpose="hpi", field="S.hpi", time_context=timing)
                if spec is None or self._key(spec) in state.questions.blocked_keys:
                    status = "blocked_asset"
                    template = self.knowledge.question_contract(attribute, anchor.target_id)
                    state.questions.chief_attribute_reasons[attribute] = (
                        template.reason if template and template.reason else "unavailable_or_rejected_question")
                elif min(self.budget.action_capacity(state), self.budget.calls_left(state.session)) <= 1:
                    status = "budget_stopped"
                else:
                    status = "unasked"
                    specs.append(spec)
            state.questions.chief_attributes[attribute] = status
        ledger = state.questions.chief_attributes
        state.questions.chief_total = len(attributes)
        state.questions.chief_acquired = sum(s == "acquired" for s in ledger.values())
        state.questions.chief_processed = sum(s not in {"unasked", "budget_stopped"} for s in ledger.values())
        for order, spec in enumerate(specs):
            self._register(state, spec, order, LIMITS.hpi_priority - order)
        self.prepare_open_inquiry(state, len(specs))
        return True

    def prepare_open_inquiry(self, state, order):
        if not any(entry.delivered and entry.question and entry.question.purpose == "open_inquiry" for entry in state.interaction.history):
            self.questions.register(state, Question(item_id="ChiefComplaint:open", field="S.ros", purpose="open_inquiry",
                text=self.config.texts.open_question, order=order, priority=LIMITS.open_inquiry_priority))

    @staticmethod
    def open_done(state):
        return any(e.delivered and e.question and e.question.purpose == "open_inquiry" for e in state.interaction.history)

    def prepare_clarification(self, state, original=None, *, primary_choice=False):
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
        confirmation = original and original.field == "S.cc" and original.target_id and not original.attribute_id
        if confirmation:
            text = original.text
        if primary_choice:
            text = self.config.texts.primary_chief_question
            values = {"field": "S.cc", "primary_choice": True}
        values.update(item_id=f"{state.session.current}:clarification:{state.session.clarifications}", kind="SAY",
                      purpose="clarification", text=text, affirmative_presence=bool(confirmation and original.affirmative_presence),
                      answer_type=original.answer_type if confirmation else "free_text",
                      order=-state.session.clarifications, priority=LIMITS.clarification_priority)
        values["clarifies_id"] = (original.clarifies_id or original.item_id) if original else None
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
        if observation is None and purpose != "context":
            observation = "observation:" + hashlib.sha256(f"{target}:{episode}:current".encode()).hexdigest()[:24]
        return dict(target_id=target, attribute_id=attribute, observation_id=observation, episode_id=episode,
                    purpose=purpose, field=field or ("O.exam" if exam else "S.ros"),
                    kind="EXAM" if exam else "SAY", text=text, answer_type=answer_type,
                    affirmative_presence=affirmative and not attribute, subject=subject, time_context=time_context)

    _key = staticmethod(question_key)

    def _register(self, state, spec, order, priority):
        key = self._key(spec)
        if key in state.questions.blocked_keys:
            return
        ident = "question:" + hashlib.sha256(key.encode()).hexdigest()[:24]
        if spec["purpose"] == "clarification":
            ident += f":clarification:{state.session.clarifications}"
        self.questions.register(state, Question(item_id=ident, **spec, order=order, priority=priority))

    def _occurrences(self, state, target):
        values = [item.value for _, item in state.case.current_entries() if item.status == "done" and item.source_refs and item.value
                  and item.value.kind in {"symptom", "finding"} and target in item.value.concept_ids
                  and item.value.subject == "patient" and item.value.time_context != "past"]
        return list({(v.observation_id, v.episode_id, v.status, len(v.concept_ids)) for v in values})

    def _eligible(self, state, spec, *, future=False):
        if self._key(spec) in state.questions.blocked_keys:
            return False
        args = (state, spec["target_id"], spec["attribute_id"], spec["observation_id"], spec["episode_id"],
                spec["subject"], spec["time_context"])
        if self.has_resolved_evidence(*args):
            return False
        if any(v.status == "unknown" and v.kind != "text" and spec["target_id"] in v.concept_ids
               and v.attribute_id == spec["attribute_id"] and v.subject == spec["subject"]
               and v.time_context == spec["time_context"]
               and (spec["observation_id"] is None or v.observation_id == spec["observation_id"])
               and (spec["episode_id"] is None or v.episode_id == spec["episode_id"])
               for _, item in state.case.current_entries() if item.status == "done" and item.source_refs and (v := item.value)):
            return False
        if self.was_asked(*args):
            previous = [e for e in state.interaction.history if e.delivered and e.question
                        and e.question.semantic_key() == self._key(spec)]
            if (not previous or any(e.question.purpose == "clarification" for e in previous)
                    or not self.budget.can_clarify(state)
                    or any(state.questions.answer_outcomes.get(e.question.item_id) in {"unknown", "not_applicable", "unsupported", "nonclinical"}
                           for e in previous)):
                return False
            attribute = (spec["attribute_id"] or "").rsplit(":", 1)[-1]
            spec.update(purpose="clarification", text=self.config.texts.clarification_questions.get(
                attribute, self.config.texts.clarification_question), affirmative_presence=False)
            if not spec["attribute_id"]:
                spec["answer_type"] = "free_text"
        if spec["attribute_id"] and spec["kind"] == "SAY" and not future:
            return any(o == spec["observation_id"] and e == spec["episode_id"] and status == "present" and n == 1
                       for o, e, status, n in self._occurrences(state, spec["target_id"]))
        return True

    def _frontier(self, state, snapshot, disease_ids):
        knowledge, paths = self.knowledge, []
        anchor = snapshot.chief
        if anchor is None:
            return [], {}
        context_index = {}
        for item in snapshot.evidence.contexts:
            for concept in item.value.concept_ids:
                context_index.setdefault((concept, item.value.subject, item.value.time_context), []).append(item)
        match_index = {(m.pattern_id, m.observation_id, m.episode_id, m.time_context): m
                       for m in snapshot.pattern_matches.values()}
        chief_paths = {}
        for disease in disease_ids:
            for profile in knowledge.get_disease_patterns(disease):
                applies, _ = self.reasoner._applicability(profile.applicability, context_index)
                if applies == "contradicted":
                    continue
                occurrences = [item for _, item in snapshot.evidence.entries if item.value.kind in {"symptom", "finding"}
                    and item.value.concept_ids == [profile.target] and item.value.subject == "patient"
                    and item.value.time_context != "past"]
                unique = {(i.value.observation_id, i.value.episode_id, i.value.time_context): i for i in occurrences}
                scopes = ([(anchor.observation_id, anchor.episode_id, anchor.time_context)]
                          if profile.target == anchor.target_id else list(unique) or [(None, anchor.episode_id, "current")])
                for observation, episode, timing in scopes:
                    result = match_index.get((profile.id, observation, episode, timing))
                    if result and result.status == "contradicted":
                        continue
                    missing, impossible = {}, False
                    for condition in profile.applicability:
                        status, _ = self.reasoner._applicability([condition], context_index)
                        if status == "matched":
                            continue
                        kind = knowledge.get_context_type(condition.concept_id)
                        field = "S.fh" if condition.subject == "family" else "S.sh" if kind in {
                            "social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh"
                        spec = self._spec(state, condition.concept_id, purpose="context", field=field,
                            subject=condition.subject, time_context=condition.time_context)
                        if not spec or not self._eligible(state, spec, future=True):
                            impossible = True
                            break
                        missing[self._key(spec)] = spec
                    unresolved = set(result.unresolved) if result else {f.id for f in knowledge.get_pattern_features(profile.id)}
                    target_present = any(i.value.status == "present" and len(i.value.concept_ids) == 1 for i in unique.values()
                        if i.value.observation_id == observation and i.value.episode_id == episode)
                    attributes = [f for f in knowledge.get_pattern_features(profile.id) if f.id in unresolved and f.attribute]
                    features = [f for f in knowledge.get_pattern_features(profile.id) if f.id in unresolved and not f.attribute]
                    if attributes and not target_present and not knowledge.has_type(profile.target, "ExamFinding"):
                        features = [None, *features]
                    ordered = [(None, "feature")] if features else []
                    ordered += [(f.attribute, "feature") for f in attributes]
                    for attribute, purpose in ordered:
                        spec = self._spec(state, profile.target, attribute, observation, episode, purpose=purpose,
                                          time_context=timing)
                        if not spec or not self._eligible(state, spec, future=True):
                            impossible = True
                            break
                        missing[self._key(spec)] = spec
                    if impossible or not missing:
                        continue
                    specs = tuple(missing.values())
                    path = QuestionPath(specs, profile, disease, profile.id, tuple(result.evidence_ids if result else [anchor.record_id]))
                    if len(specs) <= knowledge.reasoning.plan_questions:
                        paths.append(path)
                        if profile.target == anchor.target_id:
                            chief_paths.setdefault(disease, []).append(path)
            hypothesis = next((h for h in snapshot.hypotheses if h.disease_id == disease), None)
            if hypothesis and hypothesis.context_bonus:
                continue
            for context in knowledge.get_supporting_context(disease):
                subject = "family" if context["type"] == "family_history" else "patient"
                field = "S.fh" if subject == "family" else "S.sh" if context["type"] in {
                    "social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh"
                spec = self._spec(state, context["id"], purpose="context", field=field,
                                  subject=subject, time_context="unspecified")
                if spec and self._eligible(state, spec):
                    paths.append(QuestionPath((spec,), None, disease, None, (anchor.record_id,)))
        return paths, chief_paths

    def _comparison(self, snapshot, chief_paths):
        policy = self.knowledge.reasoning
        compatible = {h.disease_id for h in snapshot.hypotheses if h.chief_coverage == 1} | set(chief_paths)
        ranked = sorted((h for h in snapshot.hypotheses if h.chief_coverage == 1),
                        key=lambda h: (not eligible(h), -h.score, -h.chief_score, h.disease_id))
        selected = [h.disease_id for h in ranked[:policy.comparison_current]]
        potential = sorted(chief_paths, key=lambda d: (
            min(len(p.specs) for p in chief_paths[d]),
            -max(p.profile.score for p in chief_paths[d]), d))
        def structure(disease):
            return tuple(sorted(tuple(question_key(s) for s in p.specs) for p in chief_paths.get(disease, [])))
        seen, count = {structure(d) for d in selected}, 0
        for disease in potential:
            signature = structure(disease)
            if disease not in selected and signature not in seen:
                selected.append(disease)
                seen.add(signature)
                count += 1
                if count >= policy.comparison_potential:
                    break
        return selected, compatible

    def _allowed_now(self, state, spec):
        if not self._eligible(state, spec):
            return False
        if state.session.current == "ChiefComplaint":
            if self.knowledge.has_type(spec["target_id"], "ContextFactor") or spec["kind"] == "EXAM":
                return False
            if spec["attribute_id"]:
                return True
            delivered = sum(e.delivered and e.question and e.question.purpose == "ros" for e in state.interaction.history)
            if spec["target_id"] not in state.questions.ros_targets or delivered >= LIMITS.focused_ros:
                return False
            spec["purpose"] = "ros"
        return True

    def _plan_fits(self, state, path):
        if sum(s["purpose"] == "clarification" for s in path.specs) > LIMITS.clarifications - state.session.clarifications:
            return False
        capacity = min(self.budget.shared_action_capacity(state), self.budget.calls_left(state.session))
        if len(path.specs) > capacity:
            return False
        current = self.budget.action_capacity(state)
        future = 0
        if state.session.current in {"ChiefComplaint", "ContextFactor"}:
            future += SESSION_INTERVIEW_LIMITS["DifferentialDiagnosis"][1] - (
                state.session.usage["DifferentialDiagnosis"].actions - state.session.usage["DifferentialDiagnosis"].empathy_actions)
        return len(path.specs) <= current + future

    def replan(self, state, *, force=False):
        if state.interaction.pending or state.interaction.termination or state.session.current == "Education":
            return
        if state.session.current == "Initiation":
            self.prepare_initiation(state)
            return
        if state.case.chief(confirmed=True) is None:
            self.prepare_chief_complaint(state)
            return
        anchor = self.reasoner.anchor(state.case)
        collection_due = (anchor.model_dump_json() != state.questions.chief_anchor_key
                          or not self.open_done(state) or "unasked" in state.questions.chief_attributes.values())
        if state.session.current == "ChiefComplaint" and collection_due:
            self.prepare_chief_complaint(state)
            state.session.questions_prepared = state.case.chief(confirmed=True) is not None
            if not self.open_done(state) or "unasked" in state.questions.chief_attributes.values():
                return
        mode = state.session.current
        if mode == "ContextFactor" and self._prepare_context_coverage(state):
            return
        plan_key = json.dumps([state.differential.clinical_revision, state.questions.revision,
            len(state.interaction.history), state.case.primary_chief.model_dump() if state.case.primary_chief else None,
            mode, self.budget.action_capacity(state), self.budget.calls_left(state.session)], sort_keys=True)
        if not force and plan_key == state.questions.last_plan_key:
            return
        discard = {q.item_id for q in state.questions.questions if q.purpose != "empathy"
                   and (item := state.case.get(q.item_id)) and item.status == "unasked"}
        self.questions.discard_unasked(state, discard)
        snapshot = self.reasoner.evaluate(EvidenceIndex.from_case(state.case), self.reasoner.anchor(state.case))
        recalled = [h.disease_id for h in snapshot.hypotheses]
        all_paths, chief_paths = self._frontier(state, snapshot, recalled)
        candidates, compatible = self._comparison(snapshot, chief_paths)
        selected, assessments, used, limited = None, {}, 0, False
        for cohort in (candidates, sorted(compatible)):
            paths = [p for p in all_paths if p.disease_id in cohort and self._plan_fits(state, p)]
            specs = {}
            for path in sorted(paths, key=lambda p: (len(p.specs), p.disease_id, p.pattern_id or "")):
                spec = dict(path.specs[0])
                if self._allowed_now(state, spec):
                    specs[self._key(spec)] = spec
            paths = [p for p in paths if self._key(p.specs[0]) in specs]
            if not specs:
                continue
            evaluation = QuestionEvaluation(self.reasoner, snapshot, cohort)
            if used:
                evaluation.used = used
            assessments = evaluation.assess(specs, paths)
            used, limited = evaluation.used, evaluation.limited or any(not a["complete"] for a in assessments.values())
            positive = [(key, value) for key, value in assessments.items() if value["complete"] and (value["utility"] or 0) > 0]
            positive.sort(key=lambda pair: (-pair[1]["utility"], specs[pair[0]]["purpose"] == "clarification", pair[0]))
            if positive:
                key, value = positive[0]
                selected = dict(specs[key], assessment=value)
                break
            if used >= self.knowledge.reasoning.simulation_limit or cohort == sorted(compatible):
                break
        reason = "selected" if selected else "computation_limit" if limited else "no_useful_question"
        summaries = sorted(({"key": key, **{k: a[k] for k in ("utility", "complete", "direct_value", "plan_value")}}
                            for key, a in assessments.items()), key=lambda a: (-(a["utility"] or 0), a["key"]))
        for summary in summaries:
            summary["reason"] = ("selected" if selected and summary["key"] == self._key(selected) else
                "incomplete_evaluation" if not summary["complete"] else
                "zero_decision_value" if not (summary["utility"] or 0) > 0 else "lower_value_or_stable_tie")
        state.questions.selection_report = {"policy_version": self.knowledge.reasoning.version, "reason": reason,
            "comparison": cohort if candidates else [], "retrieved": len(recalled), "simulations": used,
            "limited": limited, "top": summaries[:3]}
        if selected:
            selected["assessment"]["selection"] = state.questions.selection_report.copy()
        if selected and mode == "ContextFactor" and not self.knowledge.has_type(selected["target_id"], "ContextFactor"):
            state.questions.selection_report["reason"] = "advance_to_diagnostic_acquisition"
        elif selected:
            if selected["purpose"] == "clarification":
                self.usage.record_clarification(state)
            self._register(state, selected, 0, 1)
        state.questions.last_plan_key = plan_key
        state.questions.last_planned_revision = state.differential.clinical_revision
        state.questions.last_planned_scope = mode

    def prepare_context_questions(self, state):
        self.replan(state, force=True)

    def _prepare_context_coverage(self, state):
        self._prepare_common(state, HISTORY, self.config.texts.history_questions, "history", state.questions.history)
        if any(q.purpose == "history" for q in state.pending_questions()):
            return True
        if len(state.questions.context_coverage) >= 2:
            return False
        anchor = state.case.primary_chief
        if anchor is None:
            return False
        snapshot = self.reasoner.evaluate(EvidenceIndex.from_case(state.case), anchor)
        profiles = self.knowledge.get_patterns_by_target(anchor.target_id)
        specs, paths, prerequisites = {}, [], set()
        for profile in profiles:
            contexts = [(c.concept_id, c.subject, c.time_context, True) for c in profile.applicability]
            contexts += [(c["id"], "family" if c["type"] == "family_history" else "patient", "unspecified", False)
                for c in self.knowledge.get_supporting_context(profile.disease_id)]
            for target, subject, timing, prerequisite in contexts:
                exclusion_key = f"{target}|{subject}|{timing}"
                if target in state.questions.context_coverage or self.was_asked(state, target, subject=subject, time_context=timing):
                    state.questions.context_exclusions[exclusion_key] = "already_asked"
                    continue
                kind = self.knowledge.get_context_type(target)
                field = "S.fh" if subject == "family" else "S.sh" if kind in {
                    "social_history", "occupational_history", "psychosocial_history", "demographic"} else "S.pmh"
                spec = self._spec(state, target, purpose="context", field=field, subject=subject, time_context=timing)
                if not spec:
                    state.questions.context_exclusions[exclusion_key] = "blocked_asset"
                    continue
                if not self._eligible(state, spec):
                    resolved = self.has_resolved_evidence(state, target, subject=subject, time_context=timing)
                    state.questions.context_exclusions[exclusion_key] = "resolved" if resolved else "unknown_or_not_applicable_or_blocked"
                    continue
                state.questions.context_exclusions.pop(exclusion_key, None)
                key = self._key(spec)
                specs[key] = dict(spec, coverage=True)
                if prerequisite:
                    prerequisites.add(key)
                paths.append(QuestionPath((spec,), None, profile.disease_id, None, (anchor.record_id,)))
        if not specs:
            state.questions.session_endings["ContextFactor"] = "no_available_unanswered_context"
            return False
        assessments = QuestionEvaluation(self.reasoner, snapshot, sorted({p.disease_id for p in paths})).assess(specs, paths)
        previous = {self.knowledge.get_context_type(c) for c in state.questions.context_coverage}
        key = min(specs, key=lambda key: (key not in prerequisites,
            -(assessments[key].get("utility") or 0), self.knowledge.get_context_type(specs[key]["target_id"]) in previous, key))
        spec = specs[key]
        spec["assessment"] = assessments[key]
        state.questions.selection_report = {"policy_version": self.knowledge.reasoning.version,
            "reason": "required_context_coverage", "target": spec["target_id"],
            "utility": assessments[key].get("utility"), "complete": assessments[key]["complete"]}
        self._register(state, spec, 0, LIMITS.hpi_priority)
        return True

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
        unnecessary = {q.item_id for q in state.questions.questions if q.assessment and not q.coverage
            and (item := state.case.get(q.item_id)) and item.status == "unasked"
            and (not q.assessment.get("complete") or not (q.assessment.get("utility") or 0) > 0)}
        self.questions.discard_unasked(state, unnecessary)
        redundant = {q.item_id for q in state.pending_questions() if q.record_category and slot_resolved(state.case, q.record_category)}
        self.questions.discard_unasked(state, redundant)
        answered = {q.item_id for q in state.questions.questions if q.target_id and q.purpose != "clarification" and
                    (item := state.case.get(q.item_id)) and item.status == "unasked" and (
                    self.has_resolved_evidence(state, q.target_id, q.attribute_id, q.observation_id, q.episode_id, q.subject,
                        q.time_context)
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
