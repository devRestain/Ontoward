import json
from pydantic import ValidationError
from .input_types import ContextInput, ContextStatement, InputResult, PatientContextFact, normalized_text
from .output_types import MappingBatch
from .model_context import messages, fact_record
from .rules.input import fact_scope, make_fact, note_fact
from .state.models import CaseFact
from .rules.limits import LIMITS
from .rules.normalization import candidate_contracts, exact_mapping, measurement_value, statement_outcome, strict_json, validate_mapping

class DoctorEar:

    def __init__(self, config, model, questions):
        self.config, self.model = (config, model)
        self.questions = questions
        self.dialogue = []

    def record_delivery(self, question, source, raw):
        if not any((row['id'] == source for row in self.dialogue)):
            self.dialogue.append({'id': source, 'kind': question.kind, 'turn': raw.get('turn'), 'doctor': question.text, 'patient': raw.get('content' if question.kind == 'SAY' else 'result', '')})

    def process_input(self, state, knowledge, client):
        turn, question = (state.turn, state.question())
        if state.session.termination or turn is None or turn.response is None:
            return
        source = turn.request_id or 'initial'
        raw = turn.response
        segments = None
        if turn.kind == 'initial':
            segments = {'opening': str(raw.get('opening', ''))}
            if raw.get('vital_signs'):
                segments['vital_signs'] = raw['vital_signs'] if isinstance(raw['vital_signs'], str) else json.dumps(raw['vital_signs'], ensure_ascii=False)
            text = '\n'.join(segments.values())
            for name, content in segments.items():
                ident = 'initial:' + name
                if not any((row['id'] == ident for row in self.dialogue)):
                    self.dialogue.append({'id': ident, 'kind': 'initial', 'patient': content})
        elif question:
            text = raw.get('content' if question.kind == 'SAY' else 'result', '')
            text = text if isinstance(text, str) else ''
            self.record_delivery(question, source, raw)
        else:
            state.stop('failed', 'unexpected_action_response')
            return
        number = raw.get('turn', LIMITS.turns - state.session.turns_remaining)
        if state.interview.current == 'Education':
            if question:
                self.questions.complete(state, question, source, outcome='delivered', turn=raw.get('turn'))
            state.turn = None
            return
        result = self._parse_text(state, knowledge, client, text, source, number, segments) if not raw.get('error') else InputResult(outcomes=['unknown'])
        if state.session.termination:
            return
        state.case.apply(result.facts, preferred=result.preferred)
        if question:

            def same_scope(fact):
                return (question.subject, question.subject_member) == (fact.subject, fact.subject_member) and (question.observation_id is None or question.observation_id == fact.observation_id) and (question.episode_id is None or question.episode_id == fact.episode_id)
            matched = [f.id for f in result.facts if f.graph_binding and same_scope(f) and (question.purpose in {'chief', 'open_inquiry'} or (question.purpose in {'intake', 'history'} and question.category == f.category) or (question.purpose not in {'intake', 'history'} and question.target == f.target and (question.attribute == f.attribute) and (question.time_context == f.time_context)))]
            notes = [n for n in result.facts if not n.graph_binding and question.category and n.category == question.category and same_scope(n)]
            outcomes = result.outcomes
            current = {f.id: f for f in state.case.current_facts()}
            conflict = any((current.get(ident) and current[ident].status == 'uncertain' for ident in matched))
            outcome = 'conflict' if conflict else 'mapped' if matched else 'not_applicable' if 'not_applicable' in outcomes else 'unknown' if 'unknown' in outcomes else 'recorded' if notes else 'unknown' if result.facts else 'unsupported' if 'unsupported' in outcomes else 'nonclinical'
            self.questions.complete(state, question, source, outcome=outcome, fact_ids=matched, turn=raw.get('turn'))
        state.turn = None

    def _call(self, state, client, payload, prompt, *, recovery=False):
        return self.model.complete(state, client, role='gateway', messages=messages(prompt, payload),
            max_tokens=LIMITS.gateway_recovery_tokens if recovery else LIMITS.gateway_tokens)

    def _project_context(self, state, question):
        facts = state.case.current_facts()
        related = set()
        if question and question.observation_id:
            related = {f.id for f in facts if f.observation_id == question.observation_id and f.episode_id == question.episode_id}
        facts = sorted(facts, key=lambda f: (f.id not in related, -f.turn, f.id))
        records = [dict(fact_record(f), source_ref=f.source_ref) for f in facts[:LIMITS.expanded_context_records]]
        refs = list(dict.fromkeys([*(f['source_ref'] for f in records), *(row['id'] for row in reversed(self.dialogue[-2:]))]))
        current = state.turn.request_id or 'initial'
        by_id = {row['id']: row for row in self.dialogue}
        current_sources = {current}
        if state.turn.kind == 'initial':
            current_sources.update({'initial:opening', 'initial:vital_signs'})
        dialogue = [by_id[ref] for ref in refs if ref in by_id and ref not in current_sources][:LIMITS.expanded_context_turns]
        return {'records': records, 'dialogue': dialogue}

    def _read_context(self, raw, payload, text, previous=None, indices=None, demographic_indices=None):
        if not isinstance(raw, dict) or not isinstance(raw.get('statements'), list):
            raise ValueError('context_requires_statement_array')
        ContextInput.model_validate({**raw, 'statements': [], 'patient_context': []})
        rows = raw['statements']
        if indices is not None and len(rows) != len(indices):
            raise ValueError('context_repair_length_mismatch')
        context = previous.model_copy(deep=True) if previous else ContextInput(statements=[ContextStatement(quote=text or ' ', role='unknown') for _ in rows])
        positions = indices if indices is not None else list(range(len(rows)))
        supplied = {f['id'] for f in payload['records']}
        observations = {f.get('observation_id') for f in payload['records']}
        episodes = {f.get('episode_id') for f in payload['records']}
        scopes = {(f.get('observation_id'), f.get('episode_id')) for f in payload['records']}
        question = payload['question']
        if question:
            observations.add(question.get('observation_id'))
            episodes.add(question.get('episode_id'))
            scopes.add((question.get('observation_id'), question.get('episode_id')))
        errors = []
        for index, row in zip(positions, rows):
            try:
                statement = ContextStatement.model_validate(row)
                if not statement.quote.strip() or statement.quote not in text:
                    raise ValueError('statement_not_in_current_input')
                if statement.correction_id and statement.correction_id not in supplied:
                    raise ValueError('correction_outside_transmitted_context')
                if statement.observation_id and statement.observation_id not in observations:
                    raise ValueError('observation_outside_transmitted_context')
                if statement.episode_id and statement.episode_id not in episodes:
                    raise ValueError('episode_outside_transmitted_context')
                if (statement.observation_id and statement.episode_id
                        and (statement.observation_id, statement.episode_id) not in scopes):
                    raise ValueError('observation_episode_pair_outside_transmitted_context')
                if statement.anchor is not None and statement.anchor >= len(context.statements):
                    raise ValueError('unknown_statement_anchor')
                if payload.get('input_segments') and not any(statement.quote in segment for segment in payload['input_segments'].values()):
                    raise ValueError('statement_crosses_input_segments')
                if statement.input_segment is not None and (not payload.get('input_segments') or statement.quote not in payload['input_segments'].get(statement.input_segment, '')):
                    raise ValueError('statement_outside_input_segment')
                if payload.get('input_segments') and statement.input_segment is None:
                    statement.input_segment = 'opening' if statement.quote in payload['input_segments']['opening'] else 'vital_signs'
                if statement.record_category=='objective_observation' and not (statement.subject=='patient' and (statement.input_segment=='vital_signs' or question and question['kind']=='EXAM')):
                    raise ValueError('objective_note_requires_objective_acquisition')
                context.statements[index] = statement
            except (TypeError, ValueError, ValidationError) as error:
                errors.append({'area': 'statements', 'index': index, 'reason': str(error)[:320], 'raw': row})
        for index in positions:
            s = context.statements[index]
            if s.anchor is not None:
                anchor = context.statements[s.anchor]
                if (s.role != 'clinical' or anchor.role != 'clinical' or anchor.focus != 'target'
                        or s.anchor == index or anchor.input_segment != s.input_segment
                        or (anchor.subject, anchor.subject_member, anchor.time_context) != (s.subject, s.subject_member, s.time_context)):
                    s.anchor = None
                elif s.focus == 'attribute' or s.measurement:
                    s.target_terms = list(dict.fromkeys([*anchor.target_terms, *s.target_terms]))[:8]
        partial = previous is not None and (indices is not None or demographic_indices is not None)
        demographic = list(context.patient_context) if previous else []
        demographic_rows = raw.get('patient_context', [])
        if not isinstance(demographic_rows, list) or len(demographic_rows) > 8:
            raise ValueError('patient_context_requires_at_most_eight_rows')
        if partial and demographic_indices is None:
            demographic_indices = []
        if demographic_indices is not None and demographic_indices and len(demographic_rows) != len(demographic_indices):
            raise ValueError('patient_context_repair_length_mismatch')
        positions = demographic_indices if demographic_indices is not None else range(len(demographic_rows))
        for index, row in zip(positions, demographic_rows):
            try:
                item = PatientContextFact.model_validate(row)
                if item.quote not in text:
                    raise ValueError('ungrounded_patient_context')
                demographic.append(item)
            except (TypeError, ValueError, ValidationError) as error:
                errors.append({'area': 'patient_context', 'index': index, 'reason': str(error)[:320], 'raw': row})
        context.patient_context = demographic
        return (context, errors)

    def _context(self, state, knowledge, client, text, segments=None):
        question = state.question()
        fixed = self._fixed_reply(question, knowledge, text)
        if fixed is not None:
            return fixed
        binding = question.model_dump(exclude_none=True, exclude_defaults=True, exclude={'text', 'priority', 'order', 'coverage', 'plan_sentence_id'}) if question else None
        if binding is not None:
            binding['kind'] = question.kind
            if question.attribute:
                attribute = knowledge.term_id(question.attribute, 'FindingAttribute')
                target = next((ident for kind in ('Symptom', 'ExamFinding', 'ContextFactor')
                    if (ident := knowledge.term_id(question.target, kind))), None)
                binding['allowed_values'] = [knowledge.term(value) for value in knowledge.get_attribute_values(attribute)]
                binding['allowed_units'] = knowledge.numeric_units(target, attribute)
        payload = {'task': 'input_context', 'phase': 'context', 'input_kind': 'reply' if question else 'initial', 'turn': LIMITS.turns - state.session.turns_remaining, 'question': binding, 'spoken_question': question.text if question else None, 'patient_context': {n.context_key: n.value for n in state.case.current_facts() if n.context_key and n.subject == 'patient' and (n.status == 'present')}, 'input_segments': segments, **self._project_context(state, question)}
        if segments is None:
            payload['input'] = text
        context, indices, demographic_indices = (None, None, None)
        review_chief = False
        route = 'input.exam' if question and question.kind == 'EXAM' else 'input.reply' if question else 'input.initial'
        for attempt in range(2):
            payload['phase'] = 'context_repair' if attempt else 'context'
            routes = [route]
            if attempt:
                routes.append('input.chief_repair' if review_chief else 'input.rows_repair' if indices is not None else 'input.repair')
            response = self._call(state, client, payload, self.config.prompt(*routes), recovery=bool(attempt))
            if state.session.termination:
                break
            try:
                context, errors = self._read_context(strict_json(response.content), payload, text, context, indices, demographic_indices)
                review_chief = False
                for i, statement in enumerate(context.statements):
                    fallback = '; '.join(dict.fromkeys(statement.target_terms + statement.attribute_terms + statement.value_terms))
                    if (statement_outcome(statement) is None and not statement.note_value
                            and not normalized_text(fallback)):
                        errors.append({'area': 'statements', 'index': i,
                            'reason': 'Unmapped content requires an English note_value',
                            'raw': statement.model_dump(exclude_defaults=True)})
                    if (question is None and statement.primary_concern and statement.subject == 'patient'
                            and statement.time_context != 'past' and statement.focus == 'target'
                            and statement_outcome(statement) == 'unknown'):
                        review_chief = True
                        errors.append({'area': 'statements', 'index': i,
                            'reason': 'Separate a reported complaint from uncertainty about its cause; keep genuinely unknown existence',
                            'raw': statement.model_dump(exclude_defaults=True)})
                if not errors:
                    break
                indices = sorted({e['index'] for e in errors if e['area'] == 'statements'})
                demographic_indices = [e['index'] for e in errors if e['area'] == 'patient_context']
                payload.update(statement_indices=indices, patient_context_indices=demographic_indices,
                    repair_statements=[e for e in errors if e['area'] == 'statements'],
                    repair_patient_context=[e for e in errors if e['area'] == 'patient_context'],
                    frozen_statements=[{'index': i, 'quote': s.quote} for i, s in enumerate(context.statements) if i not in indices])
            except (TypeError, ValueError, ValidationError) as error:
                errors = [{'reason': response.error or str(error)[:320]}]
            payload['validation_errors'] = errors
        context = context or ContextInput(statements=[ContextStatement(quote=text, role='unknown')] if text.strip() else [])
        reply = text.strip().rstrip(self.config.texts.reply_trailing_punctuation)
        if reply in self.config.texts.unknown_replies:
            context.statements = [ContextStatement(quote=text, role='unknown')]
        elif reply in set(self.config.texts.education_acknowledgements) - set(self.config.texts.present_replies):
            context.statements = [ContextStatement(quote=text, role='nonclinical')]
        return context

    def _fixed_reply(self, question, knowledge, text):
        if question is None or question.kind != 'SAY':
            return None
        texts = self.config.texts
        reply = text.strip().rstrip(texts.reply_trailing_punctuation)
        if reply in texts.unknown_replies:
            return ContextInput(statements=[ContextStatement(quote=text, role='unknown')])
        if reply in set(texts.education_acknowledgements) - set(texts.present_replies):
            return ContextInput(statements=[ContextStatement(quote=text, role='nonclinical')])
        if (question.attribute or not question.target or not question.affirmative_presence
                or question.answer_type != 'presence' or question.purpose not in {'chief', 'feature', 'ros', 'context'}):
            return None
        target = next((ident for kind in ('Symptom', 'ContextFactor')
                       if (ident := knowledge.term_id(question.target, kind))), None)
        contract = knowledge.question_contract(target, target) if target else None
        if not contract or not contract.affirmative or question.text != knowledge.question(target, target):
            return None
        status = 'present' if reply in texts.present_replies else 'absent' if reply in texts.absent_replies else None
        if status is None:
            return None
        return ContextInput(statements=[ContextStatement(quote=text, role='clinical', assertion=status,
            target_terms=[question.target], subject=question.subject, subject_member=question.subject_member,
            time_context=question.time_context, observation_id=question.observation_id,
            episode_id=question.episode_id)])

    @staticmethod
    def _mapping_payload(statements, indices, contracts, phase, feedback):
        rows = []
        for i in indices:
            statement = statements[i]
            hints = {key: getattr(statement, key) for key in ('target_terms', 'attribute_terms', 'value_terms')
                     if getattr(statement, key)}
            rows.append(dict(quote=statement.quote, focus=statement.focus, assertion=statement.assertion,
                normalized_claim=statement.note_value or '; '.join(dict.fromkeys(value for values in hints.values() for value in values)),
                meaning=dict(hints, time_context=statement.time_context,
                    **({'category': statement.record_category} if statement.record_category else {})),
                candidates=contracts[i], **({'measurement': measurement_value(statement.measurement)} if statement.measurement else {})))
        return {'task': 'input_mapping', 'phase': phase, 'statement_indices': indices,
                'statements': rows, 'validation_errors': feedback}

    def _map_batch(self, state, knowledge, client, statements, indices, contracts):
        decoded, remaining, feedback = {}, list(indices), []
        for attempt in range(2):
            if not remaining or state.session.termination:
                break
            if attempt:
                for i in remaining:
                    contracts[i] = candidate_contracts(knowledge, statements[i], state.question(), expanded=True)
                remaining = [i for i in remaining if contracts[i]]
            if not remaining:
                break
            payload = self._mapping_payload(statements, remaining, contracts,
                'mapping_repair' if attempt else 'mapping', feedback)
            routes = ['mapping.select', 'mapping.repair'] if attempt else ['mapping.select']
            response = self._call(state, client, payload, self.config.prompt(*routes), recovery=bool(attempt))
            if state.session.termination:
                break
            try:
                # Validate the envelope once and each row independently so a bad sibling
                # cannot discard an accepted mapping or force it through recovery again.
                wire = strict_json(response.content)
                if not isinstance(wire, list) or len(wire) != len(remaining):
                    raise ValueError('mapping_batch_length_or_type')
            except (TypeError, ValueError) as error:
                feedback = [{'reason': response.error or str(error)[:240]}]
                continue
            unresolved, feedback = [], []
            for i, mapping in zip(remaining, wire):
                try:
                    mapping = MappingBatch.model_validate([mapping]).root[0]
                    values = validate_mapping(mapping, statements[i], contracts[i], external=True)
                    if not values:
                        raise ValueError('unresolved_mapping')
                    decoded[i] = (values, bool(attempt))
                except (TypeError, ValueError, ValidationError) as error:
                    feedback.append({'statement_index': i, 'reason': str(error)[:240]})
                    unresolved.append(i)
            remaining = unresolved
        return decoded

    def _parse_text(self, state, knowledge, client, text, source, number, segments=None):
        context = self._context(state, knowledge, client, text, segments)
        result = InputResult()
        result.facts.extend(self._demographic_facts(state, context.patient_context, source, number, segments))
        question = state.question()
        contracts, decoded, waiting = ({}, {}, [])
        for i, statement in enumerate(context.statements):
            if statement_outcome(statement) is not None or statement.record_category=='patient_context' and any(d.quote==statement.quote for d in context.patient_context):
                continue
            contracts[i] = candidate_contracts(knowledge, statement, question)
            if not contracts[i]:
                contracts[i] = candidate_contracts(knowledge, statement, question, expanded=True)
            if not contracts[i]:
                continue
            exact = exact_mapping(knowledge, statement, contracts[i], question)
            if exact is not None:
                decoded[i] = (validate_mapping(exact, statement, contracts[i]), False)
            else:
                waiting.append(i)
        if waiting:
            decoded.update(self._map_batch(state, knowledge, client, context.statements, waiting, contracts))
        preferred = []
        for i, statement in enumerate(context.statements):
            if statement.anchor is not None:
                anchor = context.statements[statement.anchor]
                mapped = decoded.get(statement.anchor)
                target = mapped[0][0][0] if mapped else None
                observation, episode = fact_scope(anchor, self._source(anchor, source, segments),
                    statement.anchor, question, case=state.case, target=target)
                if (statement.observation_id and statement.observation_id != observation
                        or statement.episode_id and statement.episode_id != episode):
                    statement = statement.model_copy(update={'anchor': None})
                else:
                    statement = statement.model_copy(update={
                        'observation_id': statement.observation_id or observation,
                        'episode_id': statement.episode_id or episode})
            outcome = statement_outcome(statement)
            accepted = []
            if i in decoded:
                values, broader = decoded[i]
                for offset, value in enumerate(values):
                    try:
                        fact = make_fact(state.case, knowledge, statement, value, source=self._source(statement, source, segments), index=i, offset=offset, turn=number, question=question, broader=broader)
                        accepted.append(fact)
                        if statement.primary_concern or (question and question.primary_choice and (fact.category == 'presentation')):
                            preferred.append(fact.id)
                    except (TypeError, ValueError, ValidationError) as error:
                        pass
            result.facts.extend(accepted)
            if accepted:
                result.outcomes.append('mapped')
            elif statement.role in {'clinical', 'uncertain', 'unknown'} or statement.role == 'not_applicable':
                note = note_fact(statement, self._source(statement, source, segments), i, number, question)
                if note and note.category == 'patient_context' and any((d.quote == statement.quote for d in context.patient_context)):
                    note = None
                if note:
                    result.facts.append(note)
                result.outcomes.append(outcome or ('recorded' if note else 'unsupported'))
            else:
                result.outcomes.append(outcome or 'nonclinical')
        if len(set(preferred)) == 1:
            result.preferred = preferred[0]
        return result

    @staticmethod
    def _source(statement, source, segments):
        if segments is None:
            return source
        name = statement.input_segment or ('opening' if statement.quote in segments['opening'] else 'vital_signs')
        return 'initial:' + name

    def _demographic_facts(self, state, rows, source, turn, segments):
        accepted = {}
        for row in rows:
            ident = f"patient_context:{row.subject}:{row.subject_member or ''}:{row.key}"
            previous = accepted.get(ident) or state.case.facts.get(ident)
            value, measurement, status = (row.value, row.measurement, 'unknown' if row.value=='unknown' else 'present')
            if previous and (previous.value, previous.measurement) != (value, measurement) and (not row.correction):
                value = '; '.join(dict.fromkeys([previous.value, value]))
                measurement, status = (None, 'uncertain')
            ref = 'initial:opening' if segments is not None else source
            accepted[ident] = CaseFact(id=ident, category='patient_context' if row.subject == 'patient' else 'family_history', context_key=row.key if row.subject == 'patient' else None, value=value, measurement=measurement, status=status, subject=row.subject, subject_member=row.subject_member, reported_by='patient', source_ref=ref, turn=turn, acquisition=state.question().kind if state.question() else 'initial')
        historian = accepted.get('patient_context:patient::reporter') or state.case.facts.get('patient_context:patient::reporter')
        reporter = historian.value if historian and historian.status == 'present' else 'unknown' if historian else 'patient'
        return [note.model_copy(update={'reported_by': reporter}) for note in accepted.values()]
