# Preparation Tools Contract

## Ownership

- Own pre-submission Python extraction, candidate schemas, source validation, RDF generation, bundle assembly, prompts, and technical preparation design.
- Keep submission-agent code and runtime readers in root submission/.
- Keep durable responses, provenance, checkpoints, concept mappings, reviews, and generated artifacts in root data/.
- Keep disposable run inputs and drafts in root Tmp/.
- Record preparation-tool progress in root PROJECT_STATE.md without creating a Dev state scope.
- Own maintained behavioral tests in tests/workflow and the implementation-to-test rule index in architecture/WORKFLOW_RULES.md; keep generated test assets and reports under root Tmp.
- Own packaging/package_submission.py as the development archive helper copied into the package image without runtime dependency on Dev/.
- Package submission runtime files and its public .env at the ZIP root; exclude guidance, state, caches, and root development credentials.
- Preserve workflow/ and knowledge/ package paths in the archive and require their shared models and execution modules.
- Read archive inputs only from /submission and write output only to /output without traversing the project root or preparation data.
- Include required knowledge/*.ttl and knowledge/*.json assets below the submission package alongside its Python graph readers.
- Include the environment-selected runtime prompt and text files under submission/config without packaging verification fixtures.
- Treat archive validation as artifact evidence rather than clinical readiness or source admission.

## Preparation Workflow

- Read root AGENTS.md, PROJECT_STATE.md, PRD.md, and DECISION_STATE.md D07 through D10 before implementation.
- Read root data/AGENTS.md, data/PROJECT_STATE.md, data/ontology/AGENTS.md, and applicable asset contracts before handling inputs.
- Use `ontology/snomed/` for RF2 import, local terminology search, vocabulary expansion and freeze, deterministic disease-target projection, NOVA requests, whole-packet validation, and preview Turtle export.
- Keep the earlier guideline schemas, prompts, validated candidates, approvals, responses, and pilot outputs intact as historical preparation artifacts; do not automatically resume them.
- Treat the approved 510 English terms as initial seeds for seven object kinds, not as a closed enum or size cap. Keep the selected SNOMED registry separate from the legacy extraction vocabulary and runtime Turtle.
- Read a manually supplied International Edition Snapshot from `assets/snomed/`; never download or modify RF2. Reject non-International modules, mixed/future releases, same-version component conflicts, missing module dependencies, and missing selected English language refsets.
- Preserve SCTIDs as text, full RF2 component rows, source-file hashes, release metadata, language refsets, and module dependency versions in the SQLite dataset under `data/preparation/snomed/`.
- Keep the seven Ontoward object kinds and 13 finding attributes. Use exact unique seed matches deterministically, offer local SCTID candidates for ambiguous mappings, and require evidence-grounded map, decompose, or exclude outcomes for every packet.
- Decompose compound findings into a reviewed base target and explicit qualifiers; never register a qualified finding as a plain synonym or infer a qualifier from general clinical knowledge.
- Require human selection or exclusion of every vocabulary item before freezing the versioned registry used by stage two.
- Generate Pattern packets only from exact `due_to`, exact `associated_with`, or subtype-intersection RF2 paths. Preserve direct versus descendant scope, the source disease concept, relationship identifiers, and hierarchy paths.
- Derive Feature candidates only from the target-finding source concept's actual relationships and descriptions. Preserve concrete values without categorical conversion and exclude any required condition that cannot be represented without broadening its meaning.
- Merge compatible source features by Disease–Target, preserve incompatible or explicitly distinct profiles as deterministic variants, and leave unresolved groupings out of preview. Set Pattern characteristic only under the selected `due_to` policy; never infer Feature `clinicalRole`.
- Keep imported datasets, registries, packets, call ledgers, raw responses, review records, and preview assets in the data-owned preparation directory; keep disposable fixtures and verification reports in `Tmp/snomed/`.
- Use the `ontology-extraction` Compose service with RF2 and the hash-pinned NOVA SDK mounted read-only, source schema and submission reader mounted read-only, and only declared preparation/output mounts writable.
- Use `openai/gpt-6.1-sol`, medium reasoning, a 4,000-token output cap, batches of at most five packets, and no temperature. NOVA is sessionless; require `NOVA_DEV_KEY` and `NOVA_API_BASE` only for an explicit `--live` run.
- Default extraction to dry-run. For live execution require both a per-run call cap and the caller-declared team daily remaining quota, bounded by 100 KST calls across both stages. Use one locked local ledger; never retry, switch models, repair responses, resume after an unknown outcome, or schedule future calls.
- Record request identity and input before transmission, persist raw responses and usage before validation, and block replays for cached failures or unknown outcomes. Cache by dataset, input, frozen registry, prompt, schema, and model settings.
- Generate JSON Schema from the SNOMED Pydantic models. Reject the complete response on any structural, packet, registry, source ID, exact quote span, or allowed-combination mismatch; require a disposition for every packet.
- Keep numeric conditions and unreviewed ExamFinding metadata in preparation records. Preview only valid registry concepts and patterns; never admit or copy preview Turtle into `submission/` automatically.
- Use root `Tmp/codex/` for legacy guideline validation, `Tmp/snomed/` for synthetic SNOMED verification, and `Tmp/packaging/` for generated archives.

## Verification and Handoff

- Run `python -m Dev.ontology.snomed verify` in the project extraction container for the full synthetic RF2 path, NOVA test doubles, preview loader, reverse Target query, and scoring check.
- Run the retained legacy vocabulary and guideline-candidate verifier when changing shared preparation contracts; report it separately from SNOMED verification.
- Require full packet disposition, exact source evidence, registry selection, graph cardinality, and preview-only validation before handing off generated results.
- Keep synthetic fixtures, actual RF2 coverage, model-call quality, clinician review, and submission admission as distinct evidence classes.
- Report only performed checks and distinguish documentation completion from installed tools, authenticated calls, extraction quality, and submission readiness.
