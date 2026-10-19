from ..education import generate_plan


class EducationSession:
    def __init__(self, knowledge, config, brain, mouth):
        self.knowledge, self.config, self.brain, self.mouth = knowledge, config, brain, mouth

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
            notice = self.mouth.prepare_diagnosis(state, client, self.knowledge)
            if notice or state.session.termination:
                return
        self.prepare_plan(state, client)
        if self.config.education_enabled and not state.session.termination:
            self.mouth.prepare_education(state, client)
