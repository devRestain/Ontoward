import copy
import json
from pathlib import Path
import threading
import unicodedata
import uuid

from nova_sdk import Client, NovaError


MODEL = 'openai/gpt-6-luna'


def completion(text, *, prompt_tokens=20, completion_tokens=10):
    return {'id': str(uuid.uuid4()), 'object': 'chat.completion', 'model': MODEL,
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                      'total_tokens': prompt_tokens + completion_tokens}}


class NovaModels:
    def __init__(self, api_base, key, output, maximum):
        if api_base.rstrip('/') != 'https://nova.snubhai.org':
            raise ValueError('NOVA mode requires the explicit https://nova.snubhai.org origin')
        if not key.strip() or not 1 <= maximum <= 1000:
            raise ValueError('Set NOVA_DEV_KEY and a request ceiling from 1 to 1000')
        self.client = Client(api_base=api_base, token=key, session_id='', timeout=240)
        # SDK 1.0.1 treats an empty constructor ID as an environment fallback.
        self.client.session_id = ''
        self.output, self.maximum = Path(output), maximum
        self.calls, self.stopped = 0, None
        self.lock = threading.Lock()

    def complete(self, role, messages, max_tokens, request_id, *, reasoning_effort='medium'):
        with self.lock:
            if self.stopped:
                raise NovaError(self.stopped, 503)
            if self.calls >= self.maximum:
                self.stopped = 'MODEL_CALL_LIMIT'
                raise NovaError(self.stopped, 429)
            self.calls += 1
            entry = {'number': self.calls, 'request_id': request_id, 'role': role, 'model': MODEL,
                     'max_tokens': max_tokens, 'reasoning_effort': reasoning_effort, 'status': 'reserved'}
            self.record(entry)
        try:
            # A local case ID must never become an official/sample NOVA session.
            response = self.client.chat(messages, model=MODEL, reasoning_effort=reasoning_effort,
                                        max_tokens=max_tokens, request_id=request_id)
        except NovaError as error:
            if not (role in {'education', 'education_doctor', 'clinical_rank', 'clinical_decision', 'clinical_action'} and error.code == 'PROVIDER_RESPONSE_INVALID'):
                self.stopped = error.code
            self.record({**entry, 'status': 'failed_or_unknown', 'error': error.code})
            raise
        self.record({**entry, 'status': 'received', 'response': response})
        return response

    def record(self, value):
        with (self.output / 'nova-requests.jsonl').open('a') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')


from brain_double import clinical_response
from protocol import decode_context


