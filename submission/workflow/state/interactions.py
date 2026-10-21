from .models import TurnContext


class InteractionLifecycle:
    def __init__(self, new_request_id):
        self.new_request_id = new_request_id

    def select_question(self, state, question):
        state.turn = TurnContext(kind='action', question_id=question.item_id,
                                 request_id=self.new_request_id(), stage='selected')

    @staticmethod
    def clear_selected(state, ids=None):
        if state.turn and state.turn.kind == 'action' and (ids is None or state.turn.question_id in ids):
            state.turn = None
