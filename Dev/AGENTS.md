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
- Use ontology/source_projection.py and ontology/v5.py as the sole current ontology preparation implementation.
- Treat the removed v4.2 SNOMED and guideline extraction pipelines as deprecated; do not restore or adapt them for compatibility.
- Preserve original assets, approved vocabulary receipts, and useful prior preparation evidence; use data/ontology/deprecated.json to identify archival interfaces.
- Read manually supplied International and Korean RF2 Snapshot packages and the three BODHI-S CSV files without downloads or source mutation.
- Pin release metadata, module dependency versions, source file hashes, normalization version, registry version, and the public scoring policy.
- Select the latest RF2 component row before applying active status; reject same-version conflicts, future rows, and unsatisfied module dependencies.
- Preserve SCTIDs as strings, BODHI UUIDs and raw identifier fields, RF2 relationship groups and paths, source rows and positions, and mapping judgments.
- Bound the first projection to AbdominalPain, Cough, and Fever. Require a new user request to expand the corpus.
- Verify Disease identity against the active SNOMED disorder hierarchy and BODHI source classification. Record history, family history, invalid IDs, and non-disease entities as excluded or unresolved.
- Keep a source variant's required conditions together; never union features from different variants solely because Disease and Target agree.
- Normalize the typed D08 value contract without inventing units, thresholds, conjunctions, or linked findings.
- Defer other required findings and ambiguous relationship-group scope as whole dependent variants with explicit reasons.
- Preserve quantities and intervals with operators and units; distinguish elapsed time from episode duration and calendar units from fixed time.
- Reuse a Pattern only when its Target, conditions, operators, units, negation, timing, and combination scope agree.
- Retain all source assertions for each Disease–Pattern–applicability association and select BODHI directional labels before equivalent SNOMED fallback.
- Generate conditional atomic or joint FeatureContribution deltas; never distribute a joint delta across individual features.
- Keep registry entries as candidates and preview_only outputs in data/preparation/v5/ until separate human review and runtime admission.
- Keep source preparation deterministic and provider-free; do not invoke NOVA or Codex models or resume old jobs.

## Containers and Verification

- Use the proven project dev container with tests/workflow/compose.offline.yaml for current projection and checks; keep dependencies off the host.
- Preserve the existing extraction image, container, authentication volume, and stopped jobs. Use the revised Compose mounts only when explicitly starting that service.
- Run python -B Dev/tests/workflow/test_workflow.py for the complete offline consultation flow.
- Run python -B Dev/tests/ontology/verify_v5.py against the bounded real-source preview for source pins, dispositions, shared patterns, and scoring behavior.
- Run the isolated package Compose service for actual ZIP evidence.
- Keep synthetic workflow results, real-source structural projection, clinical review, runtime admission, authenticated SDK execution, and diagnostic performance distinct.
- Report only performed checks and reconcile root, submission, and data states before handoff.
