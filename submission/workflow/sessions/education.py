from ..education import generate_plan
from ..state.models import Answer, Question


class EducationSession:
    def __init__(self, knowledge, config, brain, mouth, questions, budget):
        self.knowledge, self.config, self.brain, self.mouth = knowledge, config, brain, mouth
        self.questions, self.budget = questions, budget

    def prepare_diagnosis(self, state, client):
        prefix = 'Education:diagnosis:'
        if any(a.question_id.startswith(prefix) for a in state.interview.answers):
            return False
        if any(q.item_id.startswith(prefix) for q in state.interview.queue):
            return True
        text, errors = self.mouth.render_diagnosis(state, client, self.knowledge)
        if text is None:
            state.interview.answers.append(Answer(question_id=prefix + '0', source_ref='', scope='Education',
                purpose='education', outcome='undelivered', reason=errors.get('diagnosis', 'diagnosis_render_failed')))
            return False
        utterances = [text]
        if state.case.primary().kind == 'symptom' and self.budget.action_capacity(state) > 1:
            utterances.append(self.config.texts.symptom_cause_unknown)
        for number, value in enumerate(utterances):
            self.questions.register(state, Question(item_id=prefix + str(number), purpose='education',
                text=value, order=-1000 + number))
        return True

    def prepare_delivery(self, state, client):
        handled = {q.plan_sentence_id for q in state.interview.queue} | {
            a.plan_sentence_id for a in state.interview.answers}
        remaining = [sentence for sentence in state.case.plan if sentence.id not in handled]
        if not remaining:
            return
        capacity = max(0, self.budget.action_capacity(state) - len(state.interview.queue))
        core = []
        for field in ('education', 'tests', 'treatment', 'disposition', 'follow_up'):
            sentence = next((s for s in remaining if s.field == field), None)
            if sentence:
                core.append(sentence)
                remaining.remove(sentence)
        ordered = [*core, *sorted(remaining, key=lambda s: s.priority != 'safety')]
        budgets = {sentence.id: 1 for sentence in ordered[:capacity]}
        for ident in list(budgets)[:max(0, capacity - len(budgets))]:
            budgets[ident] += 1
        batch = [{'id': sentence.id, 'text': sentence.text} for sentence in ordered if sentence.id in budgets]
        rendered, failures = {}, {s.id: 'delivery_budget' for s in ordered if s.id not in budgets}
        notice_error = next((a.reason for a in state.interview.answers
            if a.question_id.startswith('Education:diagnosis:') and a.outcome == 'undelivered'), None)
        if notice_error:
            failures['diagnosis'] = notice_error
        if batch:
            values, errors = self.mouth.render_education(state, client, batch, budgets, capacity)
            rendered.update(values)
            failures.update(errors)
        order = 0
        for sentence in ordered:
            utterances = rendered.get(sentence.id)
            reason = (failures.get(sentence.id, 'rendering_not_completed') if not utterances
                else 'delivery_budget' if len(utterances) > capacity else None)
            if reason:
                state.interview.answers.append(Answer(question_id=f'Education:{sentence.id}', source_ref='',
                    scope='Education', purpose='education', outcome='undelivered', plan_sentence_id=sentence.id, reason=reason))
                continue
            for number, text in enumerate(utterances):
                self.questions.register(state, Question(item_id=f'Education:{sentence.id}:{number}', purpose='education',
                    text=text, order=order, plan_sentence_id=sentence.id))
                order += 1
            capacity -= len(utterances)
        if failures:
            delivered = any(a.purpose == 'education' and a.outcome == 'delivered' for a in state.interview.answers)
            state.interview.education_status = 'partial' if rendered or delivered else 'failed'
            state.interview.education_reason = next(iter(failures.values()))

    def prepare_plan(self, state, client):
        state.case.primary()
        if state.interview.education_status != 'not_started':
            return
        if self.config.education_enabled:
            generate_plan(state, client, self.knowledge, self.config, self.brain)
        else:
            state.interview.education_status = 'disabled'

    def prepare(self, state, client):
        state.case.primary()
        if self.config.education_enabled:
            notice = self.prepare_diagnosis(state, client)
            if notice or state.session.termination:
                return
        self.prepare_plan(state, client)
        if self.config.education_enabled and not state.session.termination:
            self.prepare_delivery(state, client)
