# Application Contract

## Ownership

- Own submission runtime code, Pydantic state, LangGraph flow, model calls, and patient interfaces under workflow/.
- Keep run.py limited to the SDK callbacks from workflow/runtime.py.
- Assemble case-independent knowledge and text configuration in PreparedResources and create execution objects and state per consult call.
- Keep Consultation as the sole coordinator for internal session preparation transitions refresh and finalization.
- Keep graph.py limited to graph assembly state-based routing and the deep-copy validation wrapper.
- Assign SAY framing and SAY/EXAM execution to Doctor, input interpretation and clinical fact application to InputInterpreter, question and education selection to InterviewPlanner, clinical algorithms to ClinicalReasoner, and SOAP and submission attempts to SubmissionWriter.
- Assign question registration discard and unresolved closure to QuestionLifecycle, action references dialogue and delivery to InteractionLifecycle, and all usage accounting to UsageAccounting.
- Keep immutable limits and pure budget input action and submission decisions in workflow/rules without a generic rule engine.
- Keep NOVA session access model requests and identical-request recovery in workflow/io with injected clock sleep and request identity dependencies.
- Preserve the five serialized WorkflowState objects in workflow/state/models.py and keep mutable case state out of execution-object attributes.
- Use session for internal stages and nova_session for the official server session; preserve existing scope fields and serialized values.
- Use package-relative imports within workflow/ and settings.py for submission-local data paths.
- Keep RDFLib graph ownership and fixed readers in knowledge/ and preserve preparation and admission ownership in root data/.

## Application Behavior

- Use `../PRD.md` as the intended application behavior contract.
- Validate external inputs and outputs at explicit Pydantic boundaries.
- Keep CaseState in memory for one case and initialize a separate state for every new case.
- Freeze applicable HPI slots for each initial chief complaint and process them without diagnostic ranking or score-based early termination.
- Execute retained HPI, one open inquiry, then at most six focused ROS questions from confirmed chief-complaint systems before normal disease retrieval.
- Freeze focused ROS in sorted URI order using existing inSystem and BodySystem links; deduplicate and skip known symptoms without expanding into newly reported systems.
- Return every SAY and EXAM response through one InputInterpreter, including education responses.
- Use unasked and done for record processing; preserve present, absent, uncertain, and unknown within values.
- Initialize each scope once and finish only after pending replies are handled and the current scope has no unasked records.
- Delete low-priority unasked records and question references together; do not retain deferred queues or recreate deleted questions.
- Preserve acquired facts, pending actions, prepared plans, and delivered explanations.
- Recompute the complete candidate union and ranking from deduplicated current evidence after initial retrieval.
- Allow at most two clarification questions across the case for parsing failure unclear chief complaints or missing candidates; never drop clarification merely because its failed source item is done.
- Select a separately typed symptom diagnosis from a confirmed current chief complaint when bounded clarification leaves no disease candidates; fail explicitly when neither diagnosis has support.
- Apply capped positive-only context support without creating candidates or penalizing absent context.
- Require a supported disease or symptom diagnosis, an actual designated-model response, and a valid record before submission.
- Use Initiation, ChiefComplaint, ContextFactor, DifferentialDiagnosis, and Education in order without ClinicalSynthesis.
- Keep routing, question and education selection, scoring, final diagnosis, and SOAP serialization in Python.
- Use openai/gpt-6-luna separately for Doctor SAY framing and Gateway parsing with distinct prompts and role-tagged model records.
- Pass actual spoken wording, the structured InterviewPlanner question, all delivered Korean dialogue, existing observations, and allowed vocabulary to Gateway.
- Keep delivered dialogue case-local in InteractionState and exclude drafts errors and unsent phrases from its dialogue projection.
- Ground every fact in an exact current quote and validate context references; never turn Doctor speech into a patient observation.
- Restrict Python yes/no mapping to explicitly affirmative prepared presence questions; use Gateway for Doctor-rephrased questions.
- Validate actual output independently after NFC normalization including spaces punctuation and line breaks; regenerate SAY at most twice before validating its prepared fallback and never truncate.
- Treat calculated zero Context bonuses as valid; do not advance with missing calculations.
- Retain Open Inquiry then focused ROS ahead of HPI when pruning but execute HPI then Open Inquiry then ROS within twenty ChiefComplaint actions.
- Continue differential questions despite a sole leading candidate; recalculate after the last answer.
- Replace only incompatible undelivered education after new facts change the selected diagnosis; do not return to earlier scopes.
- Check the budget again before action execution and distinguish graph-step limits from SDK turns.
- Share the global model and token budget across both roles and regenerations; reserve a reply call and output allowance before Doctor framing.
- Preserve scoped action caps 1/20/10/14/5 and a 120-second finalization reserve.
- Recover transient requests at most twice with identical IDs and payloads after two and five seconds; bound timeout by 240 seconds and remaining time without modifying the pinned SDK.
- Retry explicit patient or examiner response-format errors once with a new ID; count successful actions and unique model requests once.
- Assign prepared education selection to InterviewPlanner and final record validation and submission to SubmissionWriter.
- Reconstruct an invalid SOAP record once; enter finish only after the submitted DIAGNOSE request returns completed and use abort for explicit unsuccessful outcomes.
- Separate confirmed submission, failure, unknown outcome, closed session, and expiry.
- Implement the authorized offline MVP and leave actual clinical admission and authenticated SDK acceptance explicitly unverified.
- Keep unasked and unanswered items distinct from uncertain, present, and explicitly absent observations.
- Keep separate occurrences of the same symptom distinct and preserve confirmed broad and specific locations as parallel values within one occurrence.
- Link common site- or activity-qualified complaints to specific symptom concepts and retain finer qualifiers without location containment or global absence.
- Preserve raw reports, evidence-supported symptom interpretations, corrections, and uncertainty within the same observation and episode.
- Leave unspecified pain unresolved until location or activity supports a specific symptom.
- Update interpretations from acquired evidence without relabeling symptoms to fit a diagnosis.
- Preserve the source response, acquisition turn or initial-source marker, and clinical context alongside each normalized finding.
- Represent SAY, EXAM, finals-only TEST, and DIAGNOSE as distinct SDK actions.
- Select one question or examination maneuver per preliminary interaction.
- Apply the PRD session, input-length, retry, and SOAP submission contracts at explicit boundaries.
- Keep the main diagnosis in CaseState.diagnosis and send it as the separate SDK diagnosis argument.
- Validate exactly the SDK 1.0.1 fifteen SOAP fields and exclude note.A.diagnosis.
- Preserve the unchanged SDK copy and verify its source hash before packaging.
- Read public application settings from .env with runtime environment precedence and leave runner credentials to the SDK.
- Keep Doctor instructions in config/doctor.txt, Gateway instructions in config/input_parser.txt, and editable questions replies and SOAP wording in config/texts.ko.json.
- Resolve ONTOWARD_DOCTOR_PROMPT, ONTOWARD_PARSER_PROMPT, and ONTOWARD_TEXTS inside config; validate during prepare and apply edits by rerunning prepare.
- Read disease-specific questions and plans only from manifest-declared assets; never invent missing clinical text.
- Keep the case transcript locally without depending on official session events.
- Distinguish pre-transmission validation from server-side invalid SAY or EXAM requests that consume one turn.
- Write A.evidence as a concise list of obtained interview and physical-examination findings used to judge the main diagnosis.
- Name the supporting findings directly instead of stating their source or saying that the diagnosis is based on patient expressions.
- Keep acquisition turns and raw provenance in InteractionState with references from CaseState; exclude unasked or unperformed findings from A.evidence.
- Separate education plans from explanations actually delivered through SAY.
- Keep patient-reported answers separate from examination and investigation findings.

