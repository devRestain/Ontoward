# Application Contract

## Ownership

- Apply root PRD.md, D38 chief anchored inference and graph question selection, D18 source custody, and D40 non-borrowing collection and Education budgets.
- Keep run.py limited to SDK callbacks from workflow/runtime.py.
- Assemble immutable knowledge and configuration in PreparedResources and initialize case-owned collaborators and WorkflowState for each consult call.
- Keep Consultation as the sole coordinator for Initiation, ChiefComplaint, ContextFactor, DifferentialDiagnosis, Education, and finalization.
- Apply D37 ONTOWARD_EDUCATION_ENABLED=true by default and retain explicit false as the D26 bypass.
- Fix diagnosis kind Disease identity and name before Education and reuse them during finalization and SOAP repair.
- Keep graph.py limited to assembly, pure routing, and the existing deep-copy/Pydantic boundary.
- Assign prepared SAY validation empathy generation and SAY/EXAM execution to Doctor, facts and empathy signals to InputInterpreter, clinical questions and education to InterviewPlanner, reasoning to ClinicalReasoner, and SOAP/submission to SubmissionWriter.
- Assign question registration/discard to QuestionLifecycle, transcript/projection/delivery to InteractionLifecycle, and counters to UsageAccounting.
- Keep pure decisions in workflow/rules and model/session/identical-request transport in workflow/io.
- Preserve the five case-local state owners without a generic agent base, registry, or session subclasses.
- Keep runtime knowledge inside submission/knowledge and patient facts outside the read-only Graph.
- Leave source projection, asset preparation, and admission to root Dev and data owners.

## Prepared Interviews

- Use prepared interview SAY and EXAM text and permit validated D34 empathy and D37 Education statements as generated patient-facing text.
- Validate text during prepare and independently after NFC normalization immediately before delivery; require 1–30 codepoints including whitespace and punctuation and never truncate.
- Use the manifest-pinned QuestionTemplate answer_type, affirmative, interviewable, and reason fields.
- Block direct questions about diagnosis-qualified Targets without an approved observable mapping.
- Never map an unqualified complaint to a cause-qualified concept or restore a qualifier removed from the question.
- Start with the D40 greeting and collect unresolved onset course recurrence and related previous care before chief attributes.
- Collect five basic history domains and protect up to two unanswered related ContextFactor objects independently of diagnostic utility.
- Select one patient-prioritized primary chief and process its entire get_symptom_attributes list in stable source order.
- Record acquired unknown not_applicable blocked_asset and budget_stopped outcomes separately and reserve the last available collection slot for one Open Inquiry.
- Freeze ROS systems from the primary chief and ask at most six useful presence questions without chaining from additional symptoms.
- Do not use BodySystem to filter Disease recall.
- Require confirmed Target presence in the same observation/episode before asking SAY attributes; retain EXAM as a separate acquisition action.
- Use semantic keys including Target Attribute subject occurrence and exact time context; preserve delivered history and pending actions.
- Use at most two primary clarifications and stop primary_chief_unresolved instead of choosing an arbitrary first report.
- Rebuild chief collection and ROS on explicit primary correction while preserving delivered history; replan on evidence question history session chief or budget changes.
- Apply supporting-Context utility after protected basic history and Context coverage without treating a saturated bonus as complete history.
- Never ordinarily repeat a delivered question; keep clarification case-wide at two and preserve unresolved values.
- Remove unasked placeholders and references together and retain completed facts, delivered explanations, and plans.

## Gateway and Evidence

