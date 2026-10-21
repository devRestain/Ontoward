"""Observe actual operation boundaries without adding hooks to the submitted runtime."""
from contextlib import contextmanager
from functools import wraps


BOUNDARIES = (
    ('ear', 'process_input'), ('', 'refresh_after_input'), ('', 'enter_session'),
    ('', 'check_budget'), ('', 'select_action'), ('mouth', 'validate_action'),
    ('mouth', 'execute_action'), ('', 'advance_session'), ('', 'finalize'),
    ('writer', 'validate_submission'), ('', 'repair_submission'),
    ('writer', 'submit_diagnosis'), ('writer', 'confirm_submission'),
    ('', 'pass_session'), ('writer', 'build_minimal'),
)


@contextmanager
def observing_operations(consultation, callback):
    restored = []
    depth = 0
    def notify(*args):
        try:
            callback(*args)
        except Exception:
            pass
    def wrap(operation, method):
        @wraps(operation)
        def call(state, *args, **kwargs):
            nonlocal depth
            outer = depth == 0
            depth += 1
            name = 'process_initial_input' if method == 'process_input' and state.turn and state.turn.kind == 'initial' else method
            if outer:
                notify('start', name, state, None)
            try:
                result = operation(state, *args, **kwargs)
            except BaseException as error:
                if outer:
                    notify('error', name, state, error)
                raise
            finally:
                depth -= 1
            if outer:
                notify('end', name, state, None)
            return result
        return call
    try:
        for owner, name in BOUNDARIES:
            obj = getattr(consultation, owner) if owner else consultation
            had_value, previous = name in vars(obj), vars(obj).get(name)
            operation = getattr(obj, name)
            setattr(obj, name, wrap(operation, name))
            restored.append((obj, name, had_value, previous))
        yield
    finally:
        for obj, name, had_value, previous in reversed(restored):
            if had_value:
                setattr(obj, name, previous)
            else:
                delattr(obj, name)
