import hashlib

from ..state import usage
from .collection import INTAKE, HISTORY, answered, slot_resolved
from .limits import LIMITS
from ..state.models import Question


class QuestionTools:
    def __init__(self, knowledge, config, questions, interactions, budget):
        self.knowledge, self.config, self.questions = knowledge, config, questions
        self.interactions, self.budget = interactions, budget

    def has_resolved_evidence(self, state, target, attribute=None, observation=None, episode=None,
                              subject='patient', time_context=None, subject_member=None):
        ident = target if target.startswith(('urn:', 'http')) else next((ident for kind in ('Symptom', 'ExamFinding', 'ContextFactor')
            if (ident := self.knowledge.term_id(target, kind))), None)
        exam = self.knowledge.has_type(ident, 'ExamFinding')
        target = self.knowledge.term(target) if target.startswith(('urn:', 'http')) else target
        attribute = self.knowledge.term(attribute) if attribute and attribute.startswith(('urn:', 'http')) else attribute
        values = [f for f in state.case.current_facts() if f.target == target and f.attribute == attribute
            and f.polarity_scope == 'general'
            and (f.acquisition == 'EXAM' or f.source_ref == 'initial:vital_signs') == exam
            and f.subject == subject and f.subject_member == subject_member and (time_context is not None or f.kind == 'context' or f.time_context != 'past')
            and (observation is None or f.observation_id == observation)
            and (episode is None or f.episode_id == episode)
            and (time_context is None or f.time_context == time_context)]
        values = [f for f in values if f.status in {'present', 'absent'}]
        return bool(values) and (attribute is not None or len({f.status for f in values}) == 1)

    def was_asked(self, state, target, attribute=None, observation=None, episode=None,
                  subject='patient', time_context=None, subject_member=None):
        target = self.knowledge.term(target) if target.startswith(('urn:', 'http')) else target
        attribute = self.knowledge.term(attribute) if attribute and attribute.startswith(('urn:', 'http')) else attribute
        for answer in state.interview.answers:
            if not answer.key or answer.outcome == 'undelivered':
                continue
            _, t, a, s, member, timing, observed, occurrence = answer.key
            if (t, a or None, s, member or None) != (target, attribute, subject, subject_member):
                continue
            scopes = [(observed, occurrence, timing)]
            scopes.extend((f.observation_id, f.episode_id, f.time_context) for ident in answer.fact_ids
                          if (f := state.case.facts.get(ident)) and f.target == target and f.attribute == attribute)
            if any((observation is None or o == observation) and (episode is None or e == episode)
                   and (time_context is None or t == time_context) for o,e,t in scopes):
                return True
        return False

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
                time_context=chief.time_context if chief and slot in INTAKE else 'unspecified',
                subject='family' if slot == 'family_history' else 'patient',
                answer_type='presence' if slot in {'course', 'recurrence', 'medical_history', 'medication', 'allergy', 'family_history'} else 'free_text'))

    def chief_statuses(self, state):
        chief = state.case.chief(confirmed=True)
        if chief is None:
            return {}
        target = self.knowledge.term_id(chief.target, 'Symptom')
        statuses = {}
        for attribute in self.knowledge.collection_attributes(target):
            name = self.knowledge.term(attribute)
            if self.has_resolved_evidence(state, target, attribute, chief.observation_id, chief.episode_id, 'patient', chief.time_context):
                statuses[name] = 'acquired'
                continue
            key = ('SAY', chief.target, name, 'patient', '', chief.time_context, chief.observation_id or '', chief.episode_id or '')
            answer = next((a for a in reversed(state.interview.answers) if a.key == key), None)
            statuses[name] = (('recorded_unmapped' if answer.outcome == 'recorded' else
                answer.outcome if answer.outcome in {'not_applicable', 'unsupported', 'conflict'} else 'unknown')
                if answer else state.interview.collection.get('|'.join(key), 'unasked'))
        return statuses

    def prepare_clarification(self, state, original=None, *, primary_choice=False):
        if any(q.purpose == 'clarification' for q in state.interview.queue):
            return True
        if not self.budget.can_clarify(state):
            return False
        usage.record_clarification(state)
        values = original.model_dump() if original and original.kind == 'SAY' else {}
        attribute = self.knowledge.term_id(original.attribute, 'FindingAttribute') if original and original.attribute else None
        text = self.knowledge.clarification(attribute, self.config.texts.clarification_question)
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

    def ensure_chief(self, state):
        if state.case.chief(confirmed=True):
            return True
        candidate, original = state.case.chief(), None
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

    def _spec(self, state, target, attribute=None, observation=None, episode=None, *, purpose='feature', field=None,
              subject='patient', time_context='current', subject_member=None):
        if attribute and (not self.knowledge.has_type(attribute, 'FindingAttribute')
                          or attribute not in self.knowledge.get_symptom_attributes(target)):
            return None
        if attribute and self.knowledge.collection_attributes(target, attribute) != [attribute]:
            return None
        exam = self.knowledge.has_type(target, 'ExamFinding')
        if exam:
            if subject != 'patient' or time_context != 'current':
                return None
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
            answer_type=answer_type, affirmative_presence=affirmative and not attribute, subject=subject, subject_member=subject_member, time_context=time_context)

    def _key(self, spec):
        return '|'.join(self._question(spec, '', 0, 0).semantic_key())

    def _question(self, spec, ident, order, priority):
        values = {k:v for k,v in spec.items() if k not in {'field', 'target_id', 'attribute_id', 'assessment'}}
        return Question(item_id=ident, target=self.knowledge.term(spec['target_id']),
            attribute=self.knowledge.term(spec['attribute_id']) if spec['attribute_id'] else None,
            category=self.knowledge.attribute_category(spec['attribute_id']),
            order=order, priority=priority, **values)

    def _register(self, state, spec, order, priority):
        ident = 'question:' + hashlib.sha256(self._key(spec).encode()).hexdigest()[:24]
        if spec['purpose'] == 'clarification':
            ident += f':clarification:{state.session.clarifications}'
        self.questions.register(state, self._question(spec, ident, order, priority))

    def _eligible(self, state, spec):
        target, attribute = spec['target_id'], spec['attribute_id']
        args = (state, target, attribute, spec['observation_id'], spec['episode_id'], spec['subject'], spec['time_context'], spec.get('subject_member'))
        if self.has_resolved_evidence(*args):
            return False
        key = (spec['kind'], self.knowledge.term(target), self.knowledge.term(attribute) if attribute else '',
               spec['subject'], spec.get('subject_member') or '', spec['time_context'], spec['observation_id'] or '', spec['episode_id'] or '')
        if '|'.join(key) in state.interview.collection and state.interview.collection['|'.join(key)] in {'blocked_asset', 'budget_stopped'}:
            return False
        if self.was_asked(*args):
            prior = [a for a in state.interview.answers if a.key == key and a.outcome != 'undelivered']
            if not prior or any(a.purpose == 'clarification' or a.outcome in {'unknown','not_applicable','unsupported','nonclinical'}
                                for a in prior) or not self.budget.can_clarify(state):
                return False
            spec.update(purpose='clarification', text=self.knowledge.clarification(attribute,
                         self.config.texts.clarification_question), affirmative_presence=False)
        if attribute and spec['kind'] == 'SAY':
            return any(f.target == self.knowledge.term(target) and not f.attribute and f.status == 'present'
                and f.graph_binding and f.polarity_scope == 'general'
                and f.acquisition != 'EXAM' and f.source_ref != 'initial:vital_signs'
                and (f.subject,f.subject_member,f.time_context,f.observation_id,f.episode_id) ==
                    (spec['subject'],spec.get('subject_member'),spec['time_context'],spec['observation_id'],spec['episode_id'])
                for f in state.case.current_facts())
        return True

    def _allowed_now(self, state, spec):
        if not self._eligible(state, spec):
            return False
        if state.interview.current == 'ChiefComplaint':
            return False
        if state.interview.current == 'DifferentialDiagnosis':
            if self.knowledge.has_type(spec['target_id'], 'ContextFactor'):
                return False
            if spec['kind'] == 'EXAM':
                return True
            if spec['attribute_id']:
                return True
            chief = state.case.chief(confirmed=True)
            systems = self.knowledge.get_symptom_systems(self.knowledge.term_id(chief.target, 'Symptom')) if chief else []
            targets = {t for system in systems for t in self.knowledge.get_system_symptoms(system)}
            delivered = sum(a.purpose == 'ros' and a.outcome != 'undelivered' for a in state.interview.answers)
            if spec['target_id'] in targets:
                if delivered >= LIMITS.focused_ros:
                    return False
                spec['purpose'] = 'ros'
        if state.interview.current == 'ContextFactor' and not self.knowledge.has_type(spec['target_id'], 'ContextFactor'):
            return False
        return True

    def select_question(self, state):
        if state.session.termination:
            return
        redundant = {q.item_id for q in state.interview.queue if q.category in (*HISTORY, *INTAKE)
                     and q.purpose in {'intake', 'history'} and answered(state, q.category)}
        redundant.update(q.item_id for q in state.interview.queue if q.attribute and
            self.collection_keys(q.semantic_key()) != [q.semantic_key()])
        redundant.update(q.item_id for q in state.interview.queue if q.target and q.purpose not in {'clarification', 'education', 'intake', 'history'}
            and self.has_resolved_evidence(state, q.target, q.attribute, q.observation_id, q.episode_id, q.subject, q.time_context, q.subject_member))
        self.questions.discard_unasked(state, redundant, reason='resolved')
        if state.interview.queue:
            self.interactions.select_question(state, min(state.interview.queue, key=lambda q:(q.order, q.item_id)))

    def collection_keys(self, key):
        if not key or not key[2]:
            return [key]
        target = next((ident for kind in ('Symptom', 'ExamFinding', 'ContextFactor')
                       if (ident := self.knowledge.term_id(key[1], kind))), None)
        attribute = self.knowledge.term_id(key[2], 'FindingAttribute')
        if not target or not attribute:
            return [key]
        return [(*key[:2], self.knowledge.term(component), *key[3:])
                for component in self.knowledge.collection_attributes(target, attribute)]

    def _options(self, state, candidates):
        if not self.budget.can_start_action(state):
            return {}
        grouped = {}
        for disease, candidate in candidates.items():
            for ref in candidate.entry.unresolved:
                if not ref.scope:
                    continue
                for key in self.collection_keys(ref.scope):
                    grouped.setdefault(key, set()).add(disease)
        options = {}
        for key, diseases in grouped.items():
            kind, name, attr, subject, member, timing, observation, episode = key
            target = next((ident for t in ('Symptom','ExamFinding','ContextFactor')
                if (ident := self.knowledge.term_id(name, t))), None)
            attribute = self.knowledge.term_id(attr, 'FindingAttribute') if attr else None
            if attr and attribute is None:
                continue
            spec = self._spec(state, target, attribute,
                observation or None, episode or None, purpose='context' if self.knowledge.has_type(target,'ContextFactor') else 'feature',
                subject=subject, subject_member=member or None, time_context=timing)
            if spec and self._allowed_now(state, spec):
                options[self._key(spec)] = (spec, diseases)
        return options

    @staticmethod
    def open_done(state):
        return any(a.purpose == 'open_inquiry' and a.outcome != 'undelivered' for a in state.interview.answers)
