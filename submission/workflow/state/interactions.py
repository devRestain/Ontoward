from .models import ActionSpec, ClinicalValue, InteractionEntry


class InteractionLifecycle:
    def __init__(self, new_request_id):
        self.new_request_id = new_request_id

    def select_question(self, state, question):
        state.interaction.selected = ActionSpec(question=question, content=question.text, request_id=self.new_request_id())

    @staticmethod
    def clear_selected(state, ids=None):
        selected = state.interaction.selected
        if ids is None or (selected and selected.question.item_id in ids):
            state.interaction.selected = None

    @staticmethod
    def begin_action(state):
        action = state.interaction.selected
        state.interaction.selected = None
        state.interaction.pending = action
        return action

    @staticmethod
    def record_action_attempt(state, action):
        entry = InteractionEntry(id=action.request_id, kind=action.question.kind,
            question=action.question.model_copy(deep=True),
            request={"request_id": action.request_id, "action": action.question.kind, "content": action.content})
        state.interaction.history.append(entry)
        return entry

    @staticmethod
    def record_submission_attempt(state, request):
        entry = InteractionEntry(id=request["request_id"], kind="DIAGNOSE", request=request)
        state.interaction.history.append(entry)
        return entry

    @staticmethod
    def receive_input(state, raw):
        state.interaction.incoming = raw

    def record_delivery(self, state, action, entry, response, raw):
        entry.turn = response.turn
        entry.delivered = True
        self.receive_input(state, raw)
        if action.question.purpose == "education":
            item = state.case.get(action.question.item_id)
            if item:
                item.status = "done"
                item.value = ClinicalValue(kind="education", text=action.content, status="present")
                item.source_refs = [entry.id]

    @staticmethod
    def record_initial(state, raw):
        state.interaction.history.append(InteractionEntry(id="initial", kind="initial", response=raw))

    @staticmethod
    def consume_input(state):
        state.interaction.pending = None
        state.interaction.incoming = None

    @staticmethod
    def request_clarification(state, question):
        state.interaction.needs_clarification = True
        state.interaction.clarification_target = question.model_copy(deep=True) if question else None

    @staticmethod
    def consume_clarification(state):
        state.interaction.needs_clarification = False
        state.interaction.clarification_target = None
