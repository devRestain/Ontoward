class UsageAccounting:
    @staticmethod
    def record_model_request(state):
        state.session.doctor_calls += 1
        state.session.usage[state.session.current].calls += 1

    @staticmethod
    def record_tokens(state, amounts):
        state.session.input_tokens += amounts[0]
        state.session.output_tokens += amounts[1]

    @staticmethod
    def record_model_success(state, role):
        state.session.doctor_successes += 1
        if role == "gateway":
            state.session.gateway_successes += 1

    @staticmethod
    def disable_models(state):
        state.session.models_available = False

    @staticmethod
    def record_actions(state, previous_turns, remaining, *, purpose=None):
        state.session.turns_remaining = remaining
        consumed = max(0, previous_turns - remaining)
        usage = state.session.usage[state.session.current]
        usage.actions += consumed
        if purpose == "empathy":
            usage.empathy_actions += consumed

    @staticmethod
    def exhaust_turns(state):
        state.session.turns_remaining = 0

    @staticmethod
    def record_clarification(state):
        state.session.clarifications += 1

    @staticmethod
    def apply_server_budget(state, value):
        session = state.session
        session.turns_remaining = value.turns_remaining
        for remaining, used, limit in (
            (value.doctor_calls_remaining, session.doctor_calls, "call_limit"),
            (value.input_tokens_remaining, session.input_tokens, "input_token_limit"),
            (value.output_tokens_remaining, session.output_tokens, "output_token_limit"),
        ):
            if remaining is not None:
                setattr(session, limit, min(getattr(session, limit), used + remaining))
