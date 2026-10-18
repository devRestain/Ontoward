import hashlib

from .models import PendingEmpathy, TurnContext


class InteractionLifecycle:
    def __init__(self, new_request_id):
        self.new_request_id = new_request_id

    def select_question(self, state, question):
        state.turn = TurnContext(kind='action', question_id=question.item_id,
                                 request_id=self.new_request_id(), stage='selected')

    @staticmethod
    def queue_empathy(state, signal, source_ref):
        key = hashlib.sha256(signal.quote.encode()).hexdigest()
        if signal.intent in {'repeat', 'acknowledgement'} or (signal.intent != 'renewed_request' and (
                state.interview.empathy and state.interview.empathy.key == key
                or any(a.empathy_key == key and a.outcome == 'delivered' for a in state.interview.answers))):
            return
        state.interview.empathy = PendingEmpathy(source_ref=source_ref, emotion=signal.emotion,
                                                intent=signal.intent, key=key)

    @staticmethod
    def skip_empathy(state, reason, source_id=None):
        if state.interview.empathy and (source_id is None or state.interview.empathy.source_ref == source_id):
            state.interview.empathy = None

    @staticmethod
    def clear_selected(state, ids=None):
        if state.turn and state.turn.kind == 'action' and (ids is None or state.turn.question_id in ids):
            state.turn = None
