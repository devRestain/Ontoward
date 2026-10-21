from ..state import usage
from ..rules.decision import ActionReply, accept_ranking, clinical_messages, prepare_decision, latest_response
from ..rules.limits import LIMITS
from ..rules.normalization import strict_json
from ..state.models import Assessment, DifferentialEntry, EvidenceRef, GraphRef


class DifferentialDiagnosisSession:
    def __init__(self, knowledge, config, tools, brain):
        self.knowledge, self.config, self.tools, self.brain = knowledge, config, tools, brain
        self.last_input = None
        self.error = None

    def input_key(self, state):
        return (state.case.revision, state.case.chief_fact_id, latest_response(state))

    def freeze_problem(self, state, reason):
        """Last clinical boundary when graph-dependent freeze itself is unavailable."""
        if state.case.assessment and state.case.assessment.frozen and state.case.assessment.differential:
            state.case.diagnosis = state.case.diagnosis or state.case.assessment.differential[0].name
            return
        name = state.case.diagnosis or 'Undifferentiated presenting complaint'
        state.case.diagnosis = name
        state.case.assessment = Assessment(differential=(DifferentialEntry(kind='symptom', name=name),),
            based_on_case_revision=state.case.revision, based_on_chief_fact_id=state.case.chief_fact_id,
            based_on_response=latest_response(state), frozen=True, limitations=(reason, 'Assessment incomplete'))

    def prepare_decision(self, state, *, mode='decision', closing=False, candidates=None):
        return prepare_decision(state, self.knowledge, self.tools, mode=mode, closing=closing, candidates=candidates)

    def accept(self, state, raw, work, *, ranking_accepted=False, closing=False):
        expected = {'next_action'} if ranking_accepted else {'ranked_disease_refs'} if closing else {'ranked_disease_refs', 'next_action'}
        if not isinstance(raw, dict) or closing and set(raw) != expected:
            raise ValueError('invalid_clinical_response_fields')
        if not ranking_accepted:
            accept_ranking(state, raw, work)
        if set(raw) != expected:
            raise ValueError('invalid_clinical_response_fields')
        if closing:
            return
        action = ActionReply.model_validate({'next_action': raw['next_action']}).next_action
        if action.kind == 'ask':
            spec = work.options.get(action.question_ref)
            if not spec or not self.tools._allowed_now(state, spec) or not self.tools.budget.can_start_action(state):
                raise ValueError('question_not_executable')
            if spec['purpose'] == 'clarification':
                usage.record_clarification(state)
            self.tools._register(state, spec, 0, 1)
        else:
            state.interview.collection['DifferentialDiagnosis:completion'] = 'finish_collection'

    def decide(self, state, client, *, closing=False):
        if state.session.termination or state.case.assessment and state.case.assessment.frozen:
            return
        key = self.input_key(state)
        if self.last_input == key:
            return
        self.last_input = key
        work = self.prepare_decision(state, mode='rank' if closing else 'decision', closing=closing)
        self.error = None
        ranking_accepted = False
        for attempt in range(2):
            response = self.brain.complete(state, client, role='clinical', messages=clinical_messages(self.config, work),
                max_tokens=LIMITS.gateway_recovery_tokens if attempt else LIMITS.gateway_tokens)
            if state.session.termination:
                self.error = response.error
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
                    work = self.prepare_decision(state, mode='action', candidates=work.candidates)
                work.payload['validation_error'] = self.error
        state.interview.collection[f'{state.interview.current}:decision'] = self.error

    def prepare(self, state, client):
        if state.turn or state.session.termination:
            return
        self.tools.questions.discard_unasked(state, {q.item_id for q in state.interview.queue
            if not q.coverage and q.purpose != 'clarification'}, reason='replanning')
        self.decide(state, client)

    def close(self, state, client, *, allow_model=True):
        if state.case.assessment and state.case.assessment.frozen:
            state.case.diagnosis = state.case.diagnosis or state.case.primary().name
            return
        if state.interview.current == 'Education':
            raise ValueError('Education requires an already frozen assessment')
        if state.turn:
            raise ValueError('Cannot freeze an unfinished input')
        assessment = state.case.assessment
        key = self.input_key(state)
        if allow_model and (not assessment or (assessment.based_on_case_revision, assessment.based_on_chief_fact_id,
                assessment.based_on_response) != key):
            self.decide(state, client, closing=True)
        self.freeze_fallback(state)

    def freeze_fallback(self, state, reason=None):
        """Freeze current evidence or an explicitly limited working problem without a model."""
        if state.case.assessment and state.case.assessment.frozen:
            state.case.diagnosis = state.case.diagnosis or state.case.primary().name
            return
        assessment = state.case.assessment
        key = self.input_key(state)
        limitations = []
        if not assessment or not assessment.differential or (assessment.based_on_case_revision,
                assessment.based_on_chief_fact_id, assessment.based_on_response) != key:
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
        if self.error:
            limitations.append(self.error)
        if reason:
            limitations.append(reason)
        # Keep the diagnosis; exclude dangling evidence rather than relabeling it as valid.
        entries = []
        current_ids = {fact.id for fact in state.case.current_facts()}
        for entry in assessment.differential[:LIMITS.differential_entries]:
            cleaned = {category: tuple(ref for ref in getattr(entry, category)
                       if all(ident in current_ids for ident in ref.fact_ids))
                       for category in ('supports', 'against', 'unresolved')}
            if any(len(cleaned[category]) != len(getattr(entry, category)) for category in cleaned):
                limitations.append('Invalid evidence references excluded')
            entries.append(entry.model_copy(update=cleaned))
        name = entries[0].name
        if not name.strip() or '\n' in name or '\r' in name or len(name.encode('utf-8')) > LIMITS.diagnosis_bytes:
            entries[0] = DifferentialEntry(kind='symptom', name='Undifferentiated presenting complaint')
            limitations.append('Registered diagnosis display unavailable within submission format')
        state.case.diagnosis = entries[0].name
        state.case.assessment = assessment.model_copy(update={'frozen': True,
            'differential': tuple(entries),
            'limitations': tuple(dict.fromkeys(limitations))})
