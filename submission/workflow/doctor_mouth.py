import json
import unicodedata
from nova_sdk import NovaError
from .state import usage
from .model_context import messages
from .rules.action import ActionResponse, content_error
from .rules.limits import LIMITS
from .state.evidence import fixed_case_payload
from .output_types import RenderedGroup
from .doctor_brain import ModelResult

class DoctorMouth:

    def __init__(self, executor, nova_session, questions, interactions, model, config, budget):
        self.executor, self.nova_session = (executor, nova_session)
        self.questions, self.interactions, self.model = (questions, interactions, model)
        self.config, self.budget = (config, budget)

    def _render(self, state, client, base, sentences, budgets, initial=None):
        pending = {row['id']: row for row in sentences}
        rendered, errors = ({}, {})
        response_repairs, format_repairs, generation_error = (0, 0, None)
        while pending and (not state.session.termination):
            payload = {**base, 'sentences': list(pending.values()), 'utterance_budgets': {ident: budgets[ident] for ident in pending}, 'validation_errors': {} if generation_error else errors}
            if generation_error:
                payload['generation_error'] = generation_error
            route = 'mouth.announcement.' + base['fixed_diagnosis']['kind'] if base.get('announcement') else 'mouth.plan'
            routes = [route]
            if generation_error:
                routes.append('mouth.response_repair')
            elif errors:
                routes.append('mouth.text_repair')
            if initial is not None:
                response = ModelResult(content=json.dumps({'items': [dict(id=ident, utterances=initial.get(ident)) for ident in pending]}))
                initial = None
            else:
                request = messages(self.config.prompt(*routes), payload)
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
                    utterances = RenderedGroup.model_validate(matches[0]).utterances
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

    def render_diagnosis(self, state, client, knowledge):
        """Return the Korean announcement without scheduling or recording delivery."""
        diagnosis = state.case.primary()
        kind = 'Disease' if diagnosis.kind == 'disease' else 'Symptom'
        if knowledge.term_id(diagnosis.name, kind) is None:
            return self.config.texts.symptom_cause_unknown, {}
        name = knowledge.label(knowledge.term_id(diagnosis.name, kind))
        texts = self.config.texts
        full = texts.diagnosis_announcement if diagnosis.kind == 'disease' else texts.symptom_announcement
        short = texts.diagnosis_announcement_short if diagnosis.kind == 'disease' else texts.symptom_announcement_short
        candidates = [unicodedata.normalize('NFC', template.format(diagnosis=name)) for template in (full, short)]
        prepared = next((value for value in candidates if not content_error(value)), None)
        text = prepared if any(('가' <= c <= '힣' for c in name)) else None
        errors = {}
        if text is None:
            base = {'task': 'education_doctor', **fixed_case_payload(state.case), 'turn_budget': 1, 'announcement': True}
            rendered, errors = self._render(state, client, base, [{'id': 'diagnosis', 'text': diagnosis.name}], {'diagnosis': 1})
            text = next(iter(rendered.get('diagnosis', [])), prepared)
        return text, errors

    def render_education(self, state, client, sentences, budgets, capacity, initial=None):
        """Render the session's allocated groups without changing their lifecycle."""
        base = {'task': 'education_doctor', **fixed_case_payload(state.case), 'turn_budget': capacity}
        return self._render(state, client, base, sentences, budgets, initial=initial)

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
        if not self.budget.can_start_action(state):
            if not self.budget.collection_available(state):
                state.session.finalizing = True
                state.turn = None
            else:
                self.questions.discard_unasked(state, {q.item_id})
            return
        attempts = []
        request = {'content': q.text, 'request_id': turn.request_id}
        turn.payload = request
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
            usage.record_actions(state, state.session.turns_remaining, response.turns_remaining)
            turn.response, turn.stage = (raw, 'received')
        except NovaError as error:
            raw = {'error': error.code}
            error_code = error.code
        except (TypeError, ValueError):
            error_code = 'invalid_action_response'
        if error_code:
            # Preserve the actual response or explicit error before any GET can fail.
            turn.response = raw if isinstance(raw, dict) else {'error': error_code}
            turn.error = error_code
            if attempts:
                try:
                    self.nova_session.refresh_snapshot(state, client, account_action=True)
                except NovaError as error:
                    state.session.budget_sync_required = True
                    state.interview.collection['action:budget_sync'] = error.code
                except (TypeError, ValueError):
                    state.session.budget_sync_required = True
                    state.interview.collection['action:budget_sync'] = 'invalid_session_after_action'
            self.questions.pass_step(state, error_code)
            if error_code == 'REQUEST_BUDGET_EXHAUSTED' and not attempts:
                state.session.finalizing = True
