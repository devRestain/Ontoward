# Application Contract

## Ownership

- Apply root PRD.md, D18 source-only knowledge ownership, and D17 interview, matching, parsing, and budget policy.
- Keep run.py limited to SDK callbacks from workflow/runtime.py.
- Assemble immutable knowledge and configuration in PreparedResources and initialize case-owned collaborators and WorkflowState for each consult call.
- Keep Consultation as the sole coordinator for Initiation, ChiefComplaint, ContextFactor, DifferentialDiagnosis, Education, and finalization.
- Keep graph.py limited to assembly, pure routing, and the existing deep-copy/Pydantic boundary.
- Assign prepared SAY validation and SAY/EXAM execution to Doctor, response interpretation and facts to InputInterpreter, questions and education to InterviewPlanner, Pattern evaluation and diagnosis to ClinicalReasoner, and SOAP/submission to SubmissionWriter.
- Assign question registration/discard to QuestionLifecycle, transcript/projection/delivery to InteractionLifecycle, and counters to UsageAccounting.
- Keep pure decisions in workflow/rules and model/session/identical-request transport in workflow/io.
- Preserve the five case-local state owners without a generic agent base, registry, or session subclasses.
- Keep runtime knowledge inside submission/knowledge and patient facts outside the read-only Graph.
- Leave source projection, asset preparation, and admission to root Dev and data owners.

## Prepared Interviews

- Use prepared text for every SAY and EXAM; do not generate or rephrase patient utterances with a model.
- Validate text during prepare and independently after NFC normalization immediately before delivery; require 1–30 codepoints including whitespace and punctuation and never truncate.
- Use the manifest-pinned QuestionTemplate answer_type, affirmative, interviewable, and reason fields.
- Block direct questions about diagnosis-qualified Targets without an approved observable mapping.
- Never map an unqualified complaint to a cause-qualified concept or restore a qualifier removed from the question.
- Start with the prepared greeting and chief-complaint invitation.
- Process applicable unresolved core HPI in slot-first round-robin order: Location, Laterality, PainQuality or Quality, TimeSinceOnset, EpisodeDuration, Severity.
- Ask one Open Inquiry after core HPI, then evaluate remaining questions adaptively.
- Freeze the ROS candidate system union from confirmed chief complaints; select by current utility, skip known symptoms, and ask at most six without chaining new systems.
- Do not use BodySystem to filter Disease recall.
- Require confirmed Target presence in the same observation/episode before asking SAY attributes; retain EXAM as a separate acquisition action.
- Use stable semantic question keys and preserve delivered history and pending actions.
- Replan undelivered questions after new clinical evidence; permit reconsideration of low-priority undelivered questions only after a new evidence revision.
- Never ordinarily repeat a delivered question; keep clarification case-wide at two and preserve unresolved values.
- Remove unasked placeholders and references together and retain completed facts, delivered explanations, and plans.

## Gateway and Evidence

- Route every SAY/EXAM reply through InputInterpreter, including education replies.
- Use openai/gpt-6-luna only for Gateway interpretation and parse the first substantive patient statement with that model.
- Keep routing, selection, scores, final diagnosis, and SOAP in Python.
- Preserve the complete actual transcript case-locally; exclude failed drafts, undelivered text, and transport errors from dialogue.
- Project current question, relevant observations/episodes, and original context into bounded requests rather than sending the full history.
- Limit primary past context to 24 records, 6 turns, and 16 KiB; limit expanded context to 64 records, 12 turns, and 64 KiB.
- Preserve the complete current input outside the past-context limit and allow only supplied record/dialogue references in model output.
- Require nonempty exact current quotations for every accepted fact; never turn Doctor speech into patient findings.
- Separate accepted facts, rejected facts, and unresolved links; quarantine invalid observation dependencies and conflicting corrections without discarding independent valid facts.
- Allow one combined context/link/fact recovery call per reply and retain first-pass valid facts if recovery fails.
- Use fixed parsing only for complete replies matching an explicit prepared answer contract; send compound, temporal, and subject-changing replies to Gateway.
- Bound primary vocabulary to 256 concepts/32 KiB and expansion to 1024 concepts/128 KiB.
- Require only question Target/Attribute identifiers, prefer Target-specific values and current wording, and stop candidate construction at the count limit.
- Keep unknown, uncertain, explicit absence, unasked, unperformed, and acquired evidence distinct.
- Preserve raw reports, subject/time, broad and fine locations, corrections, separate observations/episodes, typed quantities/ranges, and both time axes.
- Keep patient speech, actual EXAM findings, initial vitals, proposed tests, and plans in their designated SOAP roles.
- Do not infer units, thresholds, clinical causal qualifiers, examinations, or plans from unqualified wording.