- Route received replies through InputInterpreter and consume Education replies as transcript-only input before clinical parsing.
- Preserve quoted patient age sex reporter family-member identity and record-only quantities without requiring graph attributes.
- Transmit the compact Gateway schema with one quote per fact and derive internal text and defaults after validation.
- Use openai/gpt-6-luna for gateway terminology and empathy roles; track the first substantive Gateway interpretation separately from other model successes.
- Map each current chief report to one supplied Symptom and separate exact broader ambiguous or unmapped mapping from clinical presence.
- Restrict chief identifiers to Symptoms while extracting incidental attributes values symptoms and Context from the whole utterance under the existing bounded recovery allowance.
- Keep the chief schema enum synchronized with the transmitted candidates, reject multiple chief IDs and unqualified diagnostic composites, and record linked-chief counts separately from nonempty model responses.
- Keep routing selection scores diagnosis and SOAP serialization in Python while accepting validated D37 model-generated P sentences.
- Preserve the complete actual transcript case-locally; exclude failed drafts, undelivered text, and transport errors from dialogue.
- Project current question, relevant observations/episodes, and original context into bounded requests rather than sending the full history.
- Limit primary past context to 24 records, 6 turns, and 16 KiB; limit expanded context to 64 records, 12 turns, and 64 KiB.
- Preserve the complete current input outside the past-context limit and allow only supplied record/dialogue references in model output.
- Require nonempty exact current quotations for every accepted fact; never turn Doctor speech into patient findings.
- Resolve explicit and implicit record destinations before validation and store only the validated field under D36.
- Restrict acquired O corrections to a new EXAM result for the same target and occurrence while retaining patient disputes separately in S.
- Resolve explicit ID-free corrections only against one complete matching evidence key and retain ambiguous conflicts for bounded clarification.
- Separate accepted facts, rejected facts, and unresolved links; quarantine invalid observation dependencies and conflicting corrections without discarding independent valid facts.
- Allow one combined context/link/fact recovery and one final record-only terminology call per reply; freeze accepted independent facts and retain every original rejection and recovery result.
- Include malformed or empty Gateway JSON in that same one-call recovery allowance without admitting ungrounded facts.
- Use fixed parsing only for complete replies matching an explicit prepared answer contract; send compound, temporal, and subject-changing replies to Gateway.
- Bind current answers to the supplied Target Attribute allowed values subject and episode; recover empty substantive answers and incomplete attributes without forcing incompatible meanings.
- Preserve unsupported measurements as quoted subjective medical text without fabricated numeric attributes examination findings or score support.
- Detect exact-quote emotional signals in collection sessions and prioritize budgeted empathy after the required greeting.
- Keep empathy events outside SOAP placeholders and education completion; suppress repeated concerns and acknowledgements while permitting new distress and explicit renewed requests.
- Validate generated empathy as one NFC 1-30 codepoint statement and use the prepared fallback after empty malformed or invalid generation.
- Reserve a reply-model allowance and finalization time before empathy generation and record undelivered events when budgets prevent delivery.
- Bound primary vocabulary to 256 concepts/32 KiB and expansion to 1024 concepts/128 KiB.
- Preserve question Target/Attribute identifiers, prioritize chief lookup terms and current wording before optional Target-specific values, and stop candidate construction at the count limit.
- Apply D28 whole-message UTF-8 JSON caps of 12 KiB primary, 16 KiB expansion, and 8 KiB after a context rejection; include system instructions, schema, current input, question, vocabulary, and past context.
- Prioritize current wording and trim optional vocabulary and past context without truncating current input, question, schema, or required Target/Attribute IDs; preserve oversized input for clarification without transmission.
- Treat CONTEXT_LIMIT_EXCEEDED as a request-specific rejection and use only the existing one-call recovery allowance with a smaller payload and a new request ID; preserve accepted facts and normal clarification/finalization limits.
- Keep unknown, uncertain, explicit absence, unasked, unperformed, and acquired evidence distinct.
- Use the shared current-evidence projection for chief confirmation question resolution reasoning and SOAP while preserving raw conflicts and unstructured reports.
- Preserve raw reports, subject/time, broad and fine locations, corrections, separate observations/episodes, typed quantities/ranges, and both time axes.
- Keep patient speech, actual EXAM findings, initial vitals, proposed tests, and plans in their designated SOAP roles.
- Do not infer units, thresholds, clinical causal qualifiers, examinations, or plans from unqualified wording.

## Pattern Reasoning

- Retrieve shared Patterns from current positive or supported uncertain Targets, evaluate each Pattern per observation/episode, then apply Disease Association conditions and weights.
- Preserve matched, contradicted, and incomplete Pattern states and separate applicability status; let explicit contradiction dominate unknown.
- Activate support only after complete Feature/applicability matching; never merge episodes or count uncertain alternatives as independent confirmation.
- Replace matched ancestors with matching refinements even when support decreases, retain fractional/zero source weights, and aggregate once per Disease–Target.
- Record incomparable matches without fabricating a combined-source weight.
- Preserve nonexclusive categorical positives and distinguish explicit value negation from numeric conflict.
- Restrict chief support to the anchored occurrence and exclude another occurrence of the same Target from auxiliary support.
- Preserve source Association weights and hash-pin the separate d40.1 reasoning policy without changing source graph or action assets.
- Apply bounded absence penalties only to basic presence Patterns with matched applicability, high/very_high source typicality, and explicit current absence in the active chief episode.
- Cap penalties at one per Target and two per Disease; do not penalize unknown, missing relations, detailed mismatch, or another episode's absence.
- Calculate fit as exact-chief support plus min(4, other Target support) plus positive Context capped at one minus bounded contradiction.
- Require positive exact-chief support matched applicability and positive fit; rank eligible diagnoses by fit chief support conflicts and URI.
- Preserve broad candidate recall and use incomplete conditions for question utility rather than confirmed diagnostic support.
- Keep public indexes/refinement caches in PreparedResources and patient search/matching caches only in case state.
- Preserve full diagnostic recall and compare eight current plus four structurally diverse potential candidates before expanding to all chief-compatible candidates.
- Compare typed answer regions with D plus 0.25 E using gap scale four and action cost one; exclude unknown replies from information-branch weighting.
- Discount feasible future paths by 0.5 per step up to six questions and enforce 512 hypothetical evaluations per selection.
- Record incomplete computation separately from no useful information and retain selected paths outcomes runner-ups and actual post-answer results.
- Evaluate actual and isolated hypothetical evidence through the same pure kernel and dependency indexes; score Context from acquisition independently of session.
- Select a separately typed confirmed chief-symptom diagnosis if no eligible Disease remains and fail explicitly without supported chief evidence.

