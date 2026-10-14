from .models import ClinicalValue, RecordItem


class QuestionLifecycle:
    def __init__(self, config, interactions):
        self.config = config
        self.interactions = interactions

    def register(self, state, question):
        if state.case.get(question.item_id):
            return
        item = RecordItem(id=question.item_id, scope=state.session.current)
        if not question.text:
            item.status = "done"
            item.value = ClinicalValue(kind="text", text=self.config.texts.missing_question_text, status="unknown")
            state.interaction.issues.append(f"missing_template:{question.item_id}")
        else:
            state.questions.questions.append(question)
        state.case.put(question.field, item)

    def discard_unasked(self, state, ids):
        ids = set(ids)
        pending = state.interaction.pending
        if pending and pending.question.item_id in ids:
            raise ValueError("Cannot discard a pending question")
        if any((item := state.case.get(item_id)) and item.status != "unasked" for item_id in ids):
            raise ValueError("Cannot discard a completed record")
        state.case.remove(ids)
        state.questions.questions = [q for q in state.questions.questions if q.item_id not in ids]
        self.interactions.clear_selected(state, ids)

    @staticmethod
    def clear_session_references(state):
        state.questions.questions = []

    def reject_action(self, state, action, error):
        item = state.case.get(action.question.item_id)
        if item:
            item.status = "done"
            item.value = ClinicalValue(kind="text", text=self.config.texts.invalid_action_text, status="unknown")
        state.interaction.issues.append(f"invalid_action:{action.question.item_id}:{error}")
        self.interactions.clear_selected(state)

    def complete_unresolved(self, state, action, text, source_id):
        item = state.case.get(action.question.item_id)
        if item and item.status == "unasked":
            item.status = "done"
            item.value = ClinicalValue(kind="text", text=text or self.config.texts.unknown_text, status="unknown",
                concept_ids=[action.question.target_id] if action.question.target_id else [],
                attribute_id=action.question.attribute_id, observation_id=action.question.observation_id,
                episode_id=action.question.episode_id, subject=action.question.subject,
                time_context=action.question.time_context)
            item.source_refs = [source_id]
