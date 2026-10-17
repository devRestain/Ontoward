# Local Evaluation Contract

## Ownership

- Keep the local evaluation API, NOVA model bridge, container definitions, and harness checks in this directory.
- Keep consultation algorithms and the unchanged SDK in root submission/.
- Read root D27 and the preserved devkit and competition references before changing simulator behavior.
- Record operational progress in root PROJECT_STATE.md without creating another state scope.

## Input Boundaries

- Read only case.json from root assets/nova-samples-2026 for simulation.
- Expose only start_information before actual SAY and EXAM responses.
- Give patient_script only to the patient role and examination rows only to examiner roles.
- Exclude model_record files from all runtime inputs and prompts.
- Keep NOVA_DEV_KEY in the NOVA simulator environment and use only session-free development chat for its model calls.
- Keep the agent on the internal case network with only submission/ and its own output directory mounted.

## Workflow

- Build the root dev image before building this directory's network-disabled derived image.
- Use sh Test/run.sh verify for maintained offline API and model-boundary checks.
- Use sh Test/run.sh C10 scripted for an isolated offline public-case consultation.
- Use the separate compose.nova.yaml overlay for explicitly scoped NOVA execution.
- Preserve each run in a fresh root Tmp/test-evaluator directory and disable automatic resumption.
- Preserve request identity, completed responses, refused turns, failed requests, and final submission receipts.
- Preserve actual Gateway request bodies and responses in simulator output so transmitted candidates can be audited without exposing credentials.
- Keep the scripted Gateway case-independent and limited to supplied source names and aliases; do not add case-to-concept fixtures or clinical synonym tables.

## Evidence

- Require the real submission/run.py process, ready handshake, nonempty Gateway response, SOAP submission, and completed receipt for consultation success; distinguish linked-chief parser evidence from that transport count.
- Mark scripted replies as test fixtures and all local results as unscored.
- Record fixture and runtime hashes in the data-owned provenance receipt.
- Report authenticated NOVA calls, official API execution, clinical accuracy, and official scoring separately.
