# Preparation Tools Contract

## Ownership

- Own pre-submission source projection, normalization, RDF generation, preview validation, and bundle preparation.
- Keep runtime code and graph readers in root submission/ and durable provenance and preparation results in root data/.
- Keep disposable fixtures and reports in root Tmp/ and operational progress in root PROJECT_STATE.md.
- Own tests/workflow, tests/ontology, architecture/WORKFLOW_RULES.md, and packaging/package_submission.py.
- Package only submission runtime files and public settings; keep preparation code, tests, guidance, state, source originals, and credentials outside the ZIP.
- Read archive inputs only from /submission and write output only to /output.

## v5.0 Source Projection

- Read root AGENTS.md, PROJECT_STATE.md, PRD.md, DECISION_STATE.md D02/D05/D07/D08/D09, the data contracts, and applicable asset contracts before handling sources.
- Use ontology/source_projection.py as the build/export/admit entrypoint, database.py for SQLite source custody, model_normalization.py for bounded source normalization, admission.py for reviewed integration, and v5.py for RDF construction.
- Treat the removed v4.2 SNOMED and guideline extraction pipelines as deprecated; do not restore or adapt them for compatibility.
- Apply D18 source-only reset.py and preserve original assets, deletion receipts, and the clean empty v5 base; remove old seeds, derived batches, and obsolete approvals.
- Ingest every supplied International and Korean RF2 Snapshot TXT plus release metadata and all eight BODHI-S CSVs; preserve source licenses and upstream descriptions without downloads or mutation.
- Pin release metadata, module dependency versions, source file hashes, normalization version, registry version, and the public scoring policy.
- Select the latest RF2 component row before applying active status; reject same-version conflicts, future rows, and unsatisfied module dependencies.
- Preserve SCTIDs as strings, BODHI UUIDs and raw identifier fields, RF2 relationship groups and paths, source rows and positions, and mapping judgments.
- Apply D18's full-source and all-schema request; derive identifiers from source identities without starter-vocabulary lookup.
- Verify Disease identity against the active SNOMED disorder hierarchy and BODHI source classification. Record history, family history, invalid IDs, and non-disease entities as excluded or unresolved.
- Keep a source variant's required conditions together; never union features from different variants solely because Disease and Target agree.
- Normalize the typed D08 value contract without inventing units, thresholds, conjunctions, or linked findings.
- Defer other required findings and ambiguous relationship-group scope as whole dependent variants with explicit reasons.
- Preserve quantities and intervals with operators and units; distinguish elapsed time from episode duration and calendar units from fixed time.
- Reuse a Pattern only when its Target, conditions, operators, units, negation, timing, and combination scope agree.
- Retain all source assertions for each Disease–Pattern–applicability association and select BODHI directional labels before equivalent SNOMED fallback.
- Generate conditional atomic or joint FeatureContribution deltas; never distribute a joint delta across individual features.
- Keep registry entries as candidates and preview_only outputs in data/preparation/v5/ until separate human review and runtime admission.
- Keep source builds offline by default and execute current Korean work through D22's project-container NOVA route with pinned finite budgets, sequential calls, persistent reservations, and authorized fresh attempts after failure.
- Keep model judgments candidate-only; never infer relationships, identifiers, likelihoods, missing units, or linked findings from model knowledge and never resume older jobs.
- Resume only an explicitly selected current build with identical source, schema, and normalization pins; preserve unknown or differently pinned artifacts and regenerate only a recognized same-build preview from its canonical database.
- Require a pinned approval receipt covering association and mapping dependencies before admit writes clinical assets.
- Use D23 as the user acceptance of complete source-backed competition candidates and reviewed patient actions; preserve technical exclusions rather than requesting another clinical decision.
- Use source_catalog.py for competition-linked source roles across every v5 class; report unsupported classes explicitly without broad taxonomy inflation.
- Keep full raw source custody and original edge roles in preparation; select the competition dependency vocabulary and export only complete executable expressions as clinical RDF.
- Preserve korean.py's historical complete label/question worksets and use patient_text.py for D22 patient-only actions with its base budget and explicitly authorized same-day continuation ceiling.
- Preserve Korean RF2 terms and historical model_translation provenance; bind current clinical questions to observable Targets and Attributes and compare every generated text in a separate D22 NOVA request.
- Stop D18-D21 runs on failure, uncertainty, semantic rejection, or invalid NFC/length. Apply D22's explicitly authorized NOVA-only fresh attempts within its pinned same-day ceiling; preserve every request identity and never reuse a failed request ID or continue after quota exhaustion.
- Keep unsupported detectedBy/evaluatedBy/inSystem/context mappings unresolved rather than inferring new source assertions.
- Apply D20 connections.py for reviewed source-derived inSystem, contextType, hasSupportingContext, and prerequisite applicability; preserve each derivation's source rows and policy.
- Keep BODHI Context identities distinct from SCTID mappings and preserve one scored acquisition role per source finding identifier.
- Use D20 graph-only admission without Korean generation; preserve strict consultation text requirements and reuse the shared source-custody database read-only.
- Apply D19 findings.py discovery independently of BODHI symptom roots; distinguish direct physical methods, unresolved acquisition, grouped interpretation values, and Observable model metadata.
- Keep source-findings.ttl candidate-only; do not insert missing methods, request wording, units, thresholds, or duplicate acquisition-channel scores into executable clinical RDF.
- Report every BODHI specialty and supplied ClinicalObservable domain with evidence coverage and explicit gaps; do not claim clinical sufficiency from counts.
- Use provenance.py shared reference sets and target-specific link evidence in Korean jobs; keep detailed audit rows in SQLite and use storage.py for hash-verified lossless archival of superseded large JSON.
- Apply D21 patient_text.py to the admitted D20 graph; generate only patient-reachable SAY and EXAM text, freeze a fresh finite budget, and preserve separate semantic comparison and failure-without-retry.
- Prioritize the explicitly authorized NOVA_DEV_KEY development chat route with openai/gpt-6-luna medium; use only the pinned SNU education workspace for the alternative Docker Codex CLI route.
- Apply D22 NOVA-only continuation, compact request-local IDs, exact anatomical scope, preserved reviewed results, and user-authorized failure resumption until completion or the same-day request or service limit.
- Use evidence.py to package replay code, schema, policy, source inventories, hashes, coverage, and verification for organizer review separately from the runtime archive.

