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
- Consume D42 source and author extensions only through pinned v5.0 assets; retain D41 dictionary binding raw-free consumers and original source weight meanings.

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

- Apply D41 context analysis followed by database-only normalization for every initial input and collection SAY or EXAM reply.
- Execute D43 process_initial_input before the first SAY and preserve the opening chief and independent clinical details at turn zero.
- Keep compact observed-number schemas separate from graph-condition schemas and preserve valid context rows while repairing only invalid indices once.
- Allow one additional focused review of an explicitly prioritized unresolved initial observation without promoting genuine unknown existence to positive.
- Distinguish target assertions from attribute assertions; use feature hints for retrieval without turning them into mandatory target attributes.
- Bind common intake to the known chief and retain standalone registered numeric reports as record-only without inventing symptom presence or converting changes to absolute measurements.
- Keep Education replies transcript-only without interpretation, empathy, clinical updates, or replanning.
- Use openai/gpt-6-luna through the pinned SDK and keep routing, diagnosis scores, question selection, and SOAP serialization in Python.
- Preserve the complete actual transcript and raw model exchanges in case-local audit storage only.
- Restrict patient-original context to InputInterpreter model requests and exclude failed drafts and undelivered speech from dialogue.
- Extract atomic statements with exact current spans and typed subject, reporter, time, episode, assertion, correction, and emotional intent.
- Use only supplied existing observation, episode, and correction references and keep family relationship tokens closed.
- Separate unknown, uncertain, nonclinical, domain denials, conditional negation, inapplicability, and acquired facts.
- Search each statement independently using source labels, aliases, and context-generated retrieval hints without hypothesis filtering.
- Bind normalization batches to admitted Target, Attribute, AttributeValue, polarity, and registered numeric formats.
- Reject unknown identifiers, invalid relationships, duplicate JSON keys, nonfinite numbers, unsupported units, and invented measurements.
- Allow one context repair, three normalization stages, and one additional format repair per mapping batch inside shared case budgets.
- Freeze independent valid mappings and repair only unresolved statements while preserving original rejection evidence.
- Force the closest compatible admitted mapping at the final semantic stage and complete remaining valid-context mappings deterministically when necessary.
- Preserve polarity, subject, scope, and acquisition during forced completion and record forced_by without excluding otherwise eligible evidence.
- Keep unsupported details in typed outcomes and audit storage without adding record codes, clinical graph relations, or free SOAP summaries.
- Separate fact identifiers from question identifiers and connect every acquired question answer through answered_fact_ids.
- Preserve nonexclusive values and separate subjects, observations, conditions, and time points; replace facts only through validated corrections.
- Restrict acquired O corrections to a new EXAM result for the same target and occurrence.
- Use CanonicalSnapshot for downstream patient data and EvidenceIndex for its graph-eligible reasoning subset.
- Keep raw quotations, free English record details, and unregistered quantities outside canonical patient payloads.
- Derive question acquisition and retry behavior from typed outcomes and facts rather than patient wording.
- Detect empathy through the context pass and provide only emotional codes and canonical facts to empathy generation.
- Validate empathy independently as one NFC 1-30 Korean statement and preserve the prepared fallback.
- Preserve D28 whole-message caps of 12 KiB primary, 16 KiB recovery, and 8 KiB after context rejection.
- Split normalization batches rather than deleting independent statements and retain required current input and bound identifiers.
- Preserve oversized input in audit without transmitting an oversized request or manufacturing a clinical fact.

## Pattern Reasoning

- Retrieve shared Patterns from current positive or supported uncertain Targets, evaluate each Pattern per observation/episode, then apply Disease Association conditions and weights.
- Preserve matched, contradicted, and incomplete Pattern states and separate applicability status; let explicit contradiction dominate unknown.
- Activate support only after complete Feature/applicability matching; never merge episodes or count uncertain alternatives as independent confirmation.
- Replace matched ancestors with matching refinements even when support decreases, retain fractional/zero source weights, and aggregate once per Disease–Target.
- Record incomparable matches without fabricating a combined-source weight.
- Preserve nonexclusive categorical positives and distinguish explicit value negation from numeric conflict.
- Restrict chief support to the anchored occurrence and exclude another occurrence of the same Target from auxiliary support.
- Preserve source Association weights and hash-pin the separate d41.1 reasoning policy without changing source graph or action assets.
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
- Reserve two Gateway calls and 8192 output tokens before collection actions while retaining response and finalization windows of 120 seconds each.
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
- Include only canonical patient facts and typed outcomes in every Education generation request within a whole-messages 64-KiB cap.
- Read oversized documents in complete sequential fragments and combine verified quote-backed notes before synthesis.
- Require five nonempty English P sentence arrays on success and distinguish guideline model_knowledge and mixed provenance.
- Allow one case-wide plan-format repair and one Doctor repair for each invalid batch while preserving accepted items.
- Use education high with up to 8000 output tokens and education_doctor medium with up to 4000 inside shared budgets.
- Reject missing changed and escaping sources and retain retrieval errors without treating model knowledge as source evidence.
- Serialize exactly fifteen SOAP string fields plus separate diagnosis, keep O.tests empty, and retain acquisition provenance and meaningful clinical context.
- Keep A.evidence limited to actual obtained findings used in diagnosis and exclude unasked/unperformed findings and internal identifiers.
- Apply D33 English source labels and fixed Category: Content lines to populated SOAP fields; keep the representative complaint in S.cc and onset and pain assessment in S.hpi tied to the same observation and episode.
- Render history and ROS presence as (+) or (-), keep unknown and uncertain explicit, and never expand a general history denial into individual disease negatives.
- Render patient facts from admitted labels, values, and numeric formats; require explicit NRS scale evidence.
- Preserve numeric approximation and mark qualified assertions in SOAP without inserting the patient's original condition text.
- Keep unmapped spans, greetings, acknowledgements, and future promises in audit storage without adding them to SOAP.
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
- Run maintained D41 normalization intake SOAP algorithm empathy evidence Education and admitted-RDF checks through root Dev/tests/workflow.
- Compare frozen pre-D38 and D38 synthetic consultations with identical source fixtures and budgets without public-case tuning.
- Keep synthetic fixtures and evidence in Tmp and verify the extracted ZIP without parent data/assets or network.
- Package only active manifest knowledge assets and required runtime defaults; exclude superseded unreferenced knowledge files without deleting their source custody.
- Reconcile D18 in requirements, contracts, decisions, and all three maintained operational states before completion.
- Distinguish offline runtime/artifact checks from independent clinical validation, real Luna, authenticated SDK, official submission/evaluation, and deployment.
