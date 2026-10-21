"""Test-owned coverage contract for the sequential consultation inspector."""

# Only these collaborator fields may be serialized; never inspect service __dict__.
OWNER_FIELDS = {
    'InitiationSession': ('closed', 'error'),
    'ChiefComplaintSession': ('closed', 'error'),
    'ContextFactorSession': ('candidate_ids', 'rules'),
    'DifferentialDiagnosisSession': ('last_input', 'error'),
    'EducationSession': ('generated_utterances',),
    'BudgetPolicy': ('required_counts',),
}

# These are navigation landmarks, not mandatory calls or a compiled topology.
LANDMARKS = (
    dict(id='input', title='Input preservation', owners=['DoctorEar', 'InputBinding'],
         methods=['_fixed_reply', '_read_context', '_demographic_facts', 'make_fact', 'note_fact']),
    dict(id='evidence', title='Scoped evidence', owners=['EvidenceIndex', 'GraphEvidence'],
         methods=['from_case', 'graph_candidates']),
    dict(id='assessment', title='Assessment and action',
         owners=['InitiationSession', 'ChiefComplaintSession', 'ContextFactorSession', 'DifferentialDiagnosisSession'],
         methods=['enter', 'prepare_decision', 'accept', 'decide', 'close']),
    dict(id='budget', title='Required questions and budget', owners=['Consultation', 'BudgetPolicy'],
         methods=['refresh_requirements', 'evaluate']),
    dict(id='plan', title='Joint English and Korean plan', owners=['EnglishPlan', 'EducationSession'],
         methods=['generate_plan', 'parse_plan', 'references', 'prepare_plan', 'prepare_delivery']),
    dict(id='delivery', title='Korean validation and delivery', owners=['DoctorMouth'],
         methods=['_render', 'render_education', 'execute_action']),
    dict(id='submission', title='SOAP and completed receipt', owners=['SubmissionWriter'],
         methods=['build_soap', 'submit_diagnosis', 'confirm_submission']),
)


def metadata():
    return dict(version=1, contract='D50', landmarks=list(LANDMARKS),
                owner_fields=OWNER_FIELDS,
                semantics='Observed call landmarks; absence does not imply a skipped requirement')