## Budgets, Recovery, and Submission

- Apply D40 conditional target/cap pairs of Initiation 5/7 ChiefComplaint 7/14 ContextFactor 7/9 DifferentialDiagnosis 3/10 and Education 5/10 without borrowing capacity.
- Treat interview targets as conditional coverage goals and skip filler while reserving five shared turns before enabled Education.
- Protect future conditional collection minimums and current mandatory work before optional questions or empathy within fifty shared turns.
- Deliver Education within its ten-action cap and preserve whole PlanSentence delivery groups without mandatory understanding questions.
- Require fully evaluated positive structural decision utility for optional questions and budgeted binding clarifications; exclude resolved unknown unavailable or false-prerequisite paths.
- Preserve compulsory primary selection full chief collection and Open Inquiry while comparing optional presence attributes Context and EXAM with the shared kernel.
- Keep Usage.actions as total consumed server turns and empathy_actions as its empathy subset; count actions minus empathy_actions against interview caps.
- Charge empathy SAY and model calls to the common 50-turn and model/token budgets without an independent empathy quota; preserve queued empathy across replanning and interpret its reply before continuation.
- Preserve empathy dialogue and accepted clinical facts without inserting an unlinked acknowledgement into SOAP.
- Reserve one Gateway call and 4096 output tokens before collection actions while retaining response and finalization windows of 120 seconds each.
- Allow prepared Education delivery without a reply-model reservation and retain response and finalization time windows.
- Classify finish_reason length as truncation and use the existing single recovery with at most 8000 tokens without counting truncated responses as success.
- Process every received reply immediately after execution and let interpretation consume its reserved window; do not route budget checks back to pending recovery.
- Share 200 model calls, 500000 input tokens, and 100000 output tokens case-wide; count unique requests and successful actions once.
- Keep one graph budget evaluation and a lightweight capacity/model/time gate before transmission; distinguish graph steps from SDK turns and enforce server constraints.
- Replay transient errors once after two seconds with the exact payload/request ID and timeout bounded by 240 seconds and the remaining phase reserve; stop unknown if unresolved.
- Preserve patient/exam response-format errors as unresolved without a new-ID automatic retry; never edit the pinned SDK.
- Preserve Education replies only in the transcript without clinical extraction terminology clarification empathy or replanning.
- Treat the fixed selection as a working diagnosis and preserve unresolved assessment and treatment prerequisites in A and P.
- Keep English P sentences separate from Korean delivery queues and retain exact undelivered reasons.
- Read every mapped original document through the pinned index and organizer mount and retain document relation scope and source hashes.
- Include complete actual dialogue and obtained records in every Education generation request within a whole-messages 64-KiB cap.
- Read oversized documents in complete sequential fragments and combine verified quote-backed notes before synthesis.
- Require five nonempty English P sentence arrays on success and distinguish guideline model_knowledge and mixed provenance.
- Allow one case-wide plan-format repair and one Doctor repair for each invalid batch while preserving accepted items.
- Use education high with up to 8000 output tokens and education_doctor medium with up to 4000 inside shared budgets.
- Reject missing changed and escaping sources and retain retrieval errors without treating model knowledge as source evidence.
- Serialize exactly fifteen SOAP string fields plus separate diagnosis, keep O.tests empty, and retain acquisition provenance and meaningful clinical context.
- Keep A.evidence limited to actual obtained findings used in diagnosis and exclude unasked/unperformed findings and internal identifiers.
- Apply D33 English source labels and fixed Category: Content lines to populated SOAP fields; keep the representative complaint in S.cc and onset and pain assessment in S.hpi tied to the same observation and episode.
- Render history and ROS presence as (+) or (-), keep unknown and uncertain explicit, and never expand a general history denial into individual disease negatives.
- Keep additional record keywords anchored to exact patient quotes in the existing Gateway pass; prefer admitted typed values and require explicit NRS scale evidence.
- Render only unresolved clinical spans in their semantic S fields and keep greetings acknowledgements and future promises in the transcript.
- Render Diagnosis and Evidence categories plus source-supported r/o entries; keep all fifteen SDK fields and the separate English diagnosis unchanged in shape.
- Preserve acquired negative findings used by diagnosis penalties and include obtained supporting findings beside each differential diagnosis.
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
- Run maintained workflow D40 intake SOAP algorithm input empathy evidence Education and admitted-RDF checks through root Dev/tests/workflow.
- Compare frozen pre-D38 and D38 synthetic consultations with identical source fixtures and budgets without public-case tuning.
- Keep synthetic fixtures and evidence in Tmp and verify the extracted ZIP without parent data/assets or network.
- Package only active manifest knowledge assets and required runtime defaults; exclude superseded unreferenced knowledge files without deleting their source custody.
- Reconcile D18 in requirements, contracts, decisions, and all three maintained operational states before completion.
- Distinguish offline runtime/artifact checks from independent clinical validation, real Luna, authenticated SDK, official submission/evaluation, and deployment.
