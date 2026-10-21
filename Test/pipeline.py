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

# Wrap imported symbols where the runtime actually calls them. Keep inner packet
# candidate loops and per-fact projection outside detailed observation.
FUNCTIONS = (
    ('workflow.doctor_ear', 'InputBinding', ('candidate_contracts', 'exact_mapping', 'validate_mapping', 'make_fact', 'note_fact')),
    ('workflow.rules.decision', 'GraphEvidence', ('graph_candidates',)),
    ('workflow.sessions.education', 'EnglishPlan', ('generate_plan',)),
    ('workflow.education', 'EnglishPlan', ('_request', 'parse_plan', 'references')),
    ('workflow.education', 'GuidelineEvidence', ('pack_passages', 'project_documents', 'source_contexts')),
    ('workflow.education', 'ModelProjection', ('fixed_case_payload',)),
    ('workflow.doctor_mouth', 'ModelProjection', ('fixed_case_payload',)),
    *((f'workflow.sessions.{name}', 'ClinicalInput', ('prepare_decision',)) for name in
      ('initiation', 'chief_complaint', 'differential_diagnosis')),
)

REQUIRED_SOURCES = ('run.py', 'nova_sdk.py', 'settings.py', 'knowledge/graph.py',
                    'knowledge/guidelines.py', 'knowledge/guideline_passages.py',
                    'workflow/education.py', 'workflow/doctor_brain.py')

# These are navigation landmarks, not mandatory calls or a compiled topology.
LANDMARKS = (
    dict(id='input', title='Input preservation', owners=['DoctorEar', 'InputBinding'],
         methods=['_fixed_reply', '_read_context', '_project_context', '_mapping_payload', 'validate_mapping', '_demographic_facts', 'make_fact', 'note_fact']),
    dict(id='evidence', title='Scoped evidence', owners=['EvidenceIndex', 'GraphEvidence'],
         methods=['from_case', 'graph_candidates']),
    dict(id='assessment', title='Assessment and action',
         owners=['InitiationSession', 'ChiefComplaintSession', 'ContextFactorSession', 'DifferentialDiagnosisSession'],
         methods=['enter', 'prepare_decision', 'accept', 'decide', 'close']),
    dict(id='budget', title='Required questions and budget', owners=['Consultation', 'BudgetPolicy'],
         methods=['refresh_requirements', 'evaluate']),
    dict(id='sync', title='Model guards and budget synchronization', owners=['DoctorBrain', 'NovaSessionClient'],
         methods=['complete', 'refresh_snapshot', 'apply_snapshot']),
    dict(id='guidelines', title='Mapped sources and literal evidence packet', owners=['GuidelineLibrary', 'GuidelineEvidence'],
         methods=['read', 'pack_passages', 'project_documents', 'source_contexts']),
    dict(id='projection', title='Shared frozen facts and diagnosis', owners=['ModelProjection'], methods=['fixed_case_payload']),
    dict(id='plan', title='Joint English and Korean plan', owners=['EnglishPlan', 'EducationSession'],
         methods=['generate_plan', '_request', 'parse_plan', 'references', 'prepare_plan', 'prepare_delivery']),
    dict(id='delivery', title='Korean validation and delivery', owners=['DoctorMouth'],
         methods=['_render', 'render_education', 'execute_action']),
    dict(id='submission', title='SOAP and completed receipt', owners=['SubmissionWriter'],
         methods=['build_soap', 'submit_diagnosis', 'confirm_submission']),
)


def metadata():
    return dict(version=2, contract='D59', landmarks=list(LANDMARKS),
                owner_fields=OWNER_FIELDS,
                required_sources=list(REQUIRED_SOURCES),
                semantics='Observed call landmarks; absence does not imply a skipped requirement')
