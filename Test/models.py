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

    def complete(self, role, messages, max_tokens, request_id):
        with self.lock:
            if self.stopped:
                raise NovaError(self.stopped, 503)
            if self.calls >= self.maximum:
                self.stopped = 'MODEL_CALL_LIMIT'
                raise NovaError(self.stopped, 429)
            self.calls += 1
            entry = {'number': self.calls, 'request_id': request_id, 'role': role, 'model': MODEL,
                     'max_tokens': max_tokens, 'status': 'reserved'}
            self.record(entry)
        try:
            # A local case ID must never become an official/sample NOVA session.
            response = self.client.chat(messages, model=MODEL, reasoning_effort='medium',
                                        max_tokens=max_tokens, request_id=request_id)
        except NovaError as error:
            self.stopped = error.code
            self.record({**entry, 'status': 'failed_or_unknown', 'error': error.code})
            raise
        self.record({**entry, 'status': 'received', 'response': response})
        return response

    def record(self, value):
        with (self.output / 'nova-requests.jsonl').open('a') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')


class ScriptedModels:
    """Exercise transport and completion with fixed replies; provide no clinical quality evidence."""

    def __init__(self, case):
        self.case, self.calls = case, 0

    def complete(self, role, messages, max_tokens, request_id):
        self.calls += 1
        payload = json.loads(messages[-1]['content'])
        if role == 'patient':
            utterance = payload['utterance']
            text = self.case['start_information']['opening'] if '불편' in utterance else '모르겠어요'
            return completion(json.dumps({'content': text, 'effective_content': utterance}, ensure_ascii=False))
        if role == 'examiner':
            request = payload['request']
            row = next((f'r{number:02d}' for number, item in enumerate(self.case['exam_results'], 1)
                        if item['exam'].split(' (')[0] in request), None)
            return completion(json.dumps({'id': row} if row else {'id': None, 'reason': 'too_broad'}))
        if payload.get('task') == 'empathy':
            return completion(json.dumps({'text': '많이 힘드셨겠어요. 함께 살펴볼게요.'}, ensure_ascii=False))
        if payload.get('task') == 'terminology':
            return completion(json.dumps({'facts': [], 'clinical_content': False}))
        question, text = payload['question'], payload['input']
        is_chief = question is None or (question['purpose'] in {'chief', 'clarification'} and question['field'] == 'S.cc')
        if is_chief:
            return completion(json.dumps(self.parse_chief(payload), ensure_ascii=False))
        facts = []
        if payload['parser_pass'] != 'expansion':
            concept = question['target_id']
            if concept:
                attribute = question['attribute_id'] if question else None
                purpose = question['purpose'] if question else 'chief'
                value = {'kind': 'context' if purpose == 'context' else 'attribute' if attribute else 'symptom',
                         'text': text, 'status': 'present' if purpose == 'chief' else 'unknown',
                         'concept_ids': [concept], 'subject': question['subject'] if question else 'patient',
                         'time_context': question['time_context'] if question else 'current'}
                if purpose != 'context':
                    value.update(observation_id=(question['observation_id'] if question else None) or 'sample-chief',
                                 episode_id=(question['episode_id'] if question else None) or 'current')
                if attribute:
                    value['attribute_id'] = attribute
                fact = {'field': question['field'] if question else 'S.cc', 'quote': text, 'value': value}
                if question:
                    fact['record_id'] = question['item_id']
                facts.append(fact)
        return completion(json.dumps({'facts': facts, 'clinical_content': text.strip().rstrip('.!?') not in
                                     {'모르겠어요', '모르겠습니다', '알겠습니다', '감사합니다'}}, ensure_ascii=False))

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