## Containers and Verification

- Use the proven project dev container with tests/workflow/compose.offline.yaml for current projection and checks; keep dependencies off the host.
- Preserve the existing extraction image and dedicated authentication volume; use the declared extraction service for the explicitly requested Korean run without downloading dependencies.
- Run python -B Dev/tests/workflow/test_workflow.py for the complete offline consultation flow.
- Run python -B Dev/tests/workflow/test_admitted.py --submission PATH --output PATH for actual admitted knowledge and archive isolation with scripted patient and model responses.
- Run python -B Dev/tests/workflow/test_korean_admitted.py --submission PATH --output PATH for exact prepared Korean delivery, Context polarity, and separate examination acquisition through SOAP and confirmed submission.
- Run python -B Dev/tests/ontology/test_database.py for source/approval/quota/Korean behavior and verify_database.py plus verify_catalog.py for real-source coverage, graph semantics, provenance, Korean coverage, and resource evidence.
- Use tests/ontology/compose.build.yaml with the root dev image for two-CPU eight-GB builds and isolated prepare checks; keep source mounts read-only.
- Run the isolated package Compose service for actual ZIP evidence.
- Keep synthetic workflow results, real-source structural projection, clinical review, runtime admission, authenticated SDK execution, and diagnostic performance distinct.
- Report only performed checks and reconcile root, submission, and data states before handoff.
- Keep the D17 review adoption record in architecture/D17_REVIEW_ADOPTION.md and leave diagnostic performance claims outside offline acceptance.
