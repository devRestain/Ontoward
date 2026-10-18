import json
from copy import deepcopy
from functools import lru_cache

from pydantic import ValidationError

from .audit import emit
from .input_types import ContextInput, ContextStatement, EmpathySignal, InputResult, PatientContextFact
from .io.model_client import ModelResult
from .rules.input import isolate_attributes, make_fact, note_fact
from .rules.limits import LIMITS
from .rules.normalization import (candidate_contracts, compact_schema, exact_mapping, force_mapping,
    mapping_schema, measurement_value, numeric_schema, statement_outcome, strict_json, validate_mapping)


@lru_cache(maxsize=1)
def parser_schema():
    schema = compact_schema(ContextInput.model_json_schema())
    schema['$defs']['ObservedNumber'] = numeric_schema()
    schema['required'] = ['statements']
    return schema


class InputInterpreter:
    def __init__(self, config, model, questions, interactions, audit=None):
        self.config, self.model = config, model
        self.questions, self.interactions, self.audit = questions, interactions, audit
        self.dialogue, self.patient_context = [], {}

    def record_delivery(self, question, source, raw):
        if not any(row['id'] == source for row in self.dialogue):
            self.dialogue.append({'id':source, 'kind':question.kind, 'turn':raw.get('turn'),
                'doctor':question.text, 'patient':raw.get('content' if question.kind == 'SAY' else 'result', '')})

    def process_input(self, state, knowledge, client):
        turn, question = state.turn, state.question()
        if state.session.termination or turn is None or turn.response is None:
            return
        source = turn.request_id or 'initial'
        raw = turn.response
        if turn.kind == 'initial':
            text = str(raw.get('opening', ''))
            if raw.get('vital_signs'):
                text += '\n' + (raw['vital_signs'] if isinstance(raw['vital_signs'], str) else json.dumps(raw['vital_signs'], ensure_ascii=False))
            if not any(row['id'] == 'initial' for row in self.dialogue):
                self.dialogue.append({'id':'initial', 'kind':'initial', 'patient':text})
        elif question:
            text = raw.get('content' if question.kind == 'SAY' else 'result', '')
            text = text if isinstance(text, str) else ''
        else:
            state.stop('failed', 'unexpected_action_response')
            return
        number = raw.get('turn', LIMITS.turns - state.session.turns_remaining)
        if state.interview.current == 'Education':
            if question:
                self.questions.complete(state, question, source, outcome='delivered', turn=raw.get('turn'))
            state.turn = None
            return
        result = self._parse_text(state, knowledge, client, text, source, number) if not raw.get('error') else InputResult(outcomes=['unknown'])
        if state.session.termination:
            return
        if self.audit is not None:
            for fact in result.facts:
                previous = state.case.facts.get(fact.id)
                if previous and previous != fact:
                    emit(self.audit, 'fact_corrected', previous=previous, replacement=fact)
        state.case.apply(result.facts, result.notes, preferred=result.preferred)
        if result.empathy:
            self.interactions.queue_empathy(state, result.empathy, source)
        if question:
            def same_scope(fact):
                return (question.subject == fact.subject
                    and (question.observation_id is None or question.observation_id == fact.observation_id)
                    and (question.episode_id is None or question.episode_id == fact.episode_id))
            matched = [f.id for f in result.facts if same_scope(f) and (
                question.purpose in {'chief', 'open_inquiry'}
                or question.purpose in {'intake', 'history'} and question.category == f.category
                or question.purpose not in {'intake', 'history'} and question.target == f.target
                    and question.attribute == f.attribute and question.time_context == f.time_context)]
            notes = [n for n in result.notes if question.category and n.category == question.category and same_scope(n)]
            outcomes = result.outcomes
            current = {f.id:f for f in state.case.current_facts()}
            conflict = any(current.get(ident) and current[ident].status == 'uncertain' for ident in matched)
            outcome = ('conflict' if conflict else 'mapped' if matched else 'not_applicable' if 'not_applicable' in outcomes else
                'unknown' if 'unknown' in outcomes else 'recorded' if notes else
                'unknown' if result.facts else 'unsupported' if 'unsupported' in outcomes else 'nonclinical')
            self.questions.complete(state, question, source, outcome=outcome, fact_ids=matched, turn=raw.get('turn'))
        emit(self.audit, 'input_applied', source_ref=source, facts=result.facts, notes=result.notes, outcomes=result.outcomes)
        state.turn = None

    @staticmethod
    def _size(messages):
        return len(json.dumps(messages, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())

    def _fit_request(self, prompt, payload, byte_limit):
        while True:
            messages = [{'role':'system', 'content':prompt}, {'role':'user', 'content':json.dumps(payload,
                        ensure_ascii=False, separators=(',', ':'), allow_nan=False)}]
            if self._size(messages) <= byte_limit:
                return messages
            if payload.get('dialogue'):
                payload['dialogue'].pop()
            elif payload.get('records'):
                payload['records'].pop()
            else:
                return None

    def _call(self, state, client, payload, prompt, limit, *, recovery=False):
        fitted = self._fit_request(prompt, payload, limit)
        if fitted is None:
            emit(self.audit, 'input_request_rejected', reason='gateway_request_overflow')
            return ModelResult(error='GATEWAY_REQUEST_OVERFLOW')
        return self.model.complete(state, client, role='gateway', messages=fitted,
            max_tokens=LIMITS.gateway_recovery_tokens if recovery else LIMITS.gateway_tokens)

    def _project_context(self, state, question, text):
        related = set()
        if question and question.observation_id:
            related = {f.id for f in state.case.current_facts() if f.observation_id == question.observation_id
                       and f.episode_id == question.episode_id}
        facts = sorted(state.case.current_facts(), key=lambda f:(f.id not in related, -f.turn, f.id))
        records = [f.model_dump(exclude_defaults=True) for f in facts[:LIMITS.expanded_context_records]]
        refs = list(dict.fromkeys([*(f['source_ref'] for f in records), *(row['id'] for row in reversed(self.dialogue[-2:]))]))
        current = state.turn.request_id or 'initial'
        by_id = {row['id']:row for row in self.dialogue}
        dialogue = [by_id[ref] for ref in refs if ref in by_id and ref != current][:LIMITS.expanded_context_turns]
        return {'records':records, 'dialogue':dialogue}

    def _read_context(self, raw, payload, text, previous=None, indices=None):
        if not isinstance(raw, dict) or not isinstance(raw.get('statements'), list):
            raise ValueError('context_requires_statement_array')
        ContextInput.model_validate({**raw, 'statements':[], 'empathy':None, 'patient_context':[]})
        rows = raw['statements']
        if indices is not None and len(rows) != len(indices):
            raise ValueError('context_repair_length_mismatch')
        context = previous.model_copy(deep=True) if previous else ContextInput(
            statements=[ContextStatement(quote=text or ' ', role='unknown') for _ in rows])
        positions = indices if indices is not None else list(range(len(rows)))
        supplied = {f['id'] for f in payload['records']}
        observations = {f.get('observation_id') for f in payload['records']}
        episodes = {f.get('episode_id') for f in payload['records']}
        question = payload['question']
        if question:
            observations.add(question.get('observation_id'))
            episodes.add(question.get('episode_id'))
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
                if statement.anchor is not None and statement.anchor >= len(context.statements):
                    raise ValueError('unknown_statement_anchor')
                context.statements[index] = statement
            except (TypeError, ValueError, ValidationError) as error:
                errors.append({'index':index, 'reason':str(error)[:320], 'raw':row})
        for index in positions:
            s = context.statements[index]
            if s.anchor is not None:
                anchor = context.statements[s.anchor]
                if (s.role != 'clinical' or (anchor.subject, anchor.subject_member, anchor.time_context) != (
                        s.subject, s.subject_member, s.time_context)):
                    s.anchor = None
                elif s.focus == 'attribute' or s.measurement:
                    s.target_terms = list(dict.fromkeys([*anchor.target_terms, *s.target_terms]))[:8]
        demographic = []
        for row in raw.get('patient_context', []) if isinstance(raw.get('patient_context', []), list) else []:
            try:
                item = PatientContextFact.model_validate(row)
                if item.quote not in text:
                    raise ValueError('ungrounded_patient_context')
                demographic.append(item)
            except (TypeError, ValueError, ValidationError):
                pass
        ambiguous = {f.key for f in demographic if len({d.value for d in demographic if d.key == f.key}) > 1}
        self.patient_context.update((f.key, f.value) for f in demographic if f.key not in ambiguous)
        if raw.get('empathy') is not None:
            try:
                signal = EmpathySignal.model_validate(raw['empathy'])
                if signal.quote in text and (not question or question['kind'] == 'SAY'):
                    context.empathy = signal
            except (TypeError, ValueError, ValidationError):
                pass
        return context, errors

    def _context(self, state, knowledge, client, text):
        question = state.question()
        binding = question.model_dump(exclude_none=True, exclude_defaults=True,
            exclude={'text', 'priority', 'order', 'coverage', 'empathy_key', 'plan_sentence_id'}) if question else None
        if binding is not None:
            binding['kind'] = question.kind
        payload = {'task':'input_context', 'phase':'context', 'input':text,
            'input_kind':'reply' if question else 'initial', 'turn':LIMITS.turns - state.session.turns_remaining,
            'question':binding, 'spoken_question':question.text if question else None,
            'patient_context':dict(self.patient_context), 'schema':deepcopy(parser_schema()),
            **self._project_context(state, question, text)}
        context, indices, last_error = None, None, None
        for attempt in range(2):
            payload['phase'] = 'context_repair' if attempt else 'context'
            limit = LIMITS.expanded_gateway_request_bytes if attempt else LIMITS.gateway_request_bytes
            if last_error == 'CONTEXT_LIMIT_EXCEEDED':
                limit = LIMITS.compact_gateway_request_bytes
            response = self._call(state, client, payload, self.config.parser_prompt, limit, recovery=bool(attempt))
            last_error = response.error
            if state.session.termination:
                break
            try:
                context, errors = self._read_context(strict_json(response.content), payload, text, context, indices)
                if not errors:
                    break
                indices = [e['index'] for e in errors]
                payload.update(statement_indices=indices, repair_statements=errors,
                    frozen_statements=[{'index':i, 'quote':s.quote} for i,s in enumerate(context.statements) if i not in indices])
                payload['schema']['properties']['statements'].update(minItems=len(indices), maxItems=len(indices))
            except (TypeError, ValueError, ValidationError) as error:
                errors = [{'reason':response.error or str(error)[:320]}]
            emit(self.audit, 'context_rejection', phase=payload['phase'], errors=errors)
            payload['validation_errors'] = errors
        context = context or ContextInput(statements=[ContextStatement(quote=text, role='unknown')] if text.strip() else [])
        reply = text.strip().rstrip(self.config.texts.reply_trailing_punctuation)
        if reply in self.config.texts.unknown_replies:
            context.statements = [ContextStatement(quote=text, role='unknown')]
        elif reply in set(self.config.texts.education_acknowledgements) - set(self.config.texts.present_replies):
            context.statements = [ContextStatement(quote=text, role='nonclinical')]
        ambiguous = [i for i,s in enumerate(context.statements) if s.primary_concern and s.subject == 'patient'
                     and s.time_context != 'past' and s.focus == 'target' and statement_outcome(s) == 'unknown']
        if question is None and ambiguous and not state.session.termination:
            repair = deepcopy(payload)
            repair.update(phase='initial_chief_repair', statement_indices=ambiguous,
                repair_statements=[{'index':i, 'statement':context.statements[i].model_dump(exclude_defaults=True)} for i in ambiguous],
                validation_errors=['Separate an observed presenting complaint from uncertainty about its cause. Keep genuine unknown existence.'])
            repair['schema']['properties']['statements'].update(minItems=len(ambiguous), maxItems=len(ambiguous))
            response = self._call(state, client, repair, self.config.parser_prompt, LIMITS.expanded_gateway_request_bytes)
            try:
                context, errors = self._read_context(strict_json(response.content), repair, text, context, ambiguous)
                if errors:
                    emit(self.audit, 'context_rejection', phase=repair['phase'], errors=errors)
            except (TypeError, ValueError, ValidationError) as error:
                emit(self.audit, 'context_rejection', phase=repair['phase'], error=response.error or str(error))
        return context

    @staticmethod
    def _mapping_payload(statements, indices, contracts, phase, feedback):
        return {'task':'input_mapping', 'phase':phase, 'statement_indices':indices,
            'statements':[{'quote':statements[i].quote, 'focus':statements[i].focus,
                'assertion':statements[i].assertion, 'candidates':contracts[i],
                **({'measurement':measurement_value(statements[i].measurement)} if statements[i].measurement else {})}
                for i in indices],
            'schema':{'type':'array', 'prefixItems':[mapping_schema(contracts[i]) for i in indices],
                      'minItems':len(indices), 'maxItems':len(indices)}, 'validation_errors':feedback}

    def _map_batch(self, state, knowledge, client, statements, indices, contracts):
        decoded, remaining, feedback, format_used = {}, list(indices), [], False
        for phase in ('mapping', 'forced'):
            if not remaining or state.session.termination:
                break
            if phase == 'forced':
                for i in remaining:
                    contracts[i] = candidate_contracts(knowledge, statements[i], state.question(), expanded=True, complete=True)
                remaining = [i for i in remaining if contracts[i]]
            if not remaining:
                break
            payload = self._mapping_payload(statements, remaining, contracts, phase, feedback)
            limit = LIMITS.gateway_request_bytes if phase == 'mapping' else LIMITS.expanded_gateway_request_bytes
            while self._fit_request(self.config.normalization_prompt, payload, limit) is None:
                largest = max(remaining, key=lambda i:len(contracts[i]))
                if len(contracts[largest]) <= 1:
                    break
                contracts[largest].pop()
                payload = self._mapping_payload(statements, remaining, contracts, phase, feedback)
            response = self._call(state, client, payload, self.config.normalization_prompt, limit, recovery=phase == 'forced')
            wire = [{} for _ in remaining]
            for attempt in range(2 if not format_used else 1):
                try:
                    wire = strict_json(response.content)
                    if not isinstance(wire, list) or len(wire) != len(remaining):
                        raise ValueError('mapping_batch_length_or_type')
                    break
                except (TypeError, ValueError) as error:
                    wire = [{} for _ in remaining]
                    emit(self.audit, 'mapping_rejection', phase=phase, error=response.error or str(error))
                    if attempt or format_used or state.session.termination:
                        break
                    format_used = True
                    payload.update(phase='format_repair', repair_phase=phase, validation_errors=[str(error)])
                    response = self._call(state, client, payload, self.config.normalization_prompt,
                        LIMITS.compact_gateway_request_bytes if response.error == 'CONTEXT_LIMIT_EXCEEDED' else limit, recovery=True)
            unresolved, feedback = [], []
            for i, mapping in zip(remaining, wire):
                try:
                    values = validate_mapping(mapping, statements[i], contracts[i])
                    if not values:
                        raise ValueError('unresolved_mapping')
                    decoded[i] = (values, phase == 'forced')
                except (TypeError, ValueError, ValidationError) as error:
                    feedback.append({'statement_index':i, 'reason':str(error)[:240]})
                    unresolved.append(i)
            emit(self.audit, 'mapping_result', phase=phase, indices=remaining, mappings=wire, errors=feedback)
            remaining = unresolved
        if not state.session.termination:
            for i in remaining:
                mapping = force_mapping(statements[i], contracts[i])
                if mapping:
                    decoded[i] = (validate_mapping(mapping, statements[i], contracts[i]), True)
                    emit(self.audit, 'forced_mapping', index=i, mapping=mapping, forced_by='deterministic')
        return decoded

    def _parse_text(self, state, knowledge, client, text, source, number):
        context = self._context(state, knowledge, client, text)
        result = InputResult(empathy=context.empathy)
        question = state.question()
        contracts, decoded, waiting = {}, {}, []
        for i, statement in enumerate(context.statements):
            if statement_outcome(statement) is not None:
                continue
            contracts[i] = candidate_contracts(knowledge, statement, question)
            if not contracts[i]:
                contracts[i] = candidate_contracts(knowledge, statement, question, expanded=True, complete=True)
            if not contracts[i]:
                continue
            exact = exact_mapping(knowledge, statement, contracts[i], question)
            if exact is not None:
                decoded[i] = (validate_mapping(exact, statement, contracts[i]), False)
            else:
                waiting.append(i)
        batch = []
        for i in waiting:
            trial = self._mapping_payload(context.statements, [*batch, i], contracts, 'mapping', [])
            if batch and self._fit_request(self.config.normalization_prompt, trial, LIMITS.gateway_request_bytes) is None:
                decoded.update(self._map_batch(state, knowledge, client, context.statements, batch, contracts))
                batch = []
            batch.append(i)
        if batch:
            decoded.update(self._map_batch(state, knowledge, client, context.statements, batch, contracts))
        preferred = []
        for i, statement in enumerate(context.statements):
            outcome = statement_outcome(statement)
            accepted = []
            if i in decoded:
                values, forced = decoded[i]
                for offset, value in enumerate(values):
                    try:
                        fact = make_fact(state.case, knowledge, statement, value, source=source, index=i, offset=offset,
                                         turn=number, question=question, forced=forced)
                        accepted.append(fact)
                        if statement.primary_concern or question and question.primary_choice and fact.category == 'presentation':
                            preferred.append(fact.id)
                    except (TypeError, ValueError, ValidationError) as error:
                        emit(self.audit, 'fact_rejection', index=i, error=str(error), source_ref=source)
            result.facts.extend(accepted)
            if accepted:
                result.outcomes.append('mapped')
            elif statement.role in {'clinical', 'uncertain', 'unknown'} or statement.role == 'not_applicable':
                note = note_fact(statement, source, i, number, question)
                if note:
                    result.notes.append(note)
                result.outcomes.append(outcome or ('recorded' if note else 'unsupported'))
            else:
                result.outcomes.append(outcome or 'nonclinical')
        result.facts = isolate_attributes(result.facts, state.case)
        if len(set(preferred)) == 1:
            result.preferred = preferred[0]
        return result
