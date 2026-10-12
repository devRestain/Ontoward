# Ten-document random StatPearls pilot source review

## Observed execution and validation

Ten distinct documents were drawn without replacement from 9,651 existing nonsymlink StatPearls catalog Markdown files, with no disease, vocabulary, length, or document-type filter. The seed is 4032498269726396991. All ten full-document gpt-6-luna / medium / Standard calls completed with return code zero, no retries, no model tool events, and no remaining recorded invocation processes. The fixed schema was accepted in all ten calls. Pydantic validation and source input hashes pass in all ten saved results.

All model responses contain four empty arrays, with zero patterns, features, contexts, methods, tests, or quotation spans. Total invocation time is 82.509 seconds; reported usage is 206,423 input tokens and 1,829 output tokens. These are CLI subscription usage observations, not API-price estimates or remaining-account measurements. Because the responses have no evidence spans, positive model quotation grounding was not exercised.

The selection was prepared on 2026-10-12 KST; calls finished on 2026-10-13 KST. The date in the artifact directory identifies the selection and is retained unchanged.

## Source review by document

| Index | Source | Reviewed interpretation |
| --- | --- | --- |
| 1 | Prisms; article-143863 | Diagnostic and therapeutic prism use, squint measurements, ocular conditions, and optical procedures. Generic stroke mentions must not be forced to a specific approved stroke subtype. The reviewed sections did not establish a clear required approved disease-target relation. |
| 2 | Advancement Flaps; article-17249 | Reconstruction, vascular supply, postoperative complications, and tobacco-related procedural suitability. Do not turn flap pallor or surgical infection into an unqualified systemic finding or a Cellulitis diagnosis; these are not directly established by the source. |
| 3 | Motor Evoked Potential; article-143429 | Intraoperative signal monitoring and anesthesia/physiology. MEP is outside the approved Test list. Relative contraindications such as epilepsy do not establish a permitted diagnostic association. |
| 4 | Mohs Micrographic Surgery Management of Melanoma and Melanoma In Situ; article-165206 | Melanoma treatment, margins, histology, and postoperative complications. The disease and key procedures are outside the approved clinical enums. |
| 5 | Defamation in Healthcare; article-34715 | Professional conduct, legal disputes, and individual illustrative cases rather than general diagnostic disease-target knowledge. |
| 6 | Platysmaplasty Facelift (Archived); article-21529 | Preserve the Archived title. Surgical anatomy and nerve-injury complications must not be relabelled as Bell palsy or an unqualified neurological pattern. |
| 7 | Medicare and Medicaid Accreditation and Deemed Status; article-155642 | Administrative accreditation and organizational quality requirements. No diagnostic relationship is established by administrative language. |
| 8 | Tinnitus; article-30212 | The empty output misses at least two directly source-supported, representable approved disease-target relationships, documented below. |
| 9 | Metoclopramide; article-25088 | Medication indications, contraindications, and adverse effects. GERD treatment-resistant populations and acute migraine treatment language require careful interpretation; these were not counted as definite omissions in the small reference subset. The empty response must not be assumed clinically complete. |
| 10 | Sonography Gynecology Infertility Assessment, Protocols, and Interpretation; article-128647 | Infertility-specific imaging, ovarian cyst characterization, and reproductive interventions. Applicability and test-mapping precision need review before creating a generic disease-test relationship. The empty response must not be assumed clinically complete. |

This is an agent source review, not clinician review or exhaustive annotation of all eligible relationships. No whole-corpus recall or precision is claimed.

## Confirmed representable reference omissions

The Tinnitus source directly associates hypertension with onset of tinnitus at original line 20 and states that ear diseases including Meniere disease cause tinnitus at line 21. The approved enums contain Hypertension, Ménière disease, and Tinnitus. Mapping the source spelling Meniere disease to the approved spelling preserves the concept rather than inventing a new diagnosis.

Two hand-authored reference patterns use exactly one approved disease, target kind symptom, target term Tinnitus, zero features, and exact original-line quotes. Both references pass the existing Pydantic and source-span validator. The source quotes are also present in the saved model prompt. The two required patterns are:

- Hypertension -> Tinnitus, grounded at line 20.
- Ménière disease -> Tinnitus, grounded at line 21.

The model emitted neither relationship: zero of two in this agent-authored reference subset. The subset quality result is fail. The reference JSON and validated envelope are retained separately from the raw model response and do not count as extracted or clinically admitted knowledge. No response was repaired, and no additional model call was made.

## Handoff and admission

Execution and schema checks pass; extraction quality fails the known source-reference subset. Thus all-empty output cannot be explained only by out-of-vocabulary source selection. The exact cause is not established. Prompt/schema visibility, extraction instructions, and model behavior should be investigated in a separately bounded follow-up; changing them and rerunning a call is outside this completed ten-call request.

The selected source metadata labels every document as a textbook disease overview, even when the title and body concern administrative or legal material. Those labels alone are insufficient to select clinically useful future inputs. No source or metadata was changed to improve this draw.

Source licenses are retained as CC BY-NC-ND. Inputs, prompts, raw responses, completion events, model-call metadata, schema/vocabulary snapshots, offline validations, and the source-reference audit remain local preparation evidence. The original clinical sources and all ontology inputs are preserved. Quality admission is fail; clinician review, concept URI assignment, RDF generation/admission, submission, and deployment remain not_run.
