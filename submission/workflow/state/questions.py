from .models import Answer


class QuestionLifecycle:
    def __init__(self, interactions):
        self.interactions = interactions

    @staticmethod
    def register(state, question):
        if (not question.text or any(q.item_id == question.item_id for q in state.interview.queue)
                or state.interview.collection.get(QuestionLifecycle.collection_key(question), '').startswith('passed_')
                or 'pass:' + question.item_id in state.interview.collection):
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
            reason=reason, response=state.turn.response if state.turn else None))
        state.interview.queue = [q for q in state.interview.queue if q.item_id != question.item_id]

    def reject_action(self, state, question, reason):
        self.pass_step(state, reason)

    def pass_step(self, state, reason, *, operation=None):
        """Consume one attempt after preserving its actual input and request identity."""
        turn, question = state.turn, state.question()
        if turn and turn.kind == 'submission':
            raise ValueError('Cannot pass a final submission')
        if question:
            raw = turn.response
            received = bool(raw and not raw.get('error') and turn.stage == 'received')
            key = self.collection_key(question)
            state.interview.collection[key] = 'passed_unknown' if received else 'passed_unasked'
            state.interview.collection['|'.join(question.semantic_key())] = state.interview.collection[key]
            state.interview.collection['pass:' + question.item_id] = reason
            # No fabricated Answer or turn for a locally rejected, unsent question.
            if raw is not None or turn.payload is not None:
                self.complete(state, question, turn.request_id or '',
                    outcome='undelivered' if question.purpose == 'education' or not received else 'unknown',
                    turn=raw.get('turn') if received else None, reason=reason)
            else:
                state.interview.queue = [q for q in state.interview.queue if q.item_id != question.item_id]
        if operation:
            state.interview.collection[operation] = reason
        state.turn = None
        if question and state.interview.current == 'DifferentialDiagnosis':
            state.interview.status = 'needs_preparation'