## Knowledge Code

- Leave pre-submission extraction, candidate validation, RDF generation, and bundle assembly to root Dev/ under D09.
- Consume data-owned submission-admitted bundles without depending on Dev tools or extraction CLI authentication.
- Exclude the data-owned natural-language vocabulary candidates from runtime knowledge until clinician review and separate admission.
- Treat NOVA_GUIDELINES_DIR as a preparation source-location contract rather than a consultation retrieval dependency.
- Load the D08 schema and vocabulary with all manifest-declared clinical bundles into one RDFLib Graph during case-independent prepare().
- Query the prepared Graph without RF2 or source-document retrieval, extraction, or patient writes during consultation.
- Keep the Graph outside CaseState and preserve patient observations only in case-owned state.
- Use fixed readers for concept candidates, symptom attributes, disease candidates, patterns, supporting contexts, exam methods, and SOAP test plans.
- Follow ../data/ontology/AGENTS.md for single-target pattern ownership, optional feature status and role, categorical pairing, and partial matching.
- Retrieve candidates from observed symptoms and ExamFinding through reverse targets and hasPattern traversal without requiring presentsAs.
- Union independent alternative-pattern retrieval paths without a BodySystem filter or mandatory co-occurrence.
- Use supported uncertain concept candidates for recall without treating them as multiple confirmed findings or duplicate support.
- Keep manually reviewed pattern importance independent from feature clinicalRole and leave selectivity optional for later post-build work.
- Use predefined queries when needed without accepting LLM-generated SPARQL.
- Preserve common concept URIs while leaving relation-level source paths, sections, applicability, and review records in data-owned preparation records outside the runtime graph.
- Preserve unmapped source text and concept-link uncertainty without creating an unsupported clinical relation.
- Keep review-only scripts, examination tables, and reference answers outside clinical knowledge and patient inputs.
- Reserve evaluatedBy and Test for a separate P.tests reader without using them for diagnostic candidate generation, matching, ranking, or action selection.
- Keep preliminary TEST execution blocked and O.tests empty.
- Keep treatment, disposition, follow-up, education, and warning-sign planning in the application without introducing SOAP or workflow nodes into this ontology.
- Map ExamFinding through detectedBy to ExamMethod.examRequestText and call client.exam(text) after prepared single-maneuver and NFC-length validation.
- Treat method URIs as internal identifiers and request texts as suggested payloads without asserting server recognition.
- Record actual examination results or refusals instead of expected findings.
- Exclude selective loading, Dataset, Named Graphs, and OWL inference from the first MVP.
- Treat missing knowledge associations as unavailable evidence rather than absent findings.
- Treat retrieved associations and source likelihood labels as supporting evidence rather than calibrated disease probabilities.

## Local State

- Record application implementation progress and evidence only in PROJECT_STATE.md.
- Exclude AGENTS.md, README.md, PROJECT_STATE.md, and caches from submission archives while including the public .env.
- Run the package Compose service to archive only this directory's runtime files and knowledge assets.
- Keep Turtle, required JSON schemas, and the runtime manifest in knowledge/ without parent-project fallbacks in execution or tests.
- Run Dev/tests/workflow/test_workflow.py in the project dev container with Dev/tests/workflow/compose.offline.yaml.
- Keep generated full-flow assets inside a temporary submission copy under Tmp and exclude fixtures from the real archive.
- Use Dev/architecture/WORKFLOW_RULES.md to locate each rule owner and behavioral test without duplicating executable rules.
- Reference D01, D03, D04, D05, D06, D07, D08, D09, D11, D12, D13, and D14 in `../DECISION_STATE.md` without duplicating options or decision statuses.
- Leave source admission and preparation-result records to `../data/PROJECT_STATE.md`.
