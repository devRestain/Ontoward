import json
import unicodedata

from nova_sdk import NovaError

from .audit import emit
from .education import message_bytes, messages
from .rules.action import ActionResponse, REFUSAL_ERRORS, RESPONSE_FORMAT_ERRORS, content_error, failure_outcome
from .rules.limits import LIMITS
from .state.models import Answer, Question
from .state.evidence import patient_payload


class Doctor:
    def __init__(self, executor, nova_session, usage, questions, interactions, model, config, budget, interpreter, audit=None):
        self.executor, self.nova_session, self.usage = executor, nova_session, usage
        self.questions, self.interactions, self.model = questions, interactions, model
        self.config, self.budget, self.interpreter, self.audit = config, budget, interpreter, audit

    def prepare_education(self, state, client):
        base = {'task':'education_doctor', 'fixed_diagnosis':state.case.diagnosis.model_dump(),
                'patient':patient_payload(state.case), 'turn_budget':self.budget.action_capacity(state)}
        remaining = list(state.case.plan)
        core = []
        for field in ('education', 'tests', 'treatment', 'disposition', 'follow_up'):
            sentence = next((s for s in remaining if s.field == field), None)
            if sentence:
                core.append(sentence)
                remaining.remove(sentence)
        ordered = [*core, *sorted(remaining, key=lambda s:s.priority != 'safety')]
        batches, batch = [], []
        for sentence in ordered:
            row = {'id':sentence.id, 'text':sentence.text}
            if batch and message_bytes(messages(self.config.education_doctor_prompt, {**base, 'sentences':[*batch, row]})) > LIMITS.education_request_bytes:
                batches.append(batch)
                batch = []
            batch.append(row)
        if batch:
            batches.append(batch)
        rendered, failures = {}, {}
        for batch in batches:
            pending = {row['id']:row for row in batch}
            errors = {}
            for attempt in range(2):
                request = messages(self.config.education_doctor_prompt, {**base, 'sentences':list(pending.values()), 'validation_errors':errors})
                if message_bytes(request) > LIMITS.education_request_bytes:
                    errors = dict.fromkeys(pending, 'education_doctor_context_overflow')
                    break
                response = self.model.complete(state, client, role='education_doctor', messages=request)
                try:
                    raw = json.loads(response.content)
                    if not isinstance(raw, dict) or set(raw) != {'items'} or not isinstance(raw['items'], list):
                        raise ValueError('invalid_render_response')
                    rows = raw['items']
                except (TypeError, ValueError):
                    rows = []
                unknown = any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] not in pending for row in rows)
                errors = {}
                for ident in list(pending):
                    matches = [row for row in rows if isinstance(row, dict) and row.get('id') == ident]
                    try:
                        if unknown or len(matches) != 1 or set(matches[0]) != {'id', 'utterances'}:
                            raise ValueError('missing_duplicate_or_unexpected_render_id')
                        utterances = matches[0]['utterances']
                        if not isinstance(utterances, list) or not utterances or any(not isinstance(t, str) for t in utterances):
                            raise ValueError('expected_utterance_list')
                        utterances = [unicodedata.normalize('NFC', t) for t in utterances]
                        if any(content_error(t) or any(c in t for c in '\r\n?？') or t.startswith(('그 외에는', '그렇지 않으면', '이 경우에는'))
                               or not any('가' <= c <= '힣' for c in t) for t in utterances):
                            raise ValueError('require_standalone_NFC_1_30_Korean_statements')
                        rendered[ident] = utterances
                        del pending[ident]
                    except (TypeError, ValueError) as error:
                        errors[ident] = str(error)
                if not pending or state.session.termination or not self.budget.model_allowance(state.session, 'education_doctor'):
                    break
            failures.update(errors)
            if state.session.termination:
                break
        capacity, order = self.budget.action_capacity(state), 0
        for sentence in ordered:
            utterances = rendered.get(sentence.id)
            reason = failures.get(sentence.id, 'rendering_not_completed') if not utterances else (
                'delivery_budget' if len(utterances) > capacity else None)
            if reason:
                state.interview.answers.append(Answer(question_id=f'Education:{sentence.id}', source_ref='', scope='Education',
                    purpose='education', outcome='undelivered', plan_sentence_id=sentence.id, reason=reason))
                continue
            for number, text in enumerate(utterances):
                self.questions.register(state, Question(item_id=f'Education:{sentence.id}:{number}', purpose='education',
                    text=text, order=order, plan_sentence_id=sentence.id))
                order += 1
            capacity -= len(utterances)
        if failures:
            state.interview.education_status = 'partial' if rendered else 'failed'
            state.interview.education_reason = next(iter(failures.values()))
        emit(self.audit, 'education_rendering', rendered=rendered, errors=failures)

    def prepare_empathy(self, state, client, event):
        payload = {'task':'empathy', 'emotion':event.emotion, 'intent':event.intent,
            'patient':patient_payload(state.case),
            'previous_deliveries':sum(a.purpose == 'empathy' and a.outcome != 'undelivered' for a in state.interview.answers)}
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
            if not isinstance(raw, dict) or set(raw) != {'text'} or not isinstance(raw['text'], str):
                raise ValueError('Invalid empathy response')
            generated = unicodedata.normalize('NFC', raw['text'])
            if content_error(generated) or any(c in generated for c in '?？\r\n') or not any('가' <= c <= '힣' for c in generated):
                raise ValueError('Invalid empathy statement')
            text = generated
        except (TypeError, ValueError):
            emit(self.audit, 'empathy_prepared_fallback', source_ref=event.source_ref)
        q = Question(item_id=f'empathy:{event.source_ref}', purpose='empathy', text=text, order=-100,
                     priority=LIMITS.clarification_priority, empathy_key=event.key)
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
        q, turn = state.question(), state.turn
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
        previous, attempts = state.session.turns_remaining, []
        request = {'content':q.text, 'request_id':turn.request_id}
        raw = None
        try:
            call = client.say if q.kind == 'SAY' else client.exam
            raw = self.executor.execute(state, client, call, request, attempts, action=True)
            response = ActionResponse.model_validate(raw)
            text = response.content if q.kind == 'SAY' else response.result
            if response.status != 'OK' or text is None or response.turns_remaining != previous - 1:
                raise ValueError('Invalid action result or turn metadata')
            self.usage.record_actions(state, previous, response.turns_remaining, purpose=q.purpose)
            self.interpreter.record_delivery(q, turn.request_id, raw)
            turn.response, turn.stage = raw, 'received'
        except NovaError as error:
            raw = {'error':error.code}
            if error.code == 'REQUEST_BUDGET_EXHAUSTED' and not attempts:
                state.turn = None
                state.session.finalizing = True
            elif error.code in RESPONSE_FORMAT_ERRORS:
                turn.response, turn.stage = raw, 'received'
            elif error.code in REFUSAL_ERRORS:
                try:
                    self.nova_session.refresh_snapshot(state, client)
                    self.usage.record_actions(state, previous, state.session.turns_remaining, purpose=q.purpose)
                    if not state.session.termination:
                        turn.response, turn.stage = raw, 'received'
                except NovaError as refresh_error:
                    state.stop(failure_outcome(refresh_error), refresh_error.code)
                except (TypeError, ValueError):
                    state.stop('unknown', 'invalid_session_after_refusal')
            elif error.code == 'TURN_LIMIT_REACHED':
                self.usage.exhaust_turns(state)
                turn.response, turn.stage = raw, 'received'
            else:
                state.stop(failure_outcome(error), error.code)
        except (TypeError, ValueError):
            state.stop('unknown', 'invalid_action_response')
        emit(self.audit, 'action_exchange', request=request, response=raw, attempts=attempts)
