# Application Contract

## Ownership and Lifetime

- Apply root PRD.md and D44 for information ownership while preserving D38 reasoning, D40 budgets, D42 asset pins, and D43 initial interpretation.
- Keep run.py limited to SDK callbacks from workflow/runtime.py and Consultation as the sole five-session coordinator.
- Prepare patient-free knowledge, term indexes, question wording, policy, and configuration once in PreparedResources.
- Keep exactly case, interview, session, and optional turn in WorkflowState; preserve deep-copy and Pydantic isolation between LangGraph nodes.
- Keep acquired facts, notes, chief fact ID, final diagnosis, final English plan, and clinical revision in CaseState.
- Keep current-session pending questions, compact answer receipts, necessary collection interruptions, and pending emotional codes in InterviewState.
- Keep external constraints, latest limits, once-only usage, termination, and the completed receipt in SessionContext.
- Keep only the current question ID, request ID, execution stage, response, and submission payload/repair in TurnContext; clear it after input acceptance or termination.
- Keep ModelResult, InputResult, context rows, candidates, mappings, errors, repairs, and source documents local to their calling operation.
- Keep one ClinicalReasoner per consultation, inject it into planner and writer, and replace its latest actual cache on clinical revision or chief changes.
- Keep hypothetical patches, paths, and simulation caches local to one question evaluation; never attach them to queued questions or graph state.
- Keep actual dialogue once in InputInterpreter for reference resolution and clear dialogue and reasoner caches in consult's finally boundary.
- Send detailed exchanges, rejected rows, replaced facts, and generation work to optional Test observation; never read audit back for execution.
- Make observation failures nonfatal and preserve original request identity and errors without replaying completed actions.
- Do not restore removed state shapes, compatibility properties, patient placeholders, ClinicalValue wrappers, or CanonicalSnapshot copies.

## Input and Accepted Patient Information

- Run process_initial_input before the first SAY and always analyze each collection SAY or EXAM reply with the designated model.
- Use exact current quotations and validate supplied correction, observation, episode, subject, and relationship references at input acceptance.
- Preserve independent valid context rows and repair only failed row indices once; retain the focused initial-chief recovery for genuine cause-versus-existence uncertainty.
- Bind exact admitted labels and aliases in Python before requesting normalization; send only unresolved clinical statements with nonempty compatible candidates.
- Use official English clinical terms in clinical fields and mapping keys; resolve RDF IDs through prepared kind-specific term indexes and attribute-scoped value indexes.
- Validate target-attribute relationships, scoped values, polarity, finite reported numbers, bounds, units, and approximation before constructing facts.
- Keep patient ObservedNumber separate from graph ExpectedValue; never invent NRS, calendar conversion, growth rate, thresholds, or symptom presence from a number.
- Keep registered orphan attributes record_only until a confirmed same-occurrence target exists; exclude them and notes from diagnostic evidence.
- Use ordinary mapping and final forced mapping with one batch format repair; freeze accepted siblings and remove binding_repair.
- Force only explicit clinical assertions with compatible supplied candidates, preserve acquisition and scope, and retain a minimal forced marker on the fact.
- Preserve useful unsupported information as NoteFact in existing categories with concise English values and separate typed measurements; never copy patient quotations into SOAP.
- Preserve previous treatment denial and watchful observation as previous_care notes without negating or affirming the chief symptom.
- Preserve family members, reporters, time points, observations, episodes, nonexclusive values, qualified negation, and independent fact IDs.
- Replace acquired facts only through validated same-target, subject, attribute, occurrence, time, and acquisition corrections; audit the replaced value.
- Reject patient SAY corrections of initial or EXAM evidence and require actual EXAM acquisition for finding facts and finding attributes.
- Keep unknown, conflict, nonclinical, not_applicable, unsupported, recorded, and mapped answer outcomes distinct.
- Keep domain history denial in notes rather than inventing individual disease negatives.
- Use accepted clinical facts alone for reasoning, question selection, Education patient payloads, and empathy clinical context; use notes for SOAP and collection coverage only.
- Keep Education replies in actual dialogue and delivery receipts without clinical interpretation, empathy generation, or replanning.

## Questions, Reasoning, and Budgets

