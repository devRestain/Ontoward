"""DD collection requirements derived from confirmed action receipts."""
from .limits import DD_MINIMUMS, LIMITS


def received_answers(interview):
    seen = set()
    for answer in interview.answers if interview is not None else ():
        raw = answer.response or {}
        if (answer.scope != 'DifferentialDiagnosis' or len(answer.key) != 8
                or answer.key[0] not in DD_MINIMUMS or not answer.source_ref
                or answer.source_ref in seen or answer.outcome == 'undelivered'
                or raw.get('status') != 'OK' or raw.get('error')
                or type(answer.turn) is not int or not 1 <= answer.turn <= LIMITS.turns
                or type(raw.get('turn')) is not int or raw['turn'] != answer.turn
                or not isinstance(raw.get('content' if answer.key[0] == 'SAY' else 'result'), str)):
            continue
        seen.add(answer.source_ref)
        yield answer


def action_counts(interview):
    counts = dict.fromkeys(DD_MINIMUMS, 0)
    for answer in received_answers(interview):
        counts[answer.key[0]] += 1
    return counts


def requirements(state, options):
    counts = action_counts(state.interview)
    missing = {kind: max(0, minimum - counts[kind]) for kind, minimum in DD_MINIMUMS.items()}
    needed = {spec['kind'] for spec in options.values() if missing[spec['kind']]}
    return dict(required_say=missing['SAY'], required_exam=missing['EXAM'], finish_allowed=not needed)


def required_kinds(state, options):
    missing = requirements(state, options)
    return {kind for kind in DD_MINIMUMS if missing['required_' + kind.lower()]
            and any(spec['kind'] == kind for spec in options.values())}


