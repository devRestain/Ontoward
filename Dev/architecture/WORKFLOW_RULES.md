# Workflow Rule Ownership

D47 assigns graph-bounded clinical tasks to five session objects and all model execution to one DoctorBrain; unified CaseFacts supply clinical planning and SOAP consumers. Preserve D45 official turn budgets, D42 clinical pins, D43 initial interpretation, and D44 resident state boundaries. The selected behavior and performed evidence are recorded in DECISION_STATE.md and data/provenance/algorithm-d47-2026-10-19.json. Protocol doubles do not prove model quality or clinical accuracy.

| Behavior | Runtime owner | Maintained verification |
|---|---|---|
| Current case/interview/session and disposable turn; no duplicate diagnosis or SOAP state | workflow/state/models.py, workflow/graph.py | test_lifecycle.py |
| Always-called context, exact Python binding, selective DB mapping, independent statement recovery | workflow/doctor_ear.py, workflow/rules/normalization.py | test_binding.py |
| Demographics, historian, segment-origin validation, qualified reports, acquired objective notes | workflow/doctor_ear.py, workflow/rules/input.py | test_record.py |
| Related candidate retrieval, actual mismatch references, applicability, refinement, episode isolation | workflow/rules/assessment.py, workflow/state/evidence.py | test_brain.py |
| Existing candidates protected; local references; accepted LLM rank; action-only repair | workflow/sessions/, workflow/rules/decision.py | test_brain.py, test_d47.py |
| Required chief attributes and history; existence before attributes; member-aware compact answers | workflow/sessions/, workflow/rules/questions.py, workflow/rules/collection.py, workflow/state/questions.py | test_brain.py, test_lifecycle.py |
| Last response before freeze; symptom-only closure at DD; frozen facts and rank through repair | workflow/consultation.py, workflow/sessions/differential_diagnosis.py | test_brain.py, test_record.py |
| Official remaining turns and observed costs; protected interpretation, judgment, Education and submission | workflow/rules/budget.py, workflow/state/usage.py, workflow/io/nova_session.py | test_budget.py, test_transport.py |
| Fixed diagnosis, high-effort English P, medium-effort Korean delivery, transcript-only replies | workflow/sessions/education.py, workflow/education.py, workflow/doctor_mouth.py | test_delivery.py |
| Current-call ModelResult, identical-request replay, bounded failures | workflow/doctor_brain.py, workflow/io/request_executor.py | test_transport.py |
| Observation-based SOAP, same S/O phrases in A, fifteen strings, frozen diagnosis, completed receipt | workflow/submission_writer.py, workflow/rules/submission.py | test_record.py, test_lifecycle.py |
| Admitted RDF, Korean interview, Context polarity, registered EXAM, plan, SOAP and confirmed termination | workflow/runtime.py | test_admitted.py |
| External observation leaves execution unchanged | Test/observe.py | Test/test_observer.py, Test/test_viewer.js |
| Scripted ranking/action contracts and preserved C03 accepted-state comparison | Test/brain_double.py, Test/models.py, Test/compare_d47.py | Test/test_evaluator.py, D47 comparison report |
| Independent ZIP and unchanged original SDK over internal HTTP | Dev/packaging/package_submission.py, Test harness | D47 isolated archive and SDK evidence |
| Source score decomposition retained only for preparation | Dev/ontology/contributions.py, Dev/ontology/v5.py | Frozen source metadata comparison in D46 evidence |

Runtime paths above are relative to submission/. Use root compose.yaml with Dev/tests/workflow/compose.offline.yaml for maintained behavior checks. Keep comparison and observation in Test and all test fixtures outside the ZIP. Historical scoring tests and receipts remain frozen inputs rather than compatibility requirements for the new runtime.