- Use prepared Korean SAY and EXAM wording, independently normalize NFC, and require 1-30 codepoints before actual transmission without truncation.
- Preserve observable-target qualification guards and admitted QuestionTemplate answer_type, affirmative, interviewable, and reason contracts.
- Ask the greeting and unresolved chief-bound onset, course, recurrence, and previous care before chief attributes.
- Require one patient-prioritized confirmed chief; ask at most two primary clarifications and fail primary_chief_unresolved instead of choosing an arbitrary report.
- Collect the chief's full admitted attribute list in source order, reserve Open Inquiry, and ask at most six useful ROS targets from the chief's systems without chaining.
- Derive chief progress, ROS targets, and Context coverage from facts, knowledge, and compact answer receipts rather than duplicate counters.
- Prepare only the current session's queue; remove answered questions and discard stale bindings after chief changes or session exit.
- Collect unresolved five-domain history and protect up to two related Context targets independently of optional diagnostic utility.
- Preserve one pure scoring kernel for actual and hypothetical evidence, exact chief occurrence, applicability, refinement replacement, and source weights.
- Aggregate each Disease-Target once; calculate chief support plus capped auxiliary support plus one Context bonus minus bounded source-typicality penalties.
- Require matched positive exact-chief support and positive fit for disease selection; otherwise use the confirmed chief symptom or fail without one.
- Compare eight current and four structurally diverse potential candidates before widening to all chief-compatible candidates.
- Preserve D plus 0.25 E with score gap scale four, 0.5 future discount, six-question paths, and 512 hypothetical evaluations per selection.
- Keep explicit unknown and false prerequisite paths distinct from useful answer regions and incomplete computation distinct from no useful question.
- Require completely evaluated positive utility for optional questions; compute utility before enqueueing without retaining assessments or hypothetical answers.
- Preserve conditional target/cap pairs 5/7, 7/14, 7/9, 3/10, and 5/10 without borrowing session capacity.
- Protect future collection minimums and five enabled Education turns within fifty shared SAY/EXAM turns.
- Count empathy actions separately from interview caps while charging shared turns, tokens, calls, and time; reserve three model calls before empathy.
- Reserve two model calls and 8192 output tokens plus 120-second response and finalization windows before ordinary collection.
- Process received responses before the next budget decision and allow prepared Education delivery without reply-model reservation.
- Share 200 designated-model calls, 500000 input tokens, and 100000 output tokens; count unique semantic requests and consumed server turns once.
- Preserve whole-message caps 12 KiB primary, 16 KiB recovery, 8 KiB compact recovery, and 64 KiB Education; split independent mapping batches without deleting statements.
- Return truncation as ModelResult.error without partial semantic success and allow one bounded larger recovery up to 8000 output tokens.
- Replay a transient once after two seconds with the same ID and payload and bounded timeout; stop unknown after unresolved replay.
- Preserve explicit response-format, refusal, closed, expired, failed, and unknown boundaries without editing the SDK.

## Education and Submission

- Fix one working Diagnosis and retain minimal unresolved assessment before Education; never create a second diagnosis wrapper.
- Resolve disease guideline IDs only at knowledge access and read originals through the hash-pinned organizer guideline mount.
- Read large sources in complete sequential fragments, validate local exact quotations, and retain only final English sentences and minimal document/byte references.
- Preserve guideline, model_knowledge, and mixed provenance, source applicability, conditional treatment, and one plan-format repair.
- Generate with Luna high and render Korean with the designated medium effort within shared budgets.
- Use the current interview queue for Korean delivery, reference final PlanSentence IDs, and withhold whole invalid or unaffordable groups.
- Preserve English P when rendering or delivery fails and retain minimal undelivered receipts.
- Honor explicit ONTOWARD_EDUCATION_ENABLED=false without Education actions, reserved turns, or P.education.
- Generate SOAP only in the submission TurnContext from facts, notes, final diagnosis, and plan; never store SOAP copies in CaseState.
- Preserve fifteen English SOAP string fields and separate diagnosis, semantic categories, same-episode pain details, family context, numeric bounds, and acquisition provenance.
- Keep O.tests empty and O.exam restricted to valid objective acquisition; exclude hypothetical and unperformed findings from A and differential evidence.
- Reconstruct invalid SOAP at most once and finish only after DIAGNOSE returns completed; then clear the submission turn and retain its small receipt.

## Assets and Verification

- Resolve runtime assets within submission and use package-relative imports without host data access or new dependencies.
- Preserve the unchanged SDK, clinical RDF, source weights, question assets, guideline index, and prior admission receipts.
- Pin the runtime algorithm as d44.1 independently from clinical asset admission.
- Keep maintained behavioral fixtures in Dev/tests/workflow, evidence in Tmp, and durable artifact custody in data/provenance.
- Verify information preservation, correction/acquisition, cache parity, observer parity, Korean delivery, Education, and confirmed SOAP submission in project containers.
- Verify the independent archive with no parent project data, no development key, and network disabled; test original SDK HTTP only on the project-internal network.
- Distinguish scripted replay and local runtime/artifact evidence from fresh model quality, clinical validation, real NOVA, official evaluation, commits, and deployment.
