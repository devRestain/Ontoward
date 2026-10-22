from ..state import usage
from ..rules.decision import ActionReply, DecisionWork, accept_ranking, clinical_messages, prepare_decision, latest_response
from ..rules.assessment import graph_candidates
from ..model_context import messages
from ..wire import table_payload
from ..rules.limits import DD_MINIMUMS, LIMITS, SESSION_INTERVIEW_LIMITS
from ..rules.dd import action_counts, required_kinds, requirements
from ..rules.normalization import strict_json
from ..state.models import Assessment, DifferentialEntry, EvidenceRef, GraphRef
from ..rules.coverage import accept as accept_coverage, exact_unknown


class DifferentialDiagnosisSession:
    def __init__(self, knowledge, config, tools, brain, *, record_view):
        self.knowledge, self.config, self.tools, self.brain = knowledge, config, tools, brain
        self.record_view = record_view
        self.last_input = None
        self.last_passed = ()
        self.error = None
        self.rank_basis = None
        self.handled_response = None
        self.question_pool = None
        self.diseases = ()
        self.final_rank_attempted = False

    def prepare_selection(self, state):
        """Freeze graph-derived question identities once; check executability now."""
        if self.question_pool is None:
            candidates = graph_candidates(state.case, self.knowledge, state.interview)
            self.diseases = tuple(candidate.entry.name for candidate in candidates.values())
            pool = self.tools._options(state, candidates, include_ineligible=True)
            self.question_pool = {f'q_{index}': dict(spec)
                for index, (spec, _) in enumerate(pool.values(), 1)}
        options, rows, scopes, scope_refs = {}, [], {}, {}
        for ref, original in self.question_pool.items():
            spec = dict(original)
            if not self.tools._allowed_now(state, spec):
                continue
            question = self.tools._question(spec, '', 0, 0)
            key = question.semantic_key()[3:]
            if key not in scope_refs:
                scope_ref = f's_{len(scope_refs) + 1}'
                scope_refs[key] = scope_ref
                scopes[scope_ref] = {name: value for name, value in zip(
                    ('subject', 'member', 'time', 'observation', 'episode'), key) if value}
            rows.append({name: value for name, value in dict(ref=ref, kind=question.kind,
                target=question.target, attribute=question.attribute, text=question.text,
                scope=scope_refs[key]).items() if value is not None})
            options[ref] = spec
        chief = state.case.collection_chief()
        fields, _ = self.record_view(state.case, state.interview)
        payload = dict(task='clinical_action', stage='DifferentialDiagnosis',
            chief=chief.target if chief else None, diseases=list(self.diseases), questions=rows, scopes=scopes,
            patient_history={field: '\n'.join(lines) for field, lines in fields.items()
                if field.startswith(('S.', 'O.')) and lines},
            resources=dict(turns=self.tools.budget.action_capacity(state),
                **requirements(state, options)))
        return DecisionWork(payload, {}, {}, options)

    def selection_messages(self, work):
        return messages(self.config.prompt('clinical.select', 'session.DifferentialDiagnosis'),
            table_payload(work.payload, ('questions', 'scopes')))

    def input_key(self, state):
        return (state.case.revision, state.case.chief_fact_id, latest_response(state))

    def reusable_unknowns(self, state):
        assessment = state.case.assessment
        if (not assessment or assessment.frozen or not assessment.differential
                or self.rank_basis != (assessment.based_on_case_revision, assessment.based_on_chief_fact_id,
                                       assessment.based_on_response)
                or self.rank_basis[:2] != self.input_key(state)[:2]):
            return False
        answers = [a for a in state.interview.answers if a.scope != 'Education' and a.source_ref
                   and a.outcome not in {'undelivered', 'delivered'}]
        basis = assessment.based_on_response
        indices = [index for index, answer in enumerate(answers) if answer.source_ref == basis]
        if basis != 'entry' and len(indices) != 1:
            return False
        pending = answers[(indices[0] + 1) if indices else 0:]
        return bool(pending) and len({a.source_ref for a in pending}) == len(pending) and all(
            a.scope == 'DifferentialDiagnosis' and exact_unknown(a, state.case, self.config) for a in pending)

    def freeze_problem(self, state, reason):
        """Last clinical boundary when graph-dependent freeze itself is unavailable."""
        if state.case.assessment and state.case.assessment.frozen and state.case.assessment.differential:
            state.case.diagnosis = state.case.assessment.differential[0].name
            return
        assessment = state.case.assessment
        if assessment and assessment.differential and assessment.differential[0].kind == 'disease':
            self.freeze_assessment(state, assessment, [*assessment.limitations, reason,
                'Assessment incomplete; retain last accepted disease ranking without final reassessment'])
            return
        name = state.case.diagnosis or 'Undifferentiated presenting complaint'
        state.case.diagnosis = name
        state.case.assessment = Assessment(differential=(DifferentialEntry(kind='symptom', name=name),),
            based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id,
            based_on_response=latest_response(state), frozen=True,
            frozen_case_revision=state.case.revision, frozen_chief_fact_id=state.case.chief_fact_id,
            limitations=(reason, 'Assessment incomplete'))

    def prepare_decision(self, state, *, mode='decision', closing=False, candidates=None):
        return prepare_decision(state, self.knowledge, self.tools, mode=mode, closing=closing, candidates=candidates)

    def accept(self, state, raw, work, *, ranking_accepted=False, closing=False):
        expected = {'next_action'} if ranking_accepted else {'ranked_disease_refs'} if closing else {'ranked_disease_refs', 'next_action'}
        if not isinstance(raw, dict):
            raise ValueError('invalid_clinical_response_fields')
        raw = dict(raw)
        proposals = raw.pop('covered_questions', [])
        if closing and set(raw) != expected:
            raise ValueError('invalid_clinical_response_fields')
        if not ranking_accepted:
            accept_ranking(state, raw, work)
            assessment = state.case.assessment
            if not closing:
                self.rank_basis = (assessment.based_on_case_revision, assessment.based_on_chief_fact_id,
                                   assessment.based_on_response)
        if set(raw) != expected:
            raise ValueError('invalid_clinical_response_fields')
        if closing:
            return
        work.coverage.proposals = proposals if isinstance(proposals, list) else []
        covered_refs = accept_coverage(state, work.coverage, self.knowledge, self.config)
        action = ActionReply.model_validate({'next_action': raw['next_action']}).next_action
        available = {ref: spec for ref, spec in work.options.items() if self.tools._allowed_now(state, spec)}
        needed = required_kinds(state, available)
        if action.kind == 'ask' and action.question_ref in covered_refs:
            ref = next((ref for ref, spec in available.items() if not needed or spec['kind'] in needed), None)
            action = ActionReply(next_action=dict(kind='ask', question_ref=ref) if ref else dict(kind='finish_collection')).next_action
        if action.kind == 'ask':
            spec = work.options.get(action.question_ref)
            if not spec or not self.tools._allowed_now(state, spec) or not self.tools.budget.can_start_action(state):
                raise ValueError('question_not_executable')
            if needed and spec['kind'] not in needed:
                raise ValueError('dd_action_reserves_required_kind')
            if spec['purpose'] == 'clarification':
                usage.record_clarification(state)
            self.tools._register(state, spec, 0, 1)
        else:
            if needed and self.tools.budget.can_start_action(state):
                raise ValueError('dd_collection_minimum_unmet')
            state.interview.collection['DifferentialDiagnosis:completion'] = 'finish_collection'
        self.handled_response = latest_response(state)

    def required_actions(self, state):
        counts = action_counts(state.interview)
        return sum(max(0, minimum - counts[kind]) for kind, minimum in DD_MINIMUMS.items())

    def record_shortfall(self, state):
        counts = action_counts(state.interview)
        if state.session.usage['DifferentialDiagnosis'].actions >= SESSION_INTERVIEW_LIMITS['DifferentialDiagnosis'][1]:
            reason = 'dd_action_limit'
        elif state.interview.collection.get('DifferentialDiagnosis:completion') == 'dd_selection_input_limit':
            reason = 'dd_selection_input_limit'
        elif not self.tools.budget.action_capacity(state):
            reason = state.session.reason or 'shared_action_limit'
        elif not self.tools.budget.collection_available(state):
            reason = self.error or 'collection_resources_unavailable'
        else:
            reason = self.error or 'registered_questions_exhausted'
        for kind, minimum in DD_MINIMUMS.items():
            key = 'DifferentialDiagnosis:' + kind + '_shortfall'
            if counts[kind] < minimum:
                state.interview.collection[key] = f'{minimum - counts[kind]}; received={counts[kind]}; reason={reason}'
            else:
                state.interview.collection.pop(key, None)

    def selection_available(self, state):
        if state.session.input_tokens >= LIMITS.dd_selection_input_tokens:
            state.interview.collection['DifferentialDiagnosis:completion'] = 'dd_selection_input_limit'
            return False
        return self.tools.budget.can_start_action(state)

    def decide(self, state, client, *, closing=False):
        if state.session.termination or state.case.assessment and state.case.assessment.frozen:
            return
        if not closing and not self.selection_available(state):
            return
        key = self.input_key(state)
        passed = tuple(sorted(k for k, v in state.interview.collection.items()
                              if k.startswith(('SAY|', 'EXAM|')) and v.startswith('passed_')))
        if not closing and self.last_input == key and self.last_passed == passed:
            return
        self.last_input = key
        self.last_passed = passed
        work = (self.prepare_decision(state, mode='rank', closing=True) if closing
                else self.prepare_selection(state))
        self.error = None
        ranking_accepted = not closing
        for attempt in range(2):
            if not closing and not self.selection_available(state):
                return
            request_messages = clinical_messages(self.config, work) if closing else self.selection_messages(work)
            response = self.brain.complete(state, client, role='clinical', messages=request_messages,
                max_tokens=LIMITS.gateway_recovery_tokens if attempt else LIMITS.gateway_tokens)
            if state.session.termination:
                self.error = response.error
                return
            if not closing and not self.selection_available(state):
                if response.error:
                    self.error = response.error
                    state.interview.collection[f'{state.interview.current}:decision'] = self.error
                return
            before = state.case.assessment
            try:
                self.accept(state, strict_json(response.content), work, ranking_accepted=ranking_accepted, closing=closing)
                self.error = None
                return
            except (ValueError, TypeError) as failure:
                ranking_accepted |= state.case.assessment is not before
                self.error = response.error or str(failure)
                if response.error and response.error not in {'OUTPUT_TRUNCATED', 'PROVIDER_RESPONSE_INVALID'}:
                    break
                if ranking_accepted and not closing:
                    work = self.prepare_selection(state)
                work.payload['validation_error'] = self.error
        state.interview.collection[f'{state.interview.current}:decision'] = self.error
        if ranking_accepted and not closing and not response.error and self.tools.budget.can_start_action(state):
            needed = required_kinds(state, work.options)
            for spec in work.options.values():
                if spec['kind'] in needed and self.tools._allowed_now(state, spec):
                    if spec['purpose'] == 'clarification':
                        usage.record_clarification(state)
                    self.tools._register(state, spec, 0, 1)
                    state.interview.collection['DifferentialDiagnosis:action_fallback'] = self.error
                    self.error = None
                    break

    def prepare(self, state, client):
        if state.turn or state.session.termination:
            return
        self.tools.questions.discard_unasked(state, {q.item_id for q in state.interview.queue
            if not q.coverage and q.purpose != 'clarification'}, reason='replanning')
        self.decide(state, client)

    def close(self, state, client, *, allow_model=True):
        if state.case.assessment and state.case.assessment.frozen:
            state.case.diagnosis = state.case.primary().name
            return
        self.record_shortfall(state)
        if state.interview.current == 'Education':
            raise ValueError('Education requires an already frozen assessment')
        if state.turn:
            raise ValueError('Cannot freeze an unfinished input')
        if allow_model and not self.final_rank_attempted:
            self.final_rank_attempted = True
            self.decide(state, client, closing=True)
        self.freeze_fallback(state)

    def freeze_fallback(self, state, reason=None):
        """Freeze current evidence or an explicitly limited working problem without a model."""
        if state.case.assessment and state.case.assessment.frozen:
            state.case.diagnosis = state.case.primary().name
            return
        assessment = state.case.assessment
        key = self.input_key(state)
        current = bool(assessment and assessment.differential and (assessment.based_on_case_revision,
            assessment.based_on_chief_fact_id, assessment.based_on_response) == key)
        reuse = not current and self.reusable_unknowns(state)
        retained = bool(assessment and assessment.differential and assessment.differential[0].kind == 'disease')
        limitations = list(assessment.limitations) if current or retained or reuse else []
        if reuse:
            limitations.append('Accepted DD ranking reused after verified exact unknown SAY replies; no new clinical facts')
            self.handled_response = key[2]
        elif not current and retained:
            limitations.append('Latest clinical input was not clinically reassessed; retain last accepted disease ranking: '
                               + (reason or self.error or 'model-free finalization'))
        if not current and not retained and not reuse:
            chief = state.case.chief(confirmed=True)
            ident = self.knowledge.term_id(chief.target, 'Symptom') if chief else None
            limitations.append(self.error or 'no_graph_disease_assessment')
            route = state.case.chief_route
            name = chief.target if ident else route.target if route and route.method != 'stable_order' and route.source_ref else 'Undifferentiated presenting complaint'
            if not ident:
                limitations.append('Working problem only; collection route does not establish a patient finding')
            assessment = Assessment(differential=(DifferentialEntry(kind='symptom', name=name,
                supports=(EvidenceRef(graph_ref=GraphRef(kind='symptom', id=ident), fact_ids=(chief.id,)),) if ident else ()),),
                based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id,
                based_on_response=key[2])
        if any(v in {'unknown', 'blocked_asset', 'budget_stopped', 'recorded_unmapped', 'unasked', 'conflict', 'unsupported', 'passed_unasked', 'passed_unknown'}
                for v in self.tools.chief_statuses(state).values()):
            limitations.append('Chief complaint details remain incomplete')
        if not any(a.key and a.key[0] == 'EXAM' and a.outcome in {'mapped', 'recorded'} for a in state.interview.answers):
            limitations.append('No additional physical examination obtained')
        if any(f.binding == 'forced' for f in state.case.facts.values()):
            limitations.append('Some patient facts use forced database approximations')
        limitations.extend(f'{key}: {value}' for key, value in state.interview.collection.items()
            if key.endswith((':completion', ':decision')) and value not in {'advance_stage', 'finish_collection'})
        limitations.extend(f'{key}: {value}' for key, value in state.interview.collection.items()
                           if key.startswith('DifferentialDiagnosis:') and key.endswith('_shortfall'))
        if self.error:
            limitations.append(self.error)
        if reason:
            limitations.append(reason)
        self.freeze_assessment(state, assessment, limitations)

    def freeze_assessment(self, state, assessment, limitations):
        """Keep accepted order and ranking basis while freezing the current case boundary."""
        # Keep the diagnosis; exclude dangling evidence rather than relabeling it as valid.
        entries = []
        try:
            current_ids = {fact.id for fact in state.case.current_facts()}
        except Exception:
            current_ids = set()
            limitations.append('Evidence validation unavailable; unverified evidence references excluded')
        for entry in assessment.differential:
            cleaned = {category: tuple(ref for ref in getattr(entry, category)
                       if all(ident in current_ids for ident in ref.fact_ids))
                       for category in ('supports', 'against', 'unresolved')}
            if any(len(cleaned[category]) != len(getattr(entry, category)) for category in cleaned):
                limitations.append('Invalid evidence references excluded')
            entries.append(entry.model_copy(update=cleaned))
        name = entries[0].name
        if not name.strip() or '\n' in name or '\r' in name or len(name.encode('utf-8')) > LIMITS.diagnosis_bytes:
            if entries[0].kind == 'symptom':
                entries[0] = DifferentialEntry(kind='symptom', name='Undifferentiated presenting complaint')
            limitations.append('Registered diagnosis display unavailable within submission format')
        state.case.diagnosis = entries[0].name
        state.case.assessment = assessment.model_copy(update={'frozen': True,
            'frozen_case_revision': state.case.revision, 'frozen_chief_fact_id': state.case.chief_fact_id,
            'differential': tuple(entries),
            'limitations': tuple(dict.fromkeys(limitations))})
