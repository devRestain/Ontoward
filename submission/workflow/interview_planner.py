import hashlib

from .audit import emit
from .education import generate_plan
from .state.models import PlanSentence, Question
from .rules.collection import INTAKE, HISTORY, ATTRIBUTE_CATEGORIES, answered, slot_resolved
from .rules.limits import LIMITS, SESSION_INTERVIEW_LIMITS
from .rules.selection import QuestionEvaluation, QuestionPath, eligible, question_key


class InterviewPlanner:
    def __init__(self, knowledge, config, questions, interactions, budget, usage, model, reasoner, audit=None):
        self.knowledge, self.config = knowledge, config
        self.questions, self.interactions = questions, interactions
        self.budget, self.usage, self.model = budget, usage, model
        self.reasoner, self.audit, self._last_plan_key = reasoner, audit, None

    def has_resolved_evidence(self, state, target, attribute=None, observation=None, episode=None,
                              subject='patient', time_context=None):
        target = self.knowledge.term(target) if target.startswith(('urn:', 'http')) else target
        attribute = self.knowledge.term(attribute) if attribute and attribute.startswith(('urn:', 'http')) else attribute
        values = [f for f in state.case.current_facts() if f.target == target and f.attribute == attribute
            and f.subject == subject and (time_context is not None or f.kind == 'context' or f.time_context != 'past')
            and (observation is None or f.observation_id == observation)
            and (episode is None or f.episode_id == episode)
            and (time_context is None or f.time_context == time_context)]
        values = [f for f in values if f.status in {'present', 'absent'}]
        return bool(values) and (attribute is not None or len({f.status for f in values}) == 1)

    def was_asked(self, state, target, attribute=None, observation=None, episode=None,
                  subject='patient', time_context=None):
        target = self.knowledge.term(target) if target.startswith(('urn:', 'http')) else target
        attribute = self.knowledge.term(attribute) if attribute and attribute.startswith(('urn:', 'http')) else attribute
        for answer in state.interview.answers:
            if not answer.key or answer.outcome == 'undelivered':
                continue
            _, t, a, s, timing, observed, occurrence = answer.key
            if (t, a or None, s) != (target, attribute, subject):
                continue
            scopes = [(observed, occurrence, timing)]
            scopes.extend((f.observation_id, f.episode_id, f.time_context) for ident in answer.fact_ids
                          if (f := state.case.facts.get(ident)) and f.target == target and f.attribute == attribute)
            if any((observation is None or o == observation) and (episode is None or e == episode)
                   and (time_context is None or t == time_context) for o,e,t in scopes):
                return True
        return False

    def prepare_initiation(self, state):
        if not any(a.purpose == 'greeting' and a.outcome != 'undelivered' for a in state.interview.answers):
            self.questions.register(state, Question(item_id='Initiation:greeting', purpose='greeting',
                text=self.config.texts.greeting, order=-1, priority=LIMITS.clarification_priority, coverage=True))
        self._prepare_common(state, INTAKE, self.config.texts.intake_questions, 'intake')

    def _prepare_common(self, state, categories, texts, purpose):
        chief = state.case.chief()
        for order, slot in enumerate(categories):
            ident = f'{state.interview.current}:{slot}'
            if answered(state, slot):
                self.questions.discard_unasked(state, {ident}, reason='already_resolved')
                continue
            existing = next((q for q in state.interview.queue if q.item_id == ident), None)
            if existing and chief and slot in INTAKE and (existing.target, existing.observation_id, existing.episode_id) != (
                    chief.target, chief.observation_id, chief.episode_id):
                self.questions.discard_unasked(state, {ident}, reason='chief_changed')
            self.questions.register(state, Question(item_id=ident, purpose=purpose, text=texts[slot], order=order,
                priority=LIMITS.hpi_priority, coverage=True, category=slot,
                target=chief.target if chief and slot in INTAKE else None,
                observation_id=chief.observation_id if chief and slot in INTAKE else None,
                episode_id=chief.episode_id if chief and slot in INTAKE else None,
                subject='family' if slot == 'family_history' else 'patient',
                answer_type='presence' if slot in {'course', 'recurrence', 'medical_history', 'medication', 'allergy', 'family_history'} else 'free_text'))

    def chief_statuses(self, state):
        chief = state.case.chief(confirmed=True)
        if chief is None:
            return {}
        target = self.knowledge.term_id(chief.target, 'Symptom')
        statuses = {}
        for attribute in self.knowledge.get_symptom_attributes(target):
            name = self.knowledge.term(attribute)
            if self.has_resolved_evidence(state, target, attribute, chief.observation_id, chief.episode_id, 'patient', chief.time_context):
                statuses[name] = 'acquired'
                continue
            key = ('SAY', chief.target, name, 'patient', chief.time_context, chief.observation_id or '', chief.episode_id or '')
            answer = next((a for a in reversed(state.interview.answers) if a.key == key), None)
            statuses[name] = (('recorded_unmapped' if answer.outcome == 'recorded' else
                answer.outcome if answer.outcome in {'not_applicable', 'unsupported', 'conflict'} else 'unknown')
                if answer else state.interview.collection.get('|'.join(key), 'unasked'))
        return statuses

    def prepare_chief_complaint(self, state):
        chief = state.case.chief(confirmed=True)
        stale = {q.item_id for q in state.interview.queue if q.purpose in {'hpi', 'chief', 'open_inquiry'}
                 and q.target and (chief is None or (q.target, q.observation_id, q.episode_id, q.time_context) !=
                     (chief.target, chief.observation_id, chief.episode_id, chief.time_context))}
        self.questions.discard_unasked(state, stale, reason='chief_changed')
        if chief is None:
            candidate = state.case.chief()
            original = None
            if candidate:
                target = self.knowledge.term_id(candidate.target, 'Symptom')
                spec = self._spec(state, target, observation=candidate.observation_id,
                    episode=candidate.episode_id, purpose='chief', time_context=candidate.time_context)
                if spec:
                    original = self._question(spec, 'chief_confirmation', 0, LIMITS.clarification_priority)
                    original.clarifies_id = candidate.id
            if not self.prepare_clarification(state, original, primary_choice=len(state.case.chief_candidates()) > 1):
                state.stop('failed', 'primary_chief_unresolved')
            return False
        target = self.knowledge.term_id(chief.target, 'Symptom')
        for order, (name, status) in enumerate(self.chief_statuses(state).items()):
            if status != 'unasked':
                continue
            attribute = self.knowledge.term_id(name, 'FindingAttribute')
            spec = self._spec(state, target, attribute, chief.observation_id, chief.episode_id,
                              purpose='hpi', field='S.hpi', time_context=chief.time_context)
            key = '|'.join(('SAY', chief.target, name, 'patient', chief.time_context, chief.observation_id or '', chief.episode_id or ''))
            if spec is None:
                state.interview.collection[key] = 'blocked_asset'
            elif self.budget.action_capacity(state) <= 1:
                state.interview.collection[key] = 'budget_stopped'
            else:
                self._register(state, dict(spec, coverage=True), order, LIMITS.hpi_priority - order)
        if not self.open_done(state):
            self.questions.register(state, Question(item_id='ChiefComplaint:open', purpose='open_inquiry',
                text=self.config.texts.open_question, order=1000, priority=LIMITS.open_inquiry_priority))
        return True

    @staticmethod
    def open_done(state):
        return any(a.purpose == 'open_inquiry' and a.outcome != 'undelivered' for a in state.interview.answers)

    def prepare_clarification(self, state, original=None, *, primary_choice=False):
        if any(q.purpose == 'clarification' for q in state.interview.queue):
            return True
        if not self.budget.can_clarify(state):
            return False
        self.usage.record_clarification(state)
        values = original.model_dump() if original and original.kind == 'SAY' else {}
        attribute = self.knowledge.term_id(original.attribute, 'FindingAttribute') if original and original.attribute else None
        local = (attribute or '').rsplit(':', 1)[-1]
        text = self.config.texts.clarification_questions.get(local, self.config.texts.clarification_question)
        if original and original.target and not original.attribute:
            text = original.text
        if primary_choice:
            values = {'primary_choice':True}
            text = self.config.texts.primary_chief_question
        values.update(item_id=f'{state.interview.current}:clarification:{state.session.clarifications}',
            purpose='clarification', kind='SAY', text=text, order=-state.session.clarifications,
            priority=LIMITS.clarification_priority)
        self.questions.register(state, Question(**values))
        return True

    def _spec(self, state, target, attribute=None, observation=None, episode=None, *, purpose='feature', field=None,
              subject='patient', time_context='current'):
        exam = self.knowledge.has_type(target, 'ExamFinding')
        if exam:
            methods = self.knowledge.get_exam_methods(target)
            if not methods:
                return None
            text, answer_type, affirmative = methods[0]['text'], 'free_text', False
        else:
            template = self.knowledge.question_contract(attribute or target, target)
            if template is None or not template.interviewable:
                return None
            text = self.knowledge.question(attribute or target, target)
            answer_type, affirmative = template.answer_type, template.affirmative
        if observation is None and purpose != 'context':
            observation = 'observation:' + hashlib.sha256(f'{target}:{episode}:current'.encode()).hexdigest()[:24]
        return dict(target_id=target, attribute_id=attribute, observation_id=observation, episode_id=episode,
            purpose=purpose, field=field or ('O.exam' if exam else 'S.ros'), kind='EXAM' if exam else 'SAY', text=text,
            answer_type=answer_type, affirmative_presence=affirmative and not attribute, subject=subject, time_context=time_context)

    _key = staticmethod(question_key)

    def _question(self, spec, ident, order, priority):
        values = {k:v for k,v in spec.items() if k not in {'field', 'target_id', 'attribute_id', 'assessment'}}
        return Question(item_id=ident, target=self.knowledge.term(spec['target_id']),
            attribute=self.knowledge.term(spec['attribute_id']) if spec['attribute_id'] else None,
            category=ATTRIBUTE_CATEGORIES.get((spec['attribute_id'] or '').rsplit(':', 1)[-1]),
            order=order, priority=priority, **values)

    def _register(self, state, spec, order, priority):
        ident = 'question:' + hashlib.sha256(self._key(spec).encode()).hexdigest()[:24]
        if spec['purpose'] == 'clarification':
            ident += f':clarification:{state.session.clarifications}'
        self.questions.register(state, self._question(spec, ident, order, priority))

    def _occurrences(self, state, target):
        name = self.knowledge.term(target)
        return {(f.observation_id, f.episode_id, f.status) for f in state.case.current_facts()
                if f.target == name and f.kind in {'symptom', 'finding'} and f.subject == 'patient' and f.time_context != 'past'}

    def _eligible(self, state, spec, *, future=False):
        target, attribute = spec['target_id'], spec['attribute_id']
        args = (state, target, attribute, spec['observation_id'], spec['episode_id'], spec['subject'], spec['time_context'])
        if self.has_resolved_evidence(*args):
            return False
        key = (spec['kind'], self.knowledge.term(target), self.knowledge.term(attribute) if attribute else '',
               spec['subject'], spec['time_context'], spec['observation_id'] or '', spec['episode_id'] or '')
        if '|'.join(key) in state.interview.collection and state.interview.collection['|'.join(key)] in {'blocked_asset', 'budget_stopped'}:
            return False
        if self.was_asked(*args):
            prior = [a for a in state.interview.answers if a.key == key and a.outcome != 'undelivered']
            if not prior or any(a.purpose == 'clarification' or a.outcome in {'unknown','not_applicable','unsupported','nonclinical'}
                                for a in prior) or not self.budget.can_clarify(state):
                return False
            local = (attribute or '').rsplit(':', 1)[-1]
            spec.update(purpose='clarification', text=self.config.texts.clarification_questions.get(local,
                         self.config.texts.clarification_question), affirmative_presence=False)
        if attribute and spec['kind'] == 'SAY' and not future:
            return any(o == spec['observation_id'] and e == spec['episode_id'] and status == 'present'
                       for o,e,status in self._occurrences(state, target))
        return True

    def _frontier(self, state, snapshot, disease_ids):
        knowledge, paths = self.knowledge, []
        anchor = snapshot.chief
        if anchor is None:
            return [], {}
        context_index = {}
        for item in snapshot.evidence.contexts:
            for concept in (item.target,):
                context_index.setdefault((concept, item.subject, item.time_context), []).append(item)
        match_index = {(m.pattern_id, m.observation_id, m.episode_id, m.time_context): m
                       for m in snapshot.pattern_matches.values()}
        chief_paths = {}
        for disease in disease_ids:
            for profile in knowledge.get_disease_patterns(disease):
                applies, _ = self.reasoner._applicability(profile.applicability, context_index)
                if applies == "contradicted":
                    continue
                occurrences = [item for item in snapshot.evidence.entries if item.kind in {"symptom", "finding"}
                    and (item.target,) == (profile.target,) and item.subject == "patient"
                    and item.time_context != "past"]
                unique = {(i.observation_id, i.episode_id, i.time_context): i for i in occurrences}
                scopes = ([(anchor.observation_id, anchor.episode_id, anchor.time_context)]
                          if profile.target == anchor.target else list(unique) or [(None, anchor.episode_id, "current")])
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
                    target_present = any(i.status == "present" and len((i.target,)) == 1 for i in unique.values()
                        if i.observation_id == observation and i.episode_id == episode)
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
                    path = QuestionPath(specs, profile, disease, profile.id)
                    if len(specs) <= knowledge.reasoning.plan_questions:
                        paths.append(path)
                        if profile.target == anchor.target:
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
                    paths.append(QuestionPath((spec,), None, disease, None))
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
        if state.interview.current == 'ChiefComplaint':
            if self.knowledge.has_type(spec['target_id'], 'ContextFactor') or spec['kind'] == 'EXAM':
                return False
            if spec['attribute_id']:
                return True
            chief = state.case.chief(confirmed=True)
            systems = self.knowledge.get_symptom_systems(self.knowledge.term_id(chief.target, 'Symptom')) if chief else []
            targets = {t for system in systems for t in self.knowledge.get_system_symptoms(system)}
            delivered = sum(a.purpose == 'ros' and a.outcome != 'undelivered' for a in state.interview.answers)
            if spec['target_id'] not in targets or delivered >= LIMITS.focused_ros:
                return False
            spec['purpose'] = 'ros'
        return True

    def _plan_fits(self, state, path):
        if sum(s['purpose'] == 'clarification' for s in path.specs) > LIMITS.clarifications - state.session.clarifications:
            return False
        capacity = min(self.budget.shared_action_capacity(state), self.budget.calls_left(state.session))
        if len(path.specs) > capacity:
            return False
        future = 0
        if state.interview.current in {'ChiefComplaint', 'ContextFactor'}:
            usage = state.session.usage['DifferentialDiagnosis']
            future = SESSION_INTERVIEW_LIMITS['DifferentialDiagnosis'][1] - (usage.actions - usage.empathy_actions)
        return len(path.specs) <= self.budget.action_capacity(state) + future

    def replan(self, state, *, force=False):
        if state.turn or state.session.termination or state.interview.current == 'Education':
            return
        if state.interview.current == 'Initiation':
            self.prepare_initiation(state)
            return
        if state.case.chief(confirmed=True) is None:
            self.prepare_chief_complaint(state)
            return
        if state.interview.current == 'ChiefComplaint':
            self.prepare_chief_complaint(state)
            state.interview.status = 'collecting'
            if not self.open_done(state) or 'unasked' in self.chief_statuses(state).values():
                return
        if state.interview.current == 'ContextFactor' and self._prepare_context_coverage(state):
            return
        key = (state.case.revision, state.case.chief_fact_id, len(state.interview.answers), state.interview.current,
               self.budget.action_capacity(state), self.budget.calls_left(state.session))
        if not force and key == self._last_plan_key:
            return
        self.questions.discard_unasked(state, {q.item_id for q in state.interview.queue if not q.coverage})
        snapshot = self.reasoner.refresh_hypotheses(state)
        all_paths, chief_paths = self._frontier(state, snapshot, [h.disease_id for h in snapshot.hypotheses])
        candidates, compatible = self._comparison(snapshot, chief_paths)
        selected, used, limited = None, 0, False
        for cohort in (candidates, sorted(compatible)):
            paths = [p for p in all_paths if p.disease_id in cohort and self._plan_fits(state, p)]
            specs = {}
            for path in sorted(paths, key=lambda p:(len(p.specs), p.disease_id, p.pattern_id or '')):
                spec = dict(path.specs[0])
                if self._allowed_now(state, spec):
                    specs[self._key(spec)] = spec
            paths = [p for p in paths if self._key(p.specs[0]) in specs]
            if not specs:
                continue
            evaluation = QuestionEvaluation(self.reasoner, snapshot, cohort)
            evaluation.used = used
            assessments = evaluation.assess(specs, paths)
            used, limited = evaluation.used, evaluation.limited
            positive = [(k,a) for k,a in assessments.items() if a['complete'] and (a['utility'] or 0) > 0]
            positive.sort(key=lambda pair:(-pair[1]['utility'], specs[pair[0]]['purpose'] == 'clarification', pair[0]))
            if positive:
                selected = specs[positive[0][0]]
                break
            if used >= self.knowledge.reasoning.simulation_limit or cohort == sorted(compatible):
                break
        emit(self.audit, 'question_selection', reason='selected' if selected else 'computation_limit' if limited else 'no_useful_question',
             selected=selected, simulations=used, policy=self.knowledge.reasoning.version)
        if selected and (state.interview.current != 'ContextFactor' or self.knowledge.has_type(selected['target_id'], 'ContextFactor')):
            if selected['purpose'] == 'clarification':
                self.usage.record_clarification(state)
            self._register(state, selected, 0, 1)
        self._last_plan_key = key

    @staticmethod
    def context_coverage(state):
        return {a.key[1] for a in state.interview.answers if a.purpose == 'context' and a.coverage
                and a.outcome != 'undelivered' and a.key}

    def _prepare_context_coverage(self, state):
        self._prepare_common(state, HISTORY, self.config.texts.history_questions, 'history')
        if any(q.purpose == 'history' for q in state.interview.queue):
            return True
        covered = self.context_coverage(state)
        if len(covered) >= 2:
            return False
        snapshot = self.reasoner.refresh_hypotheses(state)
        anchor = snapshot.chief
        if anchor is None:
            return False
        specs, paths, prerequisites = {}, [], set()
        for profile in self.knowledge.get_patterns_by_target(anchor.target):
            contexts = [(c.concept_id, c.subject, c.time_context, True) for c in profile.applicability]
            contexts += [(c['id'], 'family' if c['type'] == 'family_history' else 'patient', 'unspecified', False)
                         for c in self.knowledge.get_supporting_context(profile.disease_id)]
            for target, subject, timing, prerequisite in contexts:
                if self.knowledge.term(target) in covered or self.was_asked(state, target, subject=subject, time_context=timing):
                    continue
                kind = self.knowledge.get_context_type(target)
                field = 'S.fh' if subject == 'family' else 'S.sh' if kind in {
                    'social_history', 'occupational_history', 'psychosocial_history', 'demographic'} else 'S.pmh'
                spec = self._spec(state, target, purpose='context', field=field, subject=subject, time_context=timing)
                if not spec or not self._eligible(state, spec):
                    continue
                key = self._key(spec)
                specs[key] = dict(spec, coverage=True)
                if prerequisite:
                    prerequisites.add(key)
                paths.append(QuestionPath((spec,), None, profile.disease_id, None))
        if not specs:
            return False
        assessments = QuestionEvaluation(self.reasoner, snapshot, sorted({p.disease_id for p in paths})).assess(specs, paths)
        previous = {self.knowledge.get_context_type(self.knowledge.term_id(name, 'ContextFactor')) for name in covered}
        key = min(specs, key=lambda k:(k not in prerequisites, -(assessments[k].get('utility') or 0),
            self.knowledge.get_context_type(specs[k]['target_id']) in previous, k))
        self._register(state, specs[key], 0, LIMITS.hpi_priority)
        return True

    def prepare_education(self, state, client):
        if state.interview.education_status != 'not_started':
            return
        if self.config.education_enabled:
            generate_plan(state, client, self.knowledge, self.config, self.model, self.audit)
            return
        state.interview.education_status = 'disabled'
        diagnosis = state.case.diagnosis
        selected = self.knowledge.term_id(diagnosis.name, 'Disease') if diagnosis.kind == 'disease' else None
        plan = self.knowledge.plans.get(selected)
        if plan:
            for field in ('tests', 'treatment', 'disposition', 'follow_up'):
                text = getattr(plan, field)
                if field == 'tests' and not text:
                    text = self.config.texts.test_separator.join(self.knowledge.get_planned_tests(selected))
                if text:
                    state.case.plan.append(PlanSentence(id=f'plan:{field}:0', field=field, text=text, basis='model_knowledge'))

    def select_question(self, state):
        if state.session.termination:
            return
        redundant = {q.item_id for q in state.interview.queue if q.category and slot_resolved(state.case, q.category)}
        redundant.update(q.item_id for q in state.interview.queue if q.target and q.purpose not in {'clarification', 'education', 'intake', 'history'}
            and self.has_resolved_evidence(state, q.target, q.attribute, q.observation_id, q.episode_id, q.subject, q.time_context))
        self.questions.discard_unasked(state, redundant, reason='resolved')
        if state.interview.queue:
            self.interactions.select_question(state, min(state.interview.queue, key=lambda q:(q.order, q.item_id)))
