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
- Apply the guideline-derived graph sequence from root decision D05 and the artifact structure from D07.
- Apply the ontology model and consumption boundaries from D08.
- Keep source-supported alternative disease presentations distinct from corrections of patient wording without creating unsupported clinical relations.
- Apply the adopted D09 extraction-schema and offline-validation contract; require a later bounded pilot and admission contract before producing clinical RDF.
- Keep generated two-stage schemas in ontology/ and source selections, unit inputs, atomic statements, candidate links, and clinical-review records outside submission/.
- Require reviewed disease-focused textbook or clinician-guideline inputs for the two-stage workflow.
- Record multiple approved disease topics and exact source group-definition evidence as preparation metadata; preserve single-disease candidate ownership and member-specific conditions.
- Preserve differential-list provenance without treating a possible association as expected presence or clinical importance.
- Keep Disease, Symptom, ExamFinding, AttributeValue, ContextFactor, Test, and ExamMethod candidates in English until clinician review before later extraction-schema and pilot work.
- Apply source acquisition choices from root decision D02 only when preparing SNOMED CT.
- Apply language-dependent source choices from root decision D04 when relevant.
- Limit BODHI source preparation to the three BODHI-S CSV files defined by the root PRD.
- Preserve source version, origin, license, and attribution with admitted assets.
- Preserve guideline locations, titles, organizations, years, languages, source URLs, and document licenses.
- Select source documents through the guideline catalog and exclude project guidance and review-only case answers.
- Limit model extraction to the bounded textbook inputs selected under the later D09 pilot contract.
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
- Define durable model-response, checkpoint, mapping, and clinical-review paths through the later D09 pilot contract rather than disposable Tmp/.
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
