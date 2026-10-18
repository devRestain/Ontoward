from functools import partial

from langgraph.graph import END, START, StateGraph

from .state.models import WorkflowState


def route_budget(state: WorkflowState) -> str:
    if state.session.termination:
        return "abort"
    if state.session.finalizing:
        return "build_soap"
    if state.interview.status == 'uninitialized':
        return "enter_session"
    return "select_question" if (state.interview.queue or state.interview.empathy) else "advance_session"


def route_validation(state: WorkflowState) -> str:
    if state.session.termination:
        return "abort"
    action = state.turn
    if action is None:
        return "check_budget"
    return "execute_action" if action.stage == 'ready' else "check_budget"


def route_after_action(state: WorkflowState) -> str:
    if state.session.termination:
        return "abort"
    return "process_input" if state.turn and state.turn.stage == 'received' else "check_budget"


def route_soap(state: WorkflowState) -> str:
    return "abort" if state.session.termination else "validate_submission"


def route_submission(state: WorkflowState) -> str:
    if state.session.termination:
        return "abort"
    return "repair_submission" if (state.turn and state.turn.error) else "submit_diagnosis"


def route_after_submit(state: WorkflowState) -> str:
    return "repair_submission" if (state.turn and state.turn.error) and not state.session.termination else "confirm_submission"


def route_confirmation(state: WorkflowState) -> str:
    return "finish" if state.session.termination == "submitted" else "abort"


def finish(state: WorkflowState) -> None:
    if state.session.termination != "submitted":
        raise ValueError("Normal finish requires confirmed diagnosis submission")


def abort(state: WorkflowState) -> None:
    if state.session.termination not in {"failed", "unknown", "expired", "closed"}:
        raise ValueError("Abort requires an explicit unsuccessful outcome")


def run_node(state, operation):
    updated = state.model_copy(deep=True)
    operation(updated)
    return WorkflowState.model_validate(updated.model_dump()).model_dump(mode='json')


def build_graph(consultation, knowledge):
    graph = StateGraph(WorkflowState)
    operations = {
        "process_initial_input": partial(consultation.ear.process_input, knowledge=knowledge, client=consultation.client),
        "process_input": partial(consultation.ear.process_input, knowledge=knowledge, client=consultation.client),
        "refresh_after_input": consultation.refresh_after_input,
        "enter_session": consultation.enter_session, "check_budget": consultation.check_budget,
        "select_question": consultation.select_action,
        "validate_action": consultation.mouth.validate_action,
        "execute_action": partial(consultation.mouth.execute_action, client=consultation.client),
        "advance_session": consultation.advance_session, "build_soap": consultation.finalize,
        "validate_submission": consultation.writer.validate_submission,
        "repair_submission": consultation.repair_submission,
        "submit_diagnosis": consultation.writer.submit_diagnosis,
        "confirm_submission": consultation.writer.confirm_submission,
        "finish": finish, "abort": abort,
    }
    for name, operation in operations.items():
        graph.add_node(name, partial(run_node, operation=operation))
    graph.add_edge(START, "process_initial_input")
    graph.add_edge("process_initial_input", "refresh_after_input")
    graph.add_edge("process_input", "refresh_after_input")
    graph.add_edge("refresh_after_input", "check_budget")
    graph.add_edge("enter_session", "check_budget")
    graph.add_conditional_edges("check_budget", route_budget, {key: key for key in ("abort", "build_soap", "enter_session", "select_question", "advance_session")})
    graph.add_edge("select_question", "validate_action")
    graph.add_conditional_edges("validate_action", route_validation, {key: key for key in ("abort", "check_budget", "execute_action")})
    graph.add_conditional_edges("execute_action", route_after_action, {key: key for key in ("abort", "process_input", "check_budget")})
    graph.add_edge("advance_session", "check_budget")
    graph.add_conditional_edges("build_soap", route_soap, {key: key for key in ("abort", "validate_submission")})
    graph.add_conditional_edges("validate_submission", route_submission, {key: key for key in ("abort", "repair_submission", "submit_diagnosis")})
    graph.add_edge("repair_submission", "validate_submission")
    graph.add_conditional_edges("submit_diagnosis", route_after_submit, {key: key for key in ("repair_submission", "confirm_submission")})
    graph.add_conditional_edges("confirm_submission", route_confirmation, {"finish": "finish", "abort": "abort"})
    graph.add_edge("finish", END)
    graph.add_edge("abort", END)
    return graph.compile()
