def record_model_request(state):
    state.session.doctor_calls += 1

def record_tokens(state, amounts):
    state.session.input_tokens += amounts[0]
    state.session.output_tokens += amounts[1]

def record_model_success(state):
    state.session.doctor_successes += 1

def disable_models(state):
    state.session.models_available = False

def record_actions(state, previous_turns, remaining):
    state.session.turns_remaining = remaining
    consumed = max(0, previous_turns - remaining)
    usage = state.session.usage[state.interview.current]
    usage.actions += consumed

def record_clarification(state):
    state.session.clarifications += 1

def apply_server_budget(state, value):
    session = state.session
    if session.fixed_pending_turns is not None:
        session.fixed_actions += max(0, session.fixed_pending_turns - value.turns_remaining)
        session.fixed_pending_turns = None
    session.turns_remaining = value.turns_remaining
    if value.doctor_calls_remaining is not None:
        session.call_limit = min(session.call_limit, session.doctor_calls + value.doctor_calls_remaining)
    if value.input_tokens_remaining is not None:
        session.input_token_limit = min(session.input_token_limit, session.input_tokens + value.input_tokens_remaining)
    if value.output_tokens_remaining is not None:
        session.output_token_limit = min(session.output_token_limit, session.output_tokens + value.output_tokens_remaining)
