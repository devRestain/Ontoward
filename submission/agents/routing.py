from .state import WorkflowState


def route_budget(state: WorkflowState) -> str:
    if state.interaction.termination:
        return "abort"
    if state.interaction.pending:
        return "gateway"
    if state.session.finalizing:
        return "soap"
    if not state.session.initialized:
        return "enter"
    return "select" if state.case.unasked(state.session.current) else "advance"


def route_validation(state: WorkflowState) -> str:
    if state.interaction.termination:
        return "abort"
    action = state.interaction.selected
    if action is None:
        return "budget"
    return "action_budget" if action.ready else "render"


def route_action_budget(state: WorkflowState) -> str:
    route = route_budget(state)
    if route != "select":
        return route
    return "execute" if state.interaction.selected and state.interaction.selected.ready else "budget"


def route_soap(state: WorkflowState) -> str:
    return "abort" if state.interaction.termination else "validate_submission"


def route_submission(state: WorkflowState) -> str:
    if state.interaction.termination:
        return "abort"
    return "repair_submission" if state.interaction.submission_error else "submit"


def route_after_submit(state: WorkflowState) -> str:
    return "repair_submission" if state.interaction.submission_error and not state.interaction.termination else "confirm_submission"


def route_confirmation(state: WorkflowState) -> str:
    return "finish" if state.interaction.termination == "submitted" else "abort"


def finish(state: WorkflowState) -> None:
    if state.interaction.termination != "submitted":
        raise ValueError("Normal finish requires confirmed diagnosis submission")


def abort(state: WorkflowState) -> None:
    if state.interaction.termination not in {"failed", "unknown", "expired", "closed"}:
        raise ValueError("Abort requires an explicit unsuccessful outcome")
