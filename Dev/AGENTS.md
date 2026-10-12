# Preparation Tools Contract

## Ownership

- Own pre-submission Python extraction, candidate schemas, source validation, RDF generation, bundle assembly, prompts, and technical preparation design.
- Keep submission-agent code and runtime readers in root submission/.
- Keep durable responses, provenance, checkpoints, concept mappings, reviews, and generated artifacts in root data/.
- Keep disposable run inputs and drafts in root Tmp/.
- Record preparation-tool progress in root PROJECT_STATE.md without creating a Dev state scope.
- Own packaging/package_submission.py as the development archive helper copied into the package image without runtime dependency on Dev/.
- Package submission runtime files and its public .env at the ZIP root; exclude guidance, state, caches, and root development credentials.
- Preserve agents/ and knowledge/ package paths in the archive and require their shared models and execution modules.
- Read archive inputs only from /submission and write output only to /output without traversing the project root or preparation data.
- Include required knowledge/*.ttl and knowledge/*.json assets below the submission package alongside its Python graph readers.
- Treat archive validation as artifact evidence rather than clinical readiness or source admission.

## Preparation Workflow

- Read root AGENTS.md, PROJECT_STATE.md, PRD.md, and DECISION_STATE.md D07 through D10 before implementation.
- Read root data/AGENTS.md, data/PROJECT_STATE.md, data/ontology/AGENTS.md, and applicable asset contracts before handling inputs.
- Apply the adopted D09 schema and offline candidate contract through ontology/models.py, ontology/tools.py, and ontology/extraction_prompt.md.
- Use the clinician-approved seven-object vocabulary in data/ontology/vocabulary-candidates.md as the baseline for later extraction-schema and pilot work under D09.
- Run preparation dependencies and Codex CLI in the project-owned ontology-extraction Compose service.
- Keep codex/Dockerfile and codex/environment.py separate from the submitted agent environment.
- Use relative project mounts and rebuild for the target machine architecture without transferring host authentication stores.
- Require the configured SNU workspace UUID and ChatGPT authentication before subscription calls.
- Keep credentials in isolated project-owned Docker state outside workspace artifacts.
- Run one independent read-only Codex extraction job at a time with web search disabled.
- Use gpt-6-luna with the user-selected medium reasoning pilot and Standard speed without silently substituting a model or account.
- Install only the pinned ontology/requirements.txt preparation dependencies in the extraction image; mount ontology/ read-only.
- Generate the data-owned extraction vocabulary and JSON Schema from approved tables and Python models; never hand-edit generated files.
- Use ontology.tools prompt and validate with a catalog-relative document, exact SHA-256, and inclusive one-based permitted lines.
- Reject the entire response on structural, vocabulary, source-hash, or span failure without repair or model retry.
- Treat candidate_validated as structural and quote-grounding evidence only; require separate clinical review and RDF admission.
- Permit source-supported new target/attribute/value candidates without admitting their applicability through schema validation.
- Exclude unrepresentable concepts and conditions without a hold queue; omit whole dependent relations when exclusion would broaden their meaning.
- Keep model calls, batch execution, resume policy, concept URI assignment, Turtle generation, and submission admission outside the schema slice.
- Use root Tmp/codex/ for disposable CLI scratch and root Tmp/packaging/ for generated archives.
- Mark imported fixtures as offline evidence and compare pilots only with identical selected source inputs.
- Define durable model-response, normalization, and resume records only with the later pilot contract without changing raw clinical assertions.
- Let deterministic Python validate source spans, assign URIs, and write Turtle and durable records.
- Stop and checkpoint quota, authentication, model-access, and ambiguous completion failures without unbounded retries.
- Respect user cancellation; reconcile saved completion evidence without launching another call.
- Keep unadmitted clinical artifacts outside submission bundles.

## Verification and Handoff

- Apply source grounding, schema, semantic review, quality admission, and separate submission checks under the adopted D09 contract.
- Preserve document-specific patterns and feature ownership when merging common concept URIs.
- Extract source-supported alternative symptom-targeted patterns independently without converting tentative patient interpretations into disease facts.
- Omit conditions or concepts that cannot be safely represented without weakening a retained relation.
- Define the later bounded pilot inputs and execution contract before model calls; define resume and Turtle checks only when that work is selected.
- Report only performed checks and distinguish documentation completion from installed tools, authenticated calls, extraction quality, and submission readiness.
