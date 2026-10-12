# Random StatPearls pilot source review

Both full-document gpt-6-luna / medium / Standard calls completed with exit code zero and the fixed extraction JSON Schema. The two raw responses contain four empty arrays. Pydantic validation, source input hashes, final-message/event consistency, zero model tool events, and terminated recorded processes pass. There are no evidence spans to ground, so this pilot supplies no positive quotation-grounding or nonempty clinical-extraction evidence.

## Sampling and inputs

The draw sampled two distinct documents from 9,651 existing nonsymlink US_StatPearls catalog Markdown paths without disease, length, or approved-vocabulary filtering. The saved seed is 14452481379898003081. Selection, catalog, source, prompt, schema, and vocabulary hashes are retained. Aeromedical Transport is 29,819 bytes / 119 original lines; Red Reflex is 9,440 bytes / 56 original lines. No document was redrawn to obtain a nonempty result.

## Aeromedical Transport

Source: US_StatPearls/statpearls_article-17260.md, full permitted range 1–119, 2024 StatPearls overview. The source discusses aircraft transport indications, contraindications, safety, logistics, and staffing rather than a disease-target clinical presentation profile.

- Lines 21–37 discuss flight indications, pregnancy-related transfer conditions, CPR constraints, and altitude effects. The pneumothorax mention at line 37 concerns altitude-sensitive transport, not an approved Symptom/ExamFinding target, ContextFactor, or named Test association. Altitude/flight applicability cannot be silently discarded to create a general diagnostic pattern.
- Lines 81–89 discuss time-sensitive cardiac/stroke care and specialist transport. Myocardial infarction and stroke mentions at line 85 do not directly establish any permitted disease-target or disease-test relationship. Flight logistics and catheterization-lab destination statements are outside the selected relation types.
- Lines 107–119 concern interprofessional staffing, specialist support, and transport outcomes. They do not independently supply a safely representable relationship of the four selected types.

The empty output is consistent with this agent source review. A disease name appearing in a document is insufficient to create a pattern or attach a planning test.

## Red Reflex

Source: US_StatPearls/statpearls_article-28292.md, full permitted range 1–56, 2023 StatPearls overview. Its core concepts are the red reflex / Brückner examination, abnormal red reflex / leukokoria, and associated ocular diagnoses.

- Lines 13–19 describe the red-reflex examination and its equipment. Red-reflex assessment is not an approved ExamMethod, and an abnormal/absent red reflex is not an approved ExamFinding. It must not be mapped to Reduced pupillary light response or its method, which describes a different phenomenon.
- Lines 29–49 discuss ocular history, cataract, retinoblastoma, strabismus, refractive errors, and other eye conditions. The relevant disease concepts are outside the approved Disease list. Approved symptom wording such as blurred vision or vision loss does not make the missing disease endpoint representable.
- Lines 51–56 discuss pediatric screening and instruments. These statements do not supply a permitted approved finding-method pair or a disease-specific approved Test relation.

The empty output is consistent with this agent source review. No new concept, broad substitute, or unrepresentable pediatric condition was admitted.

## Interpretation and remaining evidence

This is an agent source audit, not clinician review or a gold-standard corpus annotation. The observed result confirms authenticated model execution and acceptance of this schema for two empty responses, plus the offline validation path. It does not establish that the model respects all 510 enum choices on nonempty outputs, correctly grounds relation quotations, preserves essential conditions in positive assertions, or extracts with measured precision or recall.

Elapsed call times were 8.090 and 7.952 seconds, totaling 16.042 seconds. Reported usage totals are 38,141 input tokens and 358 output tokens, including reasoning usage as reported by Codex events. These are subscription CLI usage observations, not API-price estimates or account-credit measurements. Exactly two invocations were made with no automatic retries; no recorded invocation process remains active.

Both source licenses are recorded as CC BY-NC-ND. The results are retained locally for preparation review; no derivative source material or knowledge was submitted or published. RDF generation, concept URI assignment, clinical-expert review, RDF admission, submission, and deployment remain not_run. A separately requested pilot on documents with directly representable approved concepts is needed to assess nonempty extraction.
