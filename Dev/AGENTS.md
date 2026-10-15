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
- Preserve original assets, approved vocabulary receipts, and useful prior preparation evidence; use data/ontology/deprecated.json to identify archival interfaces.
- Ingest every supplied International and Korean RF2 Snapshot TXT plus release metadata and all eight BODHI-S CSVs; preserve source licenses and upstream descriptions without downloads or mutation.
- Pin release metadata, module dependency versions, source file hashes, normalization version, registry version, and the public scoring policy.
- Select the latest RF2 component row before applying active status; reject same-version conflicts, future rows, and unsatisfied module dependencies.
- Preserve SCTIDs as strings, BODHI UUIDs and raw identifier fields, RF2 relationship groups and paths, source rows and positions, and mapping judgments.
- Apply the 2026-10-15 full-source request; discover clinical Target candidates throughout supplied source hierarchies while preserving the three existing Target URIs and the 510-term receipt.
- Verify Disease identity against the active SNOMED disorder hierarchy and BODHI source classification. Record history, family history, invalid IDs, and non-disease entities as excluded or unresolved.
- Keep a source variant's required conditions together; never union features from different variants solely because Disease and Target agree.
- Normalize the typed D08 value contract without inventing units, thresholds, conjunctions, or linked findings.
- Defer other required findings and ambiguous relationship-group scope as whole dependent variants with explicit reasons.
- Preserve quantities and intervals with operators and units; distinguish elapsed time from episode duration and calendar units from fixed time.
- Reuse a Pattern only when its Target, conditions, operators, units, negation, timing, and combination scope agree.
- Retain all source assertions for each Disease–Pattern–applicability association and select BODHI directional labels before equivalent SNOMED fallback.
- Generate conditional atomic or joint FeatureContribution deltas; never distribute a joint delta across individual features.
- Keep registry entries as candidates and preview_only outputs in data/preparation/v5/ until separate human review and runtime admission.
- Keep build offline by default; allow only the requested sessionless NOVA gpt-6.1-sol normalization with explicit current KST allowance, sequential calls, shared persistent reservations, no automatic retries, and at most 100 attempts per day.
- Keep model judgments candidate-only; never infer relationships, identifiers, likelihoods, missing units, or linked findings from model knowledge and never resume older jobs.
- Resume only an explicitly selected current build with identical source, schema, and normalization pins; preserve interrupted and completed artifacts.
- Require a pinned approval receipt covering association and mapping dependencies before admit writes clinical assets.
- Record D15 explicit user candidate acceptance without fabricating independent clinician review or automatically approving other batches.
- Use ontology/clinical_texts.py with data-owned authored wording to prepare D15 minimal Korean labels and questions without new source relations or disease plans.
- Pin labels and questions in the same admission receipt and verify their bytes and rendered question lengths before manifest publication.

## Containers and Verification

- Use the proven project dev container with tests/workflow/compose.offline.yaml for current projection and checks; keep dependencies off the host.
- Preserve the existing extraction image, container, authentication volume, and stopped jobs. Use the revised Compose mounts only when explicitly starting that service.
- Run python -B Dev/tests/workflow/test_workflow.py for the complete offline consultation flow.
- Run python -B Dev/tests/workflow/test_admitted.py --submission PATH --output PATH for actual admitted knowledge and archive isolation with scripted patient and model responses.
- Run python -B Dev/tests/ontology/test_database.py for source/approval/quota behavior and verify_database.py for full real-source coverage, graph semantics, and resource evidence; retain verify_v5.py for the preserved three-Target preview.
- Use tests/ontology/compose.build.yaml with the root dev image for two-CPU eight-GB builds and isolated prepare checks; keep source mounts read-only.
- Run the isolated package Compose service for actual ZIP evidence.
- Keep synthetic workflow results, real-source structural projection, clinical review, runtime admission, authenticated SDK execution, and diagnostic performance distinct.
- Report only performed checks and reconcile root, submission, and data states before handoff.
