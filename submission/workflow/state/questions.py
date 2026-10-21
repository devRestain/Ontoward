from .models import Answer


class QuestionLifecycle:
    def __init__(self, interactions):
        self.interactions = interactions

    @staticmethod
    def register(state, question):
        if not question.text or any(q.item_id == question.item_id for q in state.interview.queue):
            return
        state.interview.queue.append(question)

    def discard_unasked(self, state, ids, reason='budget_or_replanning'):
        ids = set(ids)
        if state.turn and state.turn.question_id in ids and state.turn.stage == 'received':
            raise ValueError('Cannot discard an executing question')
        for q in state.interview.queue:
            if q.item_id in ids and (q.coverage or q.purpose == 'education') and reason not in {'resolved', 'already_resolved', 'chief_changed'}:
                key = self.collection_key(q)
                if q.coverage:
                    state.interview.collection[key] = 'budget_stopped'
                if q.purpose == 'education':
                    state.interview.answers.append(Answer(question_id=q.item_id, source_ref='',
                        scope=state.interview.current, purpose=q.purpose, key=q.semantic_key(), outcome='undelivered',
                        plan_sentence_id=q.plan_sentence_id, reason=reason))
        state.interview.queue = [q for q in state.interview.queue if q.item_id not in ids]
        self.interactions.clear_selected(state, ids)

    @staticmethod
    def collection_key(question):
        if question.purpose == 'history':
            return question.category or question.item_id
        return '|'.join((*question.semantic_key(), question.category or '')) if question.purpose == 'intake' else '|'.join(question.semantic_key())

    def complete(self, state, question, source_ref, *, outcome, fact_ids=(), turn=None, reason=None):
        if any(a.source_ref == source_ref and a.question_id == question.item_id for a in state.interview.answers):
            return
        state.interview.answers.append(Answer(question_id=question.item_id, source_ref=source_ref,
            scope=state.interview.current, purpose=question.purpose, key=question.semantic_key(),
            outcome=outcome, fact_ids=tuple(fact_ids), category=question.category, turn=turn,
            coverage=question.coverage, plan_sentence_id=question.plan_sentence_id,
            reason=reason))
        state.interview.queue = [q for q in state.interview.queue if q.item_id != question.item_id]

    def reject_action(self, state, question, reason):
        self.complete(state, question, state.turn.request_id, outcome='undelivered', reason=reason)
        state.turn = None
