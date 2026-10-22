"""Protocol-only clinical replies; this deterministic double measures no model quality."""


def clinical_response(payload):
    if payload.get('task') not in {'clinical_rank','clinical_decision','clinical_action'}:
        return None
    questions = payload.get('questions',[])
    if payload.get('required', []):
        action = {'kind':'continue_required'}
    elif questions:
        question = next((q for q in questions if q.get('kind')=='EXAM'),questions[0])
        action = {'kind':'ask','question_ref':question['ref']}
    else:
        action = {'kind':'finish_collection' if payload['stage']=='DifferentialDiagnosis' else 'advance_stage'}
    result = {} if payload['task']=='clinical_rank' else {'next_action':action}
    if payload['task'] in {'clinical_rank','clinical_decision'}:
        ranked = list(payload['prior_order'])
        for candidate in payload['candidates']:
            if candidate['ref'] not in ranked and len(ranked)<2:
                ranked.append(candidate['ref'])
        result['ranked_disease_refs'] = ranked
    return result


def attach_sink(consultation, sink):
    from functools import wraps
    def emit(event, **data):
        try:
            sink(event,**data)
        except Exception:
            pass
    for obj, method in [(consultation.ear,'process_input'),(consultation.ear.model,'complete'),
                        (consultation.mouth,'execute_action'),(consultation.writer,'submit_diagnosis')]:
        original = getattr(obj,method)
        def wrap(operation, name):
            @wraps(operation)
            def call(state,*args,**kwargs):
                before = dict(state.case.facts)
                result = operation(state,*args,**kwargs)
                for ident,fact in state.case.facts.items():
                    if ident in before and before[ident]!=fact:
                        emit('fact_corrected',previous=before[ident],replacement=fact)
                emit(name,result=result)
                return result
            return call
        setattr(obj,method,wrap(original,method))
