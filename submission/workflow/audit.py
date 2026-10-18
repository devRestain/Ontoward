def emit(sink, event, **data):
    if sink is not None:
        try:
            sink(event, **data)
        except Exception:
            # Observation cannot replace an operation's result or trigger a replay.
            pass
