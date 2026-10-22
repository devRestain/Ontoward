"""Discard fixed social replies at local persistence boundaries."""
import json


# Keep the standalone simulator independent of submission imports. The maintained
# fixed-utterance test checks these exact literals against the runtime contract.
FIXED_UTTERANCES = frozenset({
    '안녕하세요. 온토워드입니다. 15분 진료하겠습니다.',
    '진료실 분위기는 편안한가요? 진료해도 괜찮을까요?',
    '수고하셨습니다. 오늘 진료 협조해주셔서 감사합니다.',
    '앞으로 무탈하시도록 함께 노력해봅시다. 감사합니다.',
})


def fixed_action(body):
    return isinstance(body, dict) and body.get('action') == 'SAY' and body.get('content') in FIXED_UTTERANCES


def fixed_patient_request(role, messages):
    if role != 'patient':
        return False
    try:
        return json.loads(messages[-1]['content']).get('utterance') in FIXED_UTTERANCES
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return False


def response_metadata(response):
    keys = {'id', 'object', 'model', 'status', 'turn', 'turns_remaining', 'usage'}
    return {**{key: value for key, value in response.items() if key in keys},
            'reply_discarded': True} if isinstance(response, dict) else {'reply_discarded': True}


def recorded_model_response(role, messages, response):
    return response_metadata(response) if fixed_patient_request(role, messages) else response
