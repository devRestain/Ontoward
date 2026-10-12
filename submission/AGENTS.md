# Application Contract

## Ownership

- Own submission-agent Python, application Pydantic schemas, CaseState, LangGraph flow, runtime graph readers, and model and patient interfaces.
- Keep execution classes in agents/ and RDFLib graph ownership and fixed readers in knowledge/ under D13.
- Share CaseState, InquirySlot, ActionSpec, and Update from agents/state.py and case-independent Resources from agents/resources.py.
- Keep run.py limited to the SDK entrypoint and agents/runtime.py limited to prepare and consult orchestration.
- Keep session, gateway, interview, reasoning, action, and submission responsibilities in their dedicated classes without inheritance scaffolds or registries.
- Use package-relative imports within agents/ and keep graph assembly in agents/workflow.py.
- Resolve file paths through this directory's settings.py and keep every knowledge asset below knowledge/.
- Leave source provenance, RDF artifact provenance, review records, and preparation-result state to the data owner.

## Application Behavior

- Use `../PRD.md` as the intended application behavior contract.
- Validate external inputs and outputs at explicit Pydantic boundaries.
- Keep CaseState in memory for one case and initialize a separate state for every new case.
- Freeze applicable HPI slots for each initial chief complaint and process them without diagnostic ranking or score-based early termination.
- Collect other symptoms through open inquiry before the first normal-path disease retrieval.
- Return every SAY and EXAM response through one InputGateway, including education responses.
- Preserve unresolved HPI conflicts and distinguish processed slots from budget-interrupted HPI.
- Recompute active and reserve hypotheses from deduplicated current evidence after initial retrieval.
- Apply capped positive-only context support without creating candidates or penalizing absent context.
- Route forced pre-retrieval termination to evidence-bounded synthesis without inventing a candidate or diagnosis.
- Return education replies to finalization and revise synthesis when new evidence appears.
- Check the budget again before action execution and distinguish graph-step limits from SDK turns.
- Separate confirmed submission, failure, unknown outcome, closed session, and expiry.
- Keep unimplemented clinical, validation, and SDK boundaries explicit without fake successful results.
- Keep unasked and unanswered items distinct from uncertain, present, and explicitly absent observations.
- Keep separate occurrences of the same symptom distinct and preserve confirmed broad and specific locations as parallel values within one occurrence.
- Link common site- or activity-qualified complaints to specific symptom concepts and retain finer qualifiers without location containment or global absence.
- Preserve raw reports, evidence-supported symptom interpretations, corrections, and uncertainty within the same observation and episode.
- Leave unspecified pain unresolved until location or activity supports a specific symptom.
- Update interpretations from acquired evidence without relabeling symptoms to fit a diagnosis.
- Preserve the source response, acquisition turn or initial-source marker, and clinical context alongside each normalized finding.
- Represent SAY, EXAM, finals-only TEST, and DIAGNOSE as distinct SDK actions.
- Select one question or examination maneuver per preliminary interaction.
- Apply the PRD session, input-length, retry, and SOAP submission contracts at explicit boundaries.
- Keep the main diagnosis in CaseState.diagnosis and send it as the separate SDK diagnosis argument.
- Validate exactly the SDK 1.0.1 fifteen SOAP fields and exclude note.A.diagnosis.
- Preserve the unchanged SDK copy and verify its source hash before packaging.
- Read public application settings from .env with runtime environment precedence and leave runner credentials to the SDK.
- Keep the case transcript locally without depending on official session events.
- Distinguish pre-transmission validation from server-side invalid SAY or EXAM requests that consume one turn.
- Write A.evidence as a concise list of obtained interview and physical-examination findings used to judge the main diagnosis.
- Name the supporting findings directly instead of stating their source or saying that the diagnosis is based on patient expressions.
- Keep response provenance and acquisition turns in CaseState and exclude unasked or unperformed findings from A.evidence.
- Separate education plans from explanations actually delivered through SAY.
- Keep patient-reported answers separate from examination and investigation findings.

## Knowledge Code

- Leave pre-submission extraction, candidate validation, RDF generation, and bundle assembly to root Dev/ under D09.
- Consume data-owned submission-admitted bundles without depending on Dev tools or extraction CLI authentication.
- Exclude the data-owned natural-language vocabulary candidates from runtime knowledge until clinician review and separate admission.
- Treat NOVA_GUIDELINES_DIR as a preparation source-location contract rather than a consultation retrieval dependency.
- Load the D08 schema and vocabulary with all manifest-declared clinical bundles into one RDFLib Graph during case-independent prepare().
- Query the prepared Graph without guideline-text retrieval, extraction, or patient writes during consultation.
- Keep the Graph outside CaseState and preserve patient observations only in case-owned state.
- Use fixed readers for concept candidates, symptom attributes, disease candidates, patterns, supporting contexts, exam methods, and SOAP test plans.
- Follow ../data/ontology/AGENTS.md for single-target pattern ownership, optional feature status and role, categorical pairing, and partial matching.
- Retrieve candidates from observed symptoms and ExamFinding through reverse targets and hasPattern traversal without requiring presentsAs.
- Union independent alternative-pattern retrieval paths without a BodySystem filter or mandatory co-occurrence.
- Use supported uncertain concept candidates for recall without treating them as multiple confirmed findings or duplicate support.
- Keep manually reviewed pattern importance independent from feature clinicalRole and leave selectivity optional for later post-build work.
- Use predefined queries when needed without accepting LLM-generated SPARQL.
- Preserve common concept URIs while leaving relation-level source paths, sections, applicability, and review records in data-owned preparation records outside the runtime graph.
- Preserve unmapped source text and concept-link uncertainty without creating an unsupported clinical relation.
- Keep review-only scripts, examination tables, and reference answers outside clinical knowledge and patient inputs.
- Reserve evaluatedBy and Test for a separate P.tests reader without using them for diagnostic candidate generation, matching, ranking, or action selection.
- Keep preliminary TEST execution blocked and O.tests empty.
- Keep treatment, disposition, follow-up, education, and warning-sign planning in the application without introducing SOAP or workflow nodes into this ontology.
- Map ExamFinding through detectedBy to ExamMethod.examRequestText and later call client.exam(text) after single-maneuver and NFC-length validation.
- Treat method URIs as internal identifiers and request texts as suggested payloads without asserting server recognition.
- Record actual examination results or refusals instead of expected findings.
- Exclude selective loading, Dataset, Named Graphs, and OWL inference from the first MVP.
- Treat missing knowledge associations as unavailable evidence rather than absent findings.
- Treat retrieved associations and source likelihood labels as supporting evidence rather than calibrated disease probabilities.

## Local State

- Record application implementation progress and evidence only in PROJECT_STATE.md.
- Exclude AGENTS.md, README.md, PROJECT_STATE.md, and caches from submission archives while including the public .env.
- Run the package Compose service to archive only this directory's runtime files and knowledge assets.
- Keep Turtle, required JSON schemas, and the runtime manifest in knowledge/ without parent-project fallbacks in execution or tests.
- Reference D01, D03, D04, D05, D06, D07, D08, D09, D11, D12, D13, and D14 in `../DECISION_STATE.md` without duplicating options or decision statuses.
- Leave source admission and preparation-result records to `../data/PROJECT_STATE.md`.
