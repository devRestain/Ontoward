from .state import CaseState, Update


def route_budget(state: CaseState) -> str:
    if state.termination is not None:
        return "finish"
    if state.budget_decision == "stop":
        raise ValueError("A stopped session needs an explicit termination result")
    if state.budget_decision == "finalize":
        if state.phase in ("education", "soap") and not state.evidence_changed:
            return "soap"
        return "synthesis"
    if state.budget_decision == "continue":
        if state.phase in ("education", "soap") and state.evidence_changed:
            return "synthesis"
        if state.candidates_initialized and state.evidence_changed:
            return "refresh"
        return "route_phase"
    raise ValueError("Budget decision has not been evaluated")


def route_action_budget(state: CaseState) -> str:
    if state.termination is not None:
        return "finish"
    if state.budget_decision == "continue":
        return "execute_action"
    return route_budget(state)


def route_phase(state: CaseState) -> str:
    if state.termination is not None:
        return "finish"
    if state.phase in ("education", "soap") and state.evidence_changed:
        return "synthesis"
    return state.phase


def route_selection(state: CaseState) -> str:
    if state.termination is not None:
        return "finish"
    return "render_action" if state.next_action is not None else "route_phase"


def route_soap(state: CaseState) -> str:
    return "finish" if state.termination is not None else "validate_submission"


def route_submission(state: CaseState) -> str:
    return "finish" if state.termination is not None else "submit"


def finish(state: CaseState) -> Update:
    if state.termination is None:
        raise ValueError("Workflow cannot finish without an explicit outcome")
    return {}
