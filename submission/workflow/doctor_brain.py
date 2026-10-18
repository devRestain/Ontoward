import hashlib
import json
from collections import deque

from .education import generate_plan, messages
from .rules.assessment import graph_candidates
from .rules.collection import INTAKE, HISTORY, ATTRIBUTE_CATEGORIES, answered, slot_resolved
from .rules.limits import LIMITS
from .rules.normalization import strict_json
from .state.models import Assessment, DifferentialEntry, EvidenceRef, GraphRef, PlanSentence, Question


class DoctorBrain:
    def __init__(self, knowledge, config, questions, interactions, budget, usage, model):
        self.knowledge, self.config, self.questions = knowledge, config, questions
        self.interactions, self.budget, self.usage, self.model = interactions, budget, usage, model
        self._attempted = self._action_key = None
        self._error = None

    def has_resolved_evidence(self, state, target, attribute=None, observation=None, episode=None,
                              subject='patient', time_context=None, subject_member=None):
        target = self.knowledge.term(target) if target.startswith(('urn:', 'http')) else target
        attribute = self.knowledge.term(attribute) if attribute and attribute.startswith(('urn:', 'http')) else attribute
        values = [f for f in state.case.current_facts() if f.target == target and f.attribute == attribute
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
            key = ('SAY', chief.target, name, 'patient', '', chief.time_context, chief.observation_id or '', chief.episode_id or '')
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
            key = '|'.join(('SAY', chief.target, name, 'patient', '', chief.time_context, chief.observation_id or '', chief.episode_id or ''))
            if spec is None:
                state.interview.collection[key] = 'blocked_asset'
            elif self.budget.action_capacity(state) <= 1:
                state.interview.collection[key] = 'budget_stopped'
            else:
                self._register(state, dict(spec, coverage=True), order, LIMITS.hpi_priority - order)
        if not self.open_done(state):
            self.questions.register(state, Question(item_id='ChiefComplaint:open', purpose='open_inquiry',
                text=self.config.texts.open_question, order=1000, priority=LIMITS.open_inquiry_priority, coverage=True))
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
              subject='patient', time_context='current', subject_member=None):
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
            answer_type=answer_type, affirmative_presence=affirmative and not attribute, subject=subject, subject_member=subject_member, time_context=time_context)

    def _key(self, spec):
        return '|'.join(self._question(spec, '', 0, 0).semantic_key())

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
            local = (attribute or '').rsplit(':', 1)[-1]
            spec.update(purpose='clarification', text=self.config.texts.clarification_questions.get(local,
                         self.config.texts.clarification_question), affirmative_presence=False)
        if attribute and spec['kind'] == 'SAY' and not future:
            return any(o == spec['observation_id'] and e == spec['episode_id'] and status == 'present'
                       for o,e,status in self._occurrences(state, target))
        return True

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
        if state.interview.current == 'ContextFactor' and not self.knowledge.has_type(spec['target_id'], 'ContextFactor'):
            return False
        return True

    def select_question(self, state):
        if state.session.termination:
            return
        redundant = {q.item_id for q in state.interview.queue if q.category in HISTORY and slot_resolved(state.case, q.category)}
        redundant.update(q.item_id for q in state.interview.queue if q.target and q.purpose not in {'clarification', 'education', 'intake', 'history'}
            and self.has_resolved_evidence(state, q.target, q.attribute, q.observation_id, q.episode_id, q.subject, q.time_context, q.subject_member))
        self.questions.discard_unasked(state, redundant, reason='resolved')
        if state.interview.queue:
            self.interactions.select_question(state, min(state.interview.queue, key=lambda q:(q.order, q.item_id)))

    def prepare_required(self, state):
        scope = state.interview.current
        if scope == 'Initiation':
            self.prepare_initiation(state)
        elif state.case.chief(confirmed=True) is None:
            self.prepare_chief_complaint(state)
        elif scope == 'ChiefComplaint':
            self.prepare_chief_complaint(state)
        elif scope == 'ContextFactor':
            self._prepare_common(state, HISTORY, self.config.texts.history_questions, 'history')
            if not state.interview.queue:
                self._prepare_context_coverage(state)

    def _prepare_context_coverage(self, state):
        covered = {a.key[1] for a in state.interview.answers if a.purpose == 'context' and a.coverage
            and a.outcome != 'undelivered' and a.key}
        if len(covered) >= 2:
            return
        chief = state.case.chief(confirmed=True)
        target = self.knowledge.term_id(chief.target, 'Symptom') if chief else None
        specs = {}
        for profile in self.knowledge.get_patterns_by_target(target) if target else ():
            contexts = [(c.concept_id,c.subject,c.time_context,True) for c in profile.applicability]
            contexts += [(c['id'],'family' if c['type']=='family_history' else 'patient','unspecified',False)
                for c in self.knowledge.get_supporting_context(profile.disease_id)]
            for ident, subject, timing, prerequisite in contexts:
                if self.knowledge.term(ident) in covered:
                    continue
                spec = self._spec(state, ident, purpose='context', subject=subject, time_context=timing)
                if spec and self._eligible(state, spec):
                    specs[self._key(spec)] = (prerequisite, spec)
        if specs:
            _, spec = min(specs.values(), key=lambda row:(not row[0], row[1]['target_id']))
            self._register(state, dict(spec, coverage=True), 0, LIMITS.hpi_priority)

    def _options(self, state, candidates):
        options = {}
        for disease, candidate in candidates.items():
            for ref in candidate.entry.unresolved:
                if not ref.scope:
                    continue
                kind, name, attr, subject, member, timing, observation, episode = ref.scope
                target = next((ident for t in ('Symptom','ExamFinding','ContextFactor')
                    if (ident := self.knowledge.term_id(name, t))), None)
                spec = self._spec(state, target, self.knowledge.term_id(attr,'FindingAttribute') if attr else None,
                    observation or None, episode or None, purpose='context' if self.knowledge.has_type(target,'ContextFactor') else 'feature',
                    subject=subject, subject_member=member or None, time_context=timing)
                if not spec or not self._allowed_now(state, spec):
                    continue
                key = self._key(spec)
                options.setdefault(key, (spec, set()))[1].add(disease)
        return options

    def _stamp(self, state):
        return (state.case.revision, state.case.chief_fact_id, state.interview.current,
            tuple((a.question_id,a.outcome,a.fact_ids) for a in state.interview.answers),
            tuple(sorted(state.interview.collection.items())), self.budget.action_capacity(state))

    @staticmethod
    def _bytes(request):
        return len(json.dumps(request, ensure_ascii=False, separators=(',',':'), allow_nan=False).encode())

    def _payload(self, state, candidates, action_only, closing=False):
        previous = state.case.assessment
        prior = [self.knowledge.term_id(e.name,'Disease') for e in previous.differential] if previous else []
        protected = [ident for ident in prior if ident in candidates]
        remaining = set(candidates) - set(protected)
        buckets = {}
        for ident in sorted(remaining, key=lambda i:(-len(candidates[i].entry.supports),i)):
            for route in sorted(candidates[ident].routes):
                buckets.setdefault(route, deque()).append(ident)
        fair = []
        while any(buckets.values()):
            for bucket in buckets.values():
                if bucket:
                    ident = bucket.popleft()
                    if ident in remaining:
                        remaining.remove(ident); fair.append(ident)
        refs = {ident:f'd_{i+1}' for i,ident in enumerate([*protected,*fair])}
        fields = {'id','kind','target','attribute','values','measurement','status','subject','subject_member',
            'time_context','observation_id','episode_id','polarity_scope','binding'}
        payload = dict(task='clinical_action' if action_only else 'clinical_decision',
            revision=state.case.revision, chief_fact_id=state.case.chief_fact_id, stage=state.interview.current,
            facts=[f.model_dump(include=fields, exclude_none=True) for f in state.case.current_facts()
                if f.evidence_use=='reasoning' and f.polarity_scope!='qualified'],
            required=[q.purpose for q in state.interview.queue if q.coverage],
            prior_order=[refs[i] for i in protected], candidates=[], questions=[],
            resources=dict(turns=self.budget.action_capacity(state), calls=self.budget.calls_left(state.session)))
        relation_index = {detail['association']:detail for candidate in candidates.values() for detail in candidate.details}
        feature_index = {f['id']:f for detail in relation_index.values() for f in detail['features']}
        def expected(value):
            if not isinstance(value,dict):
                return value
            result=dict(value)
            if result.get('concept'):
                result['concept']=self.knowledge.term(result['concept'])
            if result.get('concepts'):
                result['concepts']=[self.knowledge.term(c) for c in result['concepts']]
            return result
        def evidence(ref):
            graph=ref.graph_ref
            detail=relation_index.get(graph.association_id or graph.id)
            if graph.kind=='association':
                detail=relation_index[graph.id]
                features=[dict(attribute=f['attribute'],expected=expected(f['expected'])) for f in detail['features']]
            elif graph.kind=='feature':
                f=feature_index[graph.id]
                features=[dict(attribute=f['attribute'],expected=expected(f['expected']))]
            else:
                features=[dict(context=self.knowledge.term(graph.id),expected='present')]
            result=dict(level=graph.kind,fact_ids=ref.fact_ids,features=features)
            if detail:
                result['target']=detail['target']
                if detail['conditions']:
                    result['applicability']=detail['conditions']
            return result
        def row(ident):
            candidate=candidates[ident]
            unresolved=list(dict.fromkeys((ref.scope,ref.reason) for ref in candidate.entry.unresolved))
            return dict(ref=refs[ident],name=candidate.entry.name,
                routes=[self.knowledge.term(route) for route in sorted(candidate.routes)],
                supports=[evidence(ref) for ref in candidate.entry.supports],
                against=[evidence(ref) for ref in candidate.entry.against],
                unresolved=[dict(scope=scope,reason=reason) for scope,reason in unresolved] if ident in protected else None,
                unresolved_count=len(unresolved))
        payload['candidates'] = [row(i) for i in protected]
        if self._bytes(messages(self.config.brain_prompt,payload)) > LIMITS.clinical_request_bytes:
            raise ValueError('clinical_protected_context_overflow')
        included = set(protected)
        candidate_budget = LIMITS.clinical_request_bytes - (16384 if not state.interview.queue and not closing else 0)
        for ident in fair:
            payload['candidates'].append(row(ident))
            if self._bytes(messages(self.config.brain_prompt,payload)) > candidate_budget:
                payload['candidates'].pop()
            else:
                included.add(ident)
        for ident in [*protected,*fair]:
            if ident not in included:
                continue
            item=next(r for r in payload['candidates'] if r['ref']==refs[ident])
            item['relations']=candidates[ident].details
            if self._bytes(messages(self.config.brain_prompt,payload))>candidate_budget:
                del item['relations']
        options = self._options(state, {i:c for i,c in candidates.items() if i in included}) if not state.interview.queue and not closing else {}
        question_refs = {}
        for spec, diseases in options.values():
            ref = f'q_{len(question_refs)+1}'
            question = self._question(spec, '', 0, 0)
            differences={}
            for disease in sorted(diseases & included):
                values=[]
                for unresolved in candidates[disease].entry.unresolved:
                    if unresolved.scope!=question.semantic_key():
                        continue
                    graph=unresolved.graph_ref
                    conditions=relation_index[graph.association_id]['conditions'] if graph.association_id else []
                    if graph.kind=='feature':
                        value=dict(expected=expected(feature_index[graph.id]['expected']),applicability=conditions)
                    else:
                        value=dict(expected=next((c['status'] for c in conditions if c['concept_id']==graph.id),'present'),
                            applicability=conditions)
                    if value not in values:
                        values.append(value)
                differences[refs[disease]]=values
            payload['questions'].append(dict(ref=ref, **question.model_dump(exclude_defaults=True, exclude={'item_id'}),
                disease_refs=[refs[i] for i in sorted(diseases & included)],expected_by_disease=differences))
            if self._bytes(messages(self.config.brain_prompt,payload)) > LIMITS.clinical_request_bytes:
                payload['questions'].pop()
            else:
                question_refs[ref] = spec
        return payload, {refs[i]:i for i in included}, question_refs

    def _accept_action(self, state, raw, options):
        if not isinstance(raw, dict) or raw.get('kind') not in {'continue_required','ask','advance_stage','finish_collection'}:
            raise ValueError('invalid_next_action')
        kind = raw['kind']
        if set(raw) != ({'kind','question_ref'} if kind=='ask' else {'kind'}):
            raise ValueError('invalid_next_action_fields')
        if state.interview.queue:
            if kind != 'continue_required':
                raise ValueError('required_collection_pending')
            return
        if kind == 'ask':
            spec = options.get(raw['question_ref'])
            if not spec or not self._allowed_now(state,spec) or not self.budget.can_start_action(state):
                raise ValueError('question_not_executable')
            if spec['purpose']=='clarification':
                self.usage.record_clarification(state)
            self._register(state,spec,0,1)
        elif kind == 'continue_required' or kind == 'finish_collection' and state.interview.current != 'DifferentialDiagnosis':
            raise ValueError('invalid_stage_transition')
        else:
            state.interview.collection[f'{state.interview.current}:completion'] = kind

    def decide(self, state, client, candidates, *, action_only=False, closing=False):
        try:
            payload, refs, options = self._payload(state,candidates,action_only,closing)
        except ValueError as error:
            self._error = str(error)
            return
        ranking_accepted = action_only
        for attempt in range(2):
            response = self.model.complete(state,client,role='clinical',messages=messages(self.config.brain_prompt,payload),
                max_tokens=LIMITS.gateway_recovery_tokens if attempt else LIMITS.gateway_tokens)
            if state.session.termination:
                return
            try:
                raw = strict_json(response.content)
                expected = {'next_action'} if ranking_accepted else {'ranked_disease_refs','next_action'}
                if not isinstance(raw,dict) or set(raw) != expected:
                    raise ValueError(response.error or 'invalid_clinical_response_fields')
                if not ranking_accepted:
                    ranked = raw['ranked_disease_refs']
                    if (not isinstance(ranked,list) or not ranked or any(not isinstance(r,str) or r not in refs for r in ranked)
                        or len(set(ranked)) != len(ranked) or not set(payload['prior_order']) <= set(ranked)):
                        raise ValueError('invalid_or_incomplete_ranking')
                    state.case.assessment = Assessment(differential=tuple(candidates[refs[r]].entry for r in ranked),
                        based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id)
                    ranking_accepted = True
                if not closing:
                    self._accept_action(state,raw['next_action'],options)
                self._error = None
                return
            except (ValueError,TypeError) as error:
                self._error = response.error or str(error)
                if response.error and response.error not in {'OUTPUT_TRUNCATED','PROVIDER_RESPONSE_INVALID','CONTEXT_LIMIT_EXCEEDED'}:
                    break
                payload = {**payload, 'task':'clinical_action' if ranking_accepted else 'clinical_decision',
                    'validation_error':self._error}
                if self._bytes(messages(self.config.brain_prompt,payload)) > LIMITS.clinical_request_bytes:
                    break
        state.interview.collection[f'{state.interview.current}:decision'] = self._error

    def refresh_assessment(self, state, client, *, closing=False):
        if state.case.assessment and state.case.assessment.frozen or state.session.termination:
            return
        key = (state.case.revision,state.case.chief_fact_id)
        candidates = graph_candidates(state.case,self.knowledge,state.interview)
        if self._attempted != key:
            self._attempted = key
            if candidates:
                self.decide(state,client,candidates,closing=closing)
            else:
                state.case.assessment = Assessment(based_on_case_revision=key[0],based_on_chief_fact_id=key[1])
            self._action_key = self._stamp(state)
        elif state.case.assessment and (state.case.assessment.based_on_case_revision,
                state.case.assessment.based_on_chief_fact_id) == key:
            entries = tuple(candidates[i].entry for e in state.case.assessment.differential
                if (i:=self.knowledge.term_id(e.name,'Disease')) in candidates)
            state.case.assessment = state.case.assessment.model_copy(update={'differential':entries})

    def replan(self, state, client, *, force=False):
        if state.turn or state.session.termination or state.interview.current=='Education':
            return
        self.questions.discard_unasked(state,{q.item_id for q in state.interview.queue if not q.coverage
            and q.purpose not in {'chief','clarification'}},reason='replanning')
        self.prepare_required(state)
        self.refresh_assessment(state,client)
        if state.interview.queue or state.session.termination or state.interview.current=='Initiation':
            return
        stamp = self._stamp(state)
        if stamp != self._action_key:
            candidates = graph_candidates(state.case,self.knowledge,state.interview)
            if candidates and state.case.assessment and state.case.assessment.based_on_case_revision==state.case.revision:
                self.decide(state,client,candidates,action_only=True)
            self._action_key = self._stamp(state)

    def close_differential(self, state, client):
        if state.case.assessment and state.case.assessment.frozen:
            return
        if state.turn:
            raise ValueError('Cannot freeze an unfinished input')
        self.refresh_assessment(state,client,closing=True)
        if state.session.termination:
            return
        assessment = state.case.assessment
        limitations = []
        if not assessment or not assessment.differential or (assessment.based_on_case_revision,
                assessment.based_on_chief_fact_id)!=(state.case.revision,state.case.chief_fact_id):
            chief = state.case.chief(confirmed=True)
            ident = self.knowledge.term_id(chief.target,'Symptom') if chief else None
            if ident is None:
                state.stop('failed','no_supported_diagnosis'); return
            limitations.append(self._error or 'no_graph_disease_assessment')
            assessment = Assessment(differential=(DifferentialEntry(kind='symptom',name=chief.target,
                supports=(EvidenceRef(graph_ref=GraphRef(kind='symptom',id=ident),fact_ids=(chief.id,)),)),),
                based_on_case_revision=state.case.revision,based_on_chief_fact_id=state.case.chief_fact_id)
        if any(v in {'unknown','blocked_asset','budget_stopped','recorded_unmapped','unasked','conflict','unsupported'}
                for v in self.chief_statuses(state).values()):
            limitations.append('Chief complaint details remain incomplete')
        if not any(a.key and a.key[0]=='EXAM' and a.outcome in {'mapped','recorded'} for a in state.interview.answers):
            limitations.append('No additional physical examination obtained')
        if any(f.binding=='forced' for f in state.case.facts.values()):
            limitations.append('Some patient facts use forced database approximations')
        limitations.extend(f'{key}: {value}' for key,value in state.interview.collection.items()
            if key.endswith((':completion',':decision')) and value not in {'advance_stage','finish_collection'})
        if self._error:
            limitations.append(self._error)
        state.case.assessment = assessment.model_copy(update={'frozen':True,'limitations':tuple(dict.fromkeys(limitations))})

    def prepare_education(self, state, client):
        state.case.primary()
        if state.interview.education_status != 'not_started':
            return
        if self.config.education_enabled:
            generate_plan(state,client,self.knowledge,self.config,self.model)
        else:
            state.interview.education_status = 'disabled'
            primary = state.case.primary()
            selected = self.knowledge.term_id(primary.name,'Disease') if primary.kind=='disease' else None
            plan = self.knowledge.plans.get(selected)
            if plan:
                for field in ('tests','treatment','disposition','follow_up'):
                    if text:=getattr(plan,field):
                        state.case.plan.append(PlanSentence(id=f'plan:{field}:0',field=field,text=text,basis='model_knowledge'))
