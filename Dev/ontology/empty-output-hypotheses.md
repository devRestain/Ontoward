# Empty-output investigation and falsifiable hypotheses

This is a read-only investigation of the completed ten-document pilot. No new model call, prompt adoption, schema change, response repair, vocabulary expansion, or RDF admission was performed. Observed facts are in data/preparation/empty-output-investigation-2026-10-13/facts.json. The proposed diagnostic alternatives and selection status belong to root DECISION_STATE.md D09.

## Established observations

- All ten saved raw model messages are already empty before offline validation; their JSON matches the saved response files. No filtering or validator fallback explains the emptiness.
- The saved prompts match their prepared hashes. Both source-grounded Tinnitus reference sentences are in the actual prepared prompt. The Python runner passes those bytes through process.communicate(input=prompt); the installed CLI help documents `-` as stdin prompt input.
- Hypertension, Ménière disease, and Tinnitus exist in the correct schema enums. The two disease-owned, single-target, zero-feature reference patterns pass the unchanged Pydantic and quote validator.
- The task prompt contains instructions, source metadata, section context, and numbered source text. It contains neither serialized vocabulary tables, serialized JSON Schema, nor a schema-file path. The separate CLI --output-schema argument points to the correct schema.
- The generated JSON Schema is 21,722 bytes, contains all 510 approved clinical labels, and contains zero description fields. Required properties and closed objects constrain shape but do not document disease-target semantics or extraction coverage.
- No positive nonempty JSON example is present in the extraction instructions. The instructions permit empty arrays and explicitly prefer a valid empty result to an unsupported relationship.
- The configured model and effort are gpt-6-luna and medium; web search is disabled and sandbox mode is read-only. No checked custom instruction setting or checked local AGENTS file overrides the task. This does not expose or rule out provider-side system instructions.
- All ten invocations returned zero, completed far below 300 seconds, and produced empty stderr. No observed authentication, quota, schema rejection, or timeout explains the result.

## Hypothesis register

| ID | Hypothesis | Priority | Supporting observations | Limitation / falsification |
| --- | --- | --- | --- | --- |
| H1 | The task lacks explicit vocabulary/semantic context, so membership is treated as uncertain despite output constraints. | High | No typed vocabulary is in the task text; no schema descriptions; the prompt refers to approved enums without presenting their tables. | The CLI does pass an output schema. Provider request serialization and model visibility were not observed, so absence from task text does not prove absence from model context. Test explicit vocabulary alone against the same input/schema. |
| H2 | The omission-heavy instructions and valid-empty option cause over-abstention. | High | Omission rules, strict equivalence, essential-condition exclusion, untrusted-data wording, and the final empty-output preference; no positive demonstration or explicit coverage instruction. | These constraints are clinically necessary and do not logically require omitting the two references. Clarify affirmative extraction behavior while preserving every safety and evidence boundary. |
| H3 | Extraction is scoped to the document's principal topic, not all approved diseases mentioned in its body. | Medium | The positive control chapter is titled Tinnitus, which is a Symptom rather than an approved Disease; many other chapters are procedural, drug, or administrative topics. No instruction explicitly rules out title-based scoping. | No internal model rationale is available. Add a narrow instruction to inspect every approved disease regardless of chapter title in a later isolated test. |
| H4 | A full phenotype with qualifiers is assumed necessary for a ClinicalPattern; simple sourced associations are not recognized as sufficient. | Medium | No descriptions or concrete nonempty example teach a zero-feature pattern; the task uses profile/pattern ownership terminology. | Python and the prompt permit zero features. Demonstrate an independent, directly supported association as a zero-feature pattern using a synthetic formatting example unrelated to test labels. |
| H5 | Unrepresentable neighboring names cause rejection of an entire sentence/list rather than only the unsupported endpoints. | Medium | The hypertension reference shares a line with generic heart disease, unspecified diabetes, drug statements, and dosage conditions. The prompt emphasizes discarding whole dependent claims. | Independent relations should survive without discarding essential applicability. State explicitly that independently supported endpoints are considered separately; do not split required conjunctions. |
| H6 | Many randomly selected sources genuinely have low overlap with the ontology. | Confirmed contributor, incomplete explanation | Legal, administrative, optical, surgical, and archived chapters dominate the sample. | This does not explain the two representable Tinnitus omissions. It cannot justify accepting all-empty output as extraction success. |
| H7 | Large output vocabulary, full-document distraction, and this model/task combination increase extraction difficulty. | Secondary | Four relation types, 510 terms, 13 structural attributes, and full-document prompts of 15,672–38,451 bytes must be handled together. | There is no observed hard limit, timeout, or measured model-capability deficit. Compare an original-line excerpt only after the first diagnostic contrast; do not silently change model, effort, or schema. |

Priority means order of investigation, not a numerical causal probability. H1 and H2 are the first candidates; interaction is plausible. Current evidence establishes under-extraction in the reference subset but does not establish a single cause.

## Low-priority or excluded explanations for the reference case

- Postprocessing deleted nonempty output: excluded by raw-message/file equality and the absence of a filtering fallback.
- The schema cannot encode the requested pattern: excluded for these two references by unchanged-model validation.
- The positive concepts are unapproved: excluded by membership in the actual typed enums.
- The prepared source omitted the relevant lines: excluded by the source quotes in the saved prompt and input-hash match; full provider-side payload was not observed.
- An observed CLI failure or timeout fabricated success: unsupported by return codes, completion events, empty stderr, and timing.
- A checked local instruction override forbids extraction: no such setting or file was found; provider-side instructions remain unobserved.

## Recommended diagnostic scope

The pending proposal in D09 compares explicit typed vocabulary and affirmative extraction semantics in a four-cell controlled design on the original complete Tinnitus document. It preserves the approved enums, schema hash, line numbering, model/effort/speed, and source identity. A fifth negative-control call is conditional on a candidate meeting the two-reference criterion. No experiment has been run or adopted by this investigation.

Affirmative wording should clarify that all approved disease references are evaluated regardless of title; direct source associations may form zero-feature patterns; unrepresentable adjacent endpoints do not invalidate independent supported relations; and untrusted source instructions are ignored while source facts remain usable as evidence. It must preserve essential conditions, disjunction/compound semantics, exact quotations, and approval boundaries. Do not force minItems=1, fabricate qualifiers, broaden disease subtypes, or remove empty output for genuinely irrelevant documents.

Accept a diagnostic candidate only if both reference pairs are extracted with original-line evidence and no forced diabetes subtype, generic-heart-disease substitution, differential-list inference, or unsupported qualifier. The negative control is the original Red Reflex document, expected to remain empty. Four single samples provide preliminary evidence only; baseline non-reproduction, interactions, and stochastic variation must remain explicit.

## Official documentation boundary

- https://learn.chatgpt.com/docs/developer-commands?surface=cli describes --output-schema as the expected final response shape and `-` as stdin prompt input.
- https://developers.openai.com/api/docs/guides/structured-outputs states that structured responses may still contain mistakes and recommends adjusting instructions, providing examples, or simplifying tasks.

These sources support the distinction between output shape and task correctness; they do not establish that this installed CLI omits schema enums from provider input. The installed launcher delegates to a native binary, and the full serialized provider request and model's reason for omission were not observed.