class ScriptedModels:
    """Exercise transport and completion with fixed replies; provide no clinical quality evidence."""

    def __init__(self, case):
        self.case, self.calls = case, 0

    def complete(self, role, messages, max_tokens, request_id, *, reasoning_effort='medium'):
        self.calls += 1
        payload = decode_context(messages[-1]['content'])
        clinical = clinical_response(payload)
        if clinical is not None:
            return completion(json.dumps(clinical))
        if payload.get('task') == 'education':
            phase = payload.get('repair_phase', payload.get('phase'))
            if phase in {'read', 'combine'}:
                return completion(json.dumps({'notes': []}))
            return completion(json.dumps({'P': {field: [{'text': f'Review the {field.replace("_", " ")} plan with the patient.',
                'basis': 'model_knowledge', 'references': [], 'priority': 'routine'}]
                for field in ('tests', 'treatment', 'disposition', 'follow_up', 'education')}}))
        if payload.get('task') == 'education_doctor':
            return completion(json.dumps({'items': [{'id': row['id'], 'utterances': ['진료 계획을 함께 확인해요.']}
                for row in payload['sentences']]}, ensure_ascii=False))
        if role == 'patient':
            utterance = payload['utterance']
            text = '모르겠어요' if '?' in utterance or '？' in utterance else '알겠습니다'
            return completion(json.dumps({'content': text, 'effective_content': utterance}, ensure_ascii=False))
        if role == 'examiner':
            request = payload['request']
            row = next((f'r{number:02d}' for number, item in enumerate(self.case['exam_results'], 1)
                        if item['exam'].split(' (')[0] in request), None)
            return completion(json.dumps({'id': row} if row else {'id': None, 'reason': 'too_broad'}))
        if payload.get('task') == 'empathy':
            return completion(json.dumps({'text': '많이 힘드셨겠어요. 함께 살펴볼게요.'}, ensure_ascii=False))
        if payload.get('task') == 'input_context':
            text, question = payload['input'], payload['question']
            if not text.strip():
                return completion('{"statements":[]}')
            unknown = text.strip().rstrip('.!?') in {'모르겠어요', '모르겠습니다'}
            nonclinical = text.strip().rstrip('.!?') in {'안녕하세요', '알겠습니다', '감사합니다'}
            row = {'quote': text, 'role': 'unknown' if unknown else 'nonclinical' if nonclinical else 'clinical',
                   'assertion': 'unknown' if unknown or nonclinical else 'absent' if text.strip() in {'아니요', '없어요'} else 'present',
                   'target_terms': [text[:80]], 'subject': question.get('subject','patient') if question else 'patient',
                   'time_context': question.get('time_context','unspecified') if question else 'current'}
            if question and question.get('target', question.get('target_id')):
                row['target_terms'] = [question.get('target', question.get('target_id'))]
            if question and question.get('attribute', question.get('attribute_id')):
                row['attribute_terms'] = [question.get('attribute', question.get('attribute_id'))]
            return completion(json.dumps({'statements': [row]}, ensure_ascii=False))
        if payload.get('task') == 'input_mapping':
            mappings = []
            for statement in payload['statements']:
                candidates = statement['candidates']
                target = candidates[0] if candidates else None
                sign = '(+)' if statement['assertion'] == 'present' else '(-)'
                selected = {target['id']: sign} if target and not target['attributes'] else {}
                if target and target['attributes']:
                    attribute = target['attributes'][0]
                    if attribute['values']:
                        value = attribute['values'][0]['id']
                        selected = {target['id']: {attribute['id']: value if sign == '(+)' else {value: sign}}}
                mappings.append(selected)
            return completion(json.dumps(mappings))
        if payload.get('task') == 'terminology':
            return completion(json.dumps({'facts': [], 'clinical_content': False}))
        question, text = payload['question'], payload['input']
        is_chief = question is None or (question['purpose'] in {'chief', 'clarification'} and question['field'] == 'S.cc')
        if is_chief:
            return self.wire_completion(self.parse_chief(payload))
        facts = []
        if payload['parser_pass'] != 'expansion':
            concept = question.get('target', question.get('target_id'))
            if concept:
                attribute = question.get('attribute', question.get('attribute_id')) if question else None
                purpose = question['purpose'] if question else 'chief'
                value = {'kind': 'context' if purpose == 'context' else 'attribute' if attribute else 'symptom',
                         'text': text, 'status': 'present' if purpose == 'chief' else 'unknown',
                         'concept_ids': [concept], 'subject': question.get('subject','patient') if question else 'patient',
                         'time_context': question.get('time_context','unspecified') if question else 'current'}
                if purpose != 'context':
                    value.update(observation_id=(question['observation_id'] if question else None) or 'sample-chief',
                                 episode_id=(question['episode_id'] if question else None) or 'current')
                if attribute:
                    value['attribute_id'] = attribute
                fact = {'field': question['field'] if question else 'S.cc', 'quote': text, 'value': value}
                if question:
                    fact['record_id'] = question['item_id']
                facts.append(fact)
        return self.wire_completion({'facts': facts, 'clinical_content': text.strip().rstrip('.!?') not in
                                     {'모르겠어요', '모르겠습니다', '알겠습니다', '감사합니다'}})

    @staticmethod
    def wire_completion(parsed):
        wire = copy.deepcopy(parsed)
        for fact in wire.get('facts', []):
            fact['value'].pop('text', None)
        return completion(json.dumps(wire, ensure_ascii=False))

    def parse_chief(self, payload):
        # This protocol double ranks supplied names only; real semantic selection belongs to NOVA.
        def normalized(text):
            return ''.join(unicodedata.normalize('NFC', text).casefold().split())
        def grams(text):
            return {text[index:index + 2] for index in range(max(0, len(text) - 1))}
        quote = payload['input']
        text = normalized(quote)
        candidates = []
        for concept in payload['vocabulary']:
            if concept['kind'] != 'Symptom':
                continue
            names = [normalized(name) for name in [concept['label'], *concept.get('aliases', [])] if name.strip()]
            exact = any(name in text for name in names)
            overlap = max((len(grams(name) & grams(text)) / max(1, len(grams(name))) for name in names), default=0)
            if exact or overlap:
                candidates.append((exact, overlap, concept['id']))
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        if not candidates:
            return {'facts': [], 'needs_context': True}
        exact, _, target = candidates[0]
        if payload['parser_pass'] == 'expansion':
            repairs = []
            for fact in payload.get('unlinked_facts', []):
                if fact['quote'] == quote and (exact or fact['value']['status'] == 'uncertain'):
                    repaired = copy.deepcopy(fact)
                    repaired['value']['concept_ids'] = [target]
                    repairs.append(repaired)
            if payload.get('unlinked_facts'):
                return {'facts': repairs, 'needs_context': not bool(repairs)}
        question = payload['question']
        fact = {'field': 'S.cc', 'quote': quote, 'value': {'kind': 'symptom', 'text': quote,
                'status': 'present' if exact else 'uncertain', 'concept_ids': [target],
                'subject': 'patient', 'time_context': 'current',
                'observation_id': 'scripted-chief', 'episode_id': 'current'}}
        if question:
            fact['record_id'] = question['item_id']
        return {'facts': [fact]}
