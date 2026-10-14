# Data Directory Contract

## Ownership

- Own source provenance, review records, preparation results, admitted additional sources, and generated RDF knowledge artifacts in this directory.
- Preserve organizer inputs in `../assets/` and record their inspection evidence in this scope.
- Keep extraction, candidate validation, RDF generation, and bundle assembly code in root `Dev/` and runtime retrieval code in root `submission/`.
- Treat Turtle knowledge as derived general clinical evidence rather than patient state.
- Use ontology/, catalog/, and provenance/ for retained inputs without creating additional state scopes.
- Own ontology/schema.ttl, ontology/vocabulary.ttl, catalog/guideline_paths.txt, and provenance/competition.json without adding another operational state.
- Own ontology/vocabulary-candidates.md as natural-language clinician-review data separate from RDF inputs and submission knowledge.
- Admit runtime Turtle and required JSON schema assets into submission/knowledge/ after the existing review and submission checks; keep root data/ exclusively for development and provenance.
- Keep runtime execution and tests independent of this directory even when no completed submission knowledge exists.
- Keep directory-orientation files separate from actual Turtle bundles and manifest evidence.
- Read ontology/AGENTS.md before changing the schema or starter vocabulary.

## Source Preparation

- Read the root PRD and `DECISION_STATE.md` before preparing source assets.
- Apply the SNOMED-first preparation sequence from root decisions D05 and D09; retain earlier guideline-derived records without automatically resuming their workflow.
- Apply the ontology model and consumption boundaries from D08.
- Keep source-supported alternative disease presentations distinct from corrections of patient wording without creating unsupported clinical relations.
- Keep the D09 SNOMED preparation outputs in preparation/snomed/ and require separate review and runtime admission before placing any resulting assets in submission/.
- Keep generated guideline schemas, source selections, unit inputs, atomic statements, candidate links, and review records in their existing locations as preserved prior-work artifacts.
- Use International Edition RF2 metadata and module dependency records to identify the pinned release; do not infer a version from a filename or an expected month.
- Keep one preparation dataset's SQLite import, source manifest, vocabulary candidates, human review, frozen registry, projection packets, raw NOVA responses, call ledger, reports, and preview assets under preparation/snomed/.
- Preserve the approved 510-term English vocabulary as seed input only. Keep the expanded, versioned SNOMED registry separate from ontology/extraction-vocabulary.json and the authored runtime vocabulary.
- Require a human selection or exclusion decision for every vocabulary item before stage two consumes the registry.
- Preserve source SCTIDs, Description and Relationship identifiers, exact quotations and spans, relationship groups, direct versus descendant scope, source variants, and file hashes in preparation records.
- Do not admit inferred clinical links from model knowledge. Keep SNOMED, feature, terminology review, and RDF submission admission as distinct evidence.
- Record multiple approved disease topics and exact source group-definition evidence as preparation metadata; preserve single-disease candidate ownership and member-specific conditions.
- Preserve differential-list provenance without treating a possible association as expected presence or clinical importance.
- Keep Disease, Symptom, ExamFinding, AttributeValue, ContextFactor, Test, and ExamMethod candidates in English until human selection freezes the D09 registry; keep runtime admission separate.
- Apply source acquisition choices from root decision D02 only when preparing SNOMED CT.
- Apply language-dependent source choices from root decision D04 when relevant.
- Limit BODHI source preparation to the three BODHI-S CSV files defined by the root PRD.
- Preserve source version, origin, license, and attribution with admitted assets.
- Preserve guideline locations, titles, organizations, years, languages, source URLs, and document licenses.
- Select source documents through the guideline catalog and exclude project guidance and review-only case answers.
- Do not start new guideline model extraction under the replaced D09 path unless a later explicit user request selects new inputs and a call budget.
- Preserve common concept URIs and keep relation-level source paths, sections, applicability, and review records outside the runtime graph.
- Keep catalog/guideline_paths.txt as a path-only projection of the catalog with project-root-relative assets/guidelines/ paths.
- Treat the path index as original-document navigation rather than extraction, source admission, or provenance review.
- Separate source presence and selected metadata inspection from full provenance review and generated RDF evidence.
- Check document-specific conditions before including RDF relations, planning evidence, excerpts, or translations in submissions.
- Exclude transformed copies of documents with modification-distribution restrictions from submission artifacts.
- Separate Doctor-visible starting information from simulator scripts, examination tables, and review answers.
- Preserve BODHI symptom UUIDs as source keys.
- Preserve nullable raw SNOMED identifiers separately from verified SNOMED links.
- Establish verified SNOMED links against the admitted terminology release.

## Artifact Evidence

- Record source admission, review, extraction, and bundle preparation results in `data/PROJECT_STATE.md`.
- Retain document-level extraction outputs and failed, pending-review, excluded, or approved preparation records outside submission bundles.
- Keep durable SNOMED request/response, checkpoint, mapping, review, call-ledger, and preview records under preparation/snomed/, not disposable Tmp/.
- Distinguish automated validation, complete pilot review, sampled batch review, quality admission, and submission admission.
- Record explicit user candidate acceptance without an additional agent source-meaning audit gate.
- Bundle only quality-admitted and submission-admitted outputs by existing source group.
- Preserve bundle file lists, versions, source identity, triple counts, and preparation-result links in the submission manifest.
- Distinguish source inspection from generated Turtle and manifest evidence.
- Distinguish the authored schema and starter vocabulary from extracted clinical relations and submission bundles.
- Measure triple counts, Turtle sizes, full-load time, peak memory, and query time on representative document lengths and types.
- Treat file partitioning as a maintenance boundary rather than evidence of reduced runtime memory.
- Verify submission size and file-count limits against actual bundles and required code.
- Keep published archive hashes separate from unverified extracted-directory identity.
- Record absent or unconfigured artifacts without claiming successful preparation.

## Handoff

- Keep one current source preparation goal in `data/PROJECT_STATE.md`.
- Keep pending choices and their alternatives in root `DECISION_STATE.md`.
- Reserve `data/README.md` for human-readable directory orientation.