## Pattern Reasoning

- Retrieve shared Patterns from current positive or supported uncertain Targets, evaluate each Pattern per observation/episode, then apply Disease Association conditions and weights.
- Preserve matched, contradicted, and incomplete Pattern states and separate applicability status; let explicit contradiction dominate unknown.
- Activate support only after complete Feature/applicability matching; never merge episodes or count uncertain alternatives as independent confirmation.
- Replace matched ancestors with matching refinements even when support decreases, retain fractional/zero source weights, and aggregate once per Disease–Target.
- Record incomparable matches without fabricating a combined-source weight.
- Preserve the original scoring_policy and hash-pin the separate D17 reasoning_policy.
- Apply bounded absence penalties only to basic presence Patterns with matched applicability, high/very_high source typicality, and explicit current absence in the active chief episode.
- Cap penalties at one per Target and two per Disease; do not penalize unknown, missing relations, detailed mismatch, or another episode's absence.
- Calculate fit as source support plus capped positive-only Context minus bounded contradiction.
- Rank by fit, current-chief coverage, explicit conflicts, and Disease URI; require positive support, positive fit, and complete current-chief explanation for primary and alternative diagnosis eligibility.
- Preserve broad candidate recall and use incomplete conditions for question utility rather than confirmed diagnostic support.
- Keep public indexes/refinement caches in PreparedResources and patient search/matching caches only in case state.
- Invalidate changed observation/episode evaluations and recompute Context when its scoring mode changes; skip repeated scoring without changed clinical evidence.
- Select a separately typed confirmed chief-symptom diagnosis if no eligible Disease remains and fail explicitly without supported chief evidence.

## Budgets, Recovery, and Submission

- Use a common 50-turn action pool rather than per-session caps and preserve two education/understanding turns plus one correction opportunity.
- Reserve one Gateway call/output allowance, 120 seconds for reply processing, and 120 seconds for finalization before new actions.
- Process received pending replies before finalization and let response processing consume its reserved window.
- Share 200 model calls, 500000 input tokens, and 100000 output tokens case-wide; count unique requests and successful actions once.
- Recheck before transmission, distinguish graph steps from SDK turns, and enforce server constraints.
- Preserve exact payload/request identity for transient retries after two/five seconds, at most twice, with timeout bounded by 240 seconds and the remaining phase reserve.
- Retry explicit patient/exam response-format errors once with a new request ID; never edit the pinned SDK.
- Preserve delivered education if later parsing fails and prioritize correction_required after a changed diagnosis.
- Record unmet correction when actions/time run out and never claim an undelivered explanation.
- Use only admitted plans and prepared common provisional wording; keep missing disease plans visible and apply D18's deletion of prior education drafts.
- Serialize exactly fifteen SOAP string fields plus separate diagnosis, keep O.tests empty, and retain acquisition provenance and meaningful clinical context.
- Keep A.evidence limited to actual obtained findings used in diagnosis and exclude unasked/unperformed findings and internal identifiers.
- Reconstruct an invalid SOAP record once and finish only after the submitted DIAGNOSE returns completed.
- Distinguish failed, unknown, closed, expired, and confirmed submitted outcomes.

## Configuration and Acceptance

- Read public .env settings with runtime environment precedence and keep runner credentials separate.
- Resolve manifest assets within knowledge and Gateway/text configuration within config; reject external/parent/symlink escapes and missing assets.
- Require manifest-pinned schema, vocabulary, clinical bundles, source policy, reasoning policy, and optional labels/questions/plans.
- Reject the D18-withdrawn runtime manifest until a new pinned source-only batch and its wording are admitted.
- Recognize D20 graph_admitted_text_pending as approved graph data and reject consultation until its pinned action text is complete.
- Consume D23 admitted D22 patient actions through strict prepare; preserve D20 graph and policy semantics and use only exact prepared SAY and EXAM wording.
- Keep require_action_assets=False confined to offline graph preparation and validation; use full graph and question validation during prepare.
- Use package-relative runtime imports and settings.py for file-relative paths.
- Run maintained offline behavioral tests and actual-admitted-RDF scripted consultations through root Dev/tests/workflow.
- Keep synthetic fixtures and evidence in Tmp and verify the extracted ZIP without parent data/assets or network.
- Package only active manifest knowledge assets and required runtime defaults; exclude superseded unreferenced knowledge files without deleting their source custody.
- Reconcile D18 in requirements, contracts, decisions, and all three maintained operational states before completion.
- Distinguish offline runtime/artifact checks from independent clinical validation, real Luna, authenticated SDK, official submission/evaluation, and deployment.
