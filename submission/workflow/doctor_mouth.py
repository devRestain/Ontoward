import json
import unicodedata
from nova_sdk import NovaError
from .education import message_bytes, messages
from .rules.action import ActionResponse, REFUSAL_ERRORS, RESPONSE_FORMAT_ERRORS, content_error, failure_outcome
from .rules.limits import LIMITS
from .state.models import Answer, Question
from .state.evidence import patient_payload

class DoctorMouth:

    def __init__(self, executor, nova_session, usage, questions, interactions, model, config, budget):
        self.executor, self.nova_session, self.usage = (executor, nova_session, usage)
        self.questions, self.interactions, self.model = (questions, interactions, model)
        self.config, self.budget = (config, budget)

    def _render(self, state, client, base, sentences, budgets):
        pending = {row['id']: row for row in sentences}
        rendered, errors = ({}, {})
        response_repairs, format_repairs, generation_error = (0, 0, None)
        while pending and (not state.session.termination):
            payload = {**base, 'sentences': list(pending.values()), 'utterance_budgets': {ident: budgets[ident] for ident in pending}, 'validation_errors': {} if generation_error else errors}
            if generation_error:
                payload['generation_error'] = generation_error
            request = messages(self.config.education_doctor_prompt, payload)
            if message_bytes(request) > LIMITS.education_request_bytes:
                errors = dict.fromkeys(pending, 'education_doctor_context_overflow')
                break
            response = self.model.complete(state, client, role='education_doctor', messages=request)
            if response.error:
                errors = dict.fromkeys(pending, response.error)
                if response.error not in {'PROVIDER_RESPONSE_INVALID', 'OUTPUT_TRUNCATED'} or response_repairs:
                    break
                response_repairs += 1
                generation_error = response.error
                continue
            generation_error = None
            try:
                raw = json.loads(response.content)
                if not isinstance(raw, dict) or set(raw) != {'items'} or (not isinstance(raw['items'], list)):
                    raise ValueError('invalid_render_response')
                rows = raw['items']
            except (TypeError, ValueError):
                rows = []
            unknown = any((not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] not in pending for row in rows))
            errors = {}
            for ident in list(pending):
                matches = [row for row in rows if isinstance(row, dict) and row.get('id') == ident]
                utterances = []
                try:
                    if unknown or len(matches) != 1 or set(matches[0]) != {'id', 'utterances'}:
                        raise ValueError('missing_duplicate_or_unexpected_render_id')
                    utterances = matches[0]['utterances']
                    if not isinstance(utterances, list) or not utterances or any((not isinstance(t, str) for t in utterances)):
                        utterances = []
                        raise ValueError('expected_utterance_list')
                    utterances = [unicodedata.normalize('NFC', t) for t in utterances]
                    if any((content_error(t) or any((c in t for c in '\r\n?？')) or t.startswith(('그 외에는', '그렇지 않으면', '이 경우에는')) or (not any(('가' <= c <= '힣' for c in t))) for t in utterances)):
                        raise ValueError('require_standalone_NFC_1_30_Korean_statements')
                    if len(utterances) > budgets[ident]:
                        raise ValueError('utterance_budget_exceeded')
                    rendered[ident] = utterances
                    del pending[ident]
                except (TypeError, ValueError) as error:
                    errors[ident] = {'code': str(error), 'utterances': utterances, 'codepoints': [len(t) for t in utterances], 'max_codepoints': LIMITS.content_codepoints, 'max_utterances': budgets[ident]}
            if not pending or format_repairs:
                break
            format_repairs += 1
        return (rendered, {ident: value['code'] if isinstance(value, dict) else value for ident, value in errors.items()})

    def prepare_diagnosis(self, state, client, knowledge):
        prefix = 'Education:diagnosis:'
        if any((a.question_id.startswith(prefix) for a in state.interview.answers)):
            return False
        if any((q.item_id.startswith(prefix) for q in state.interview.queue)):
            return True
        diagnosis = state.case.primary()
        kind = 'Disease' if diagnosis.kind == 'disease' else 'Symptom'
        name = knowledge.label(knowledge.term_id(diagnosis.name, kind))
        texts = self.config.texts
        full = texts.diagnosis_announcement if diagnosis.kind == 'disease' else texts.symptom_announcement
        short = texts.diagnosis_announcement_short if diagnosis.kind == 'disease' else texts.symptom_announcement_short
        candidates = [unicodedata.normalize('NFC', template.format(diagnosis=name)) for template in (full, short)]
        prepared = next((value for value in candidates if not content_error(value)), None)
        text = prepared if any(('가' <= c <= '힣' for c in name)) else None
        errors = {}
        if text is None:
            base = {'task': 'education_doctor', 'fixed_diagnosis': diagnosis.model_dump(), 'patient': patient_payload(state.case), 'turn_budget': 1, 'announcement': True}
            rendered, errors = self._render(state, client, base, [{'id': 'diagnosis', 'text': diagnosis.name}], {'diagnosis': 1})
            text = next(iter(rendered.get('diagnosis', [])), prepared)
        if text is None:
            state.interview.answers.append(Answer(question_id=prefix + '0', source_ref='', scope='Education', purpose='education', outcome='undelivered', reason=errors.get('diagnosis', 'diagnosis_render_failed')))
            return False
        utterances = [text]
        if diagnosis.kind == 'symptom' and self.budget.action_capacity(state) > 1:
            utterances.append(texts.symptom_cause_unknown)
        for number, value in enumerate(utterances):
            self.questions.register(state, Question(item_id=prefix + str(number), purpose='education', text=value, order=-1000 + number))
        return True

    def prepare_education(self, state, client):
        capacity = max(0, self.budget.action_capacity(state) - len(state.interview.queue))
        base = {'task': 'education_doctor', 'fixed_diagnosis': state.case.fixed_diagnosis(), 'patient': patient_payload(state.case), 'turn_budget': capacity}
        remaining, core = (list(state.case.plan), [])
        for field in ('education', 'tests', 'treatment', 'disposition', 'follow_up'):
            sentence = next((s for s in remaining if s.field == field), None)
            if sentence:
                core.append(sentence)
                remaining.remove(sentence)
        ordered = [*core, *sorted(remaining, key=lambda s: s.priority != 'safety')]
        budgets = {sentence.id: 1 for sentence in ordered[:capacity]}
        for ident in list(budgets)[:max(0, capacity - len(budgets))]:
            budgets[ident] += 1
        batches, batch = ([], [])
        for sentence in ordered:
            if sentence.id not in budgets:
                continue
            row = {'id': sentence.id, 'text': sentence.text}
            if batch and message_bytes(messages(self.config.education_doctor_prompt, {**base, 'sentences': [*batch, row], 'utterance_budgets': budgets})) > LIMITS.education_request_bytes:
                batches.append(batch)
                batch = []
            batch.append(row)
        if batch:
            batches.append(batch)
        rendered, failures = ({}, {s.id: 'delivery_budget' for s in ordered if s.id not in budgets})
        notice_error = next((a.reason for a in state.interview.answers if a.question_id.startswith('Education:diagnosis:') and a.outcome == 'undelivered'), None)
        if notice_error:
            failures['diagnosis'] = notice_error
        for batch in batches:
            values, errors = self._render(state, client, base, batch, budgets)
            rendered.update(values)
            failures.update(errors)
            if state.session.termination:
                break
        order = 0
        for sentence in ordered:
            utterances = rendered.get(sentence.id)
            reason = failures.get(sentence.id, 'rendering_not_completed') if not utterances else 'delivery_budget' if len(utterances) > capacity else None
            if reason:
                state.interview.answers.append(Answer(question_id=f'Education:{sentence.id}', source_ref='', scope='Education', purpose='education', outcome='undelivered', plan_sentence_id=sentence.id, reason=reason))
                continue
            for number, text in enumerate(utterances):
                self.questions.register(state, Question(item_id=f'Education:{sentence.id}:{number}', purpose='education', text=text, order=order, plan_sentence_id=sentence.id))
                order += 1
            capacity -= len(utterances)
        if failures:
            delivered = any((a.purpose == 'education' and a.outcome == 'delivered' for a in state.interview.answers))
            state.interview.education_status = 'partial' if rendered or delivered else 'failed'
            state.interview.education_reason = next(iter(failures.values()))

    def prepare_empathy(self, state, client, event):
        payload = {'task': 'empathy', 'emotion': event.emotion, 'intent': event.intent, 'patient': patient_payload(state.case), 'previous_deliveries': sum((a.purpose == 'empathy' and a.outcome != 'undelivered' for a in state.interview.answers))}
        request = messages(self.config.empathy_prompt, payload)
        if message_bytes(request) > LIMITS.gateway_request_bytes:
            self.interactions.skip_empathy(state, 'empathy_request_overflow')
            return
        response = self.model.complete(state, client, role='empathy', messages=request)
        if state.session.termination:
            return
        text = self.config.texts.empathy_fallback
        try:
            raw = json.loads(response.content)
            if not isinstance(raw, dict) or set(raw) != {'text'} or (not isinstance(raw['text'], str)):
                raise ValueError('Invalid empathy response')
            generated = unicodedata.normalize('NFC', raw['text'])
            if content_error(generated) or any((c in generated for c in '?？\r\n')) or (not any(('가' <= c <= '힣' for c in generated))):
                raise ValueError('Invalid empathy statement')
            text = generated
        except (TypeError, ValueError):
            pass
        q = Question(item_id=f'empathy:{event.source_ref}', purpose='empathy', text=text, order=-100, priority=LIMITS.clarification_priority, empathy_key=event.key)
        self.questions.register(state, q)
        self.interactions.select_question(state, q)

    def validate_action(self, state):
        q = state.question()
        if q is None or state.session.termination:
            return
        q.text = unicodedata.normalize('NFC', q.text)
        error = content_error(q.text) or ('not_allowed' if q.kind not in state.session.allowed_actions else None)
        if error:
            self.questions.reject_action(state, q, error)
        else:
            state.turn.stage = 'ready'

    def execute_action(self, state, client):
        q, turn = (state.question(), state.turn)
        if q is None or turn.stage != 'ready' or state.session.termination:
            return
        if self.budget.seconds_left(state.session) <= 0:
            state.stop('expired', 'session_expired')
            return
        if not self.budget.can_start_action(state, purpose=q.purpose):
            if not self.budget.collection_available(state):
                state.session.finalizing = True
                state.turn = None
            else:
                self.questions.discard_unasked(state, {q.item_id})
            return
        attempts = []
        request = {'content': q.text, 'request_id': turn.request_id}
        raw, error_code = (None, None)
        try:
            call = client.say if q.kind == 'SAY' else client.exam
            raw = self.executor.execute(state, client, call, request, attempts, action=True)
            response = ActionResponse.model_validate(raw)
            if response.turn + response.turns_remaining != LIMITS.turns:
                raise ValueError('Invalid action turn metadata')
            text = response.content if q.kind == 'SAY' else response.result
            if response.status != 'OK' or text is None:
                raise ValueError('Invalid action result')
            self.usage.record_actions(state, state.session.turns_remaining, response.turns_remaining, purpose=q.purpose)
            turn.response, turn.stage = (raw, 'received')
        except NovaError as error:
            raw = {'error': error.code}
            error_code = error.code
        except (TypeError, ValueError):
            error_code = 'invalid_action_response'
        if error_code:
            if attempts:
                try:
                    self.nova_session.refresh_snapshot(state, client, action_purpose=q.purpose)
                except NovaError as error:
                    state.stop(failure_outcome(error), error.code)
                except (TypeError, ValueError):
                    state.stop('unknown', 'invalid_session_after_action')
            if not state.session.termination:
                if error_code == 'REQUEST_BUDGET_EXHAUSTED' and (not attempts):
                    state.turn = None
                    state.session.finalizing = True
                elif error_code in RESPONSE_FORMAT_ERRORS or error_code in REFUSAL_ERRORS or error_code == 'TURN_LIMIT_REACHED':
                    turn.response, turn.stage = (raw, 'received')
                elif error_code == 'invalid_action_response':
                    state.stop('unknown', error_code)
                else:
                    state.stop(failure_outcome(NovaError(error_code)), error_code)
