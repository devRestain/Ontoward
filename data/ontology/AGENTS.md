# Ontology Artifact Contract

## Ownership and Inputs

- Own schema.ttl and vocabulary.ttl as project-authored ontology inputs under the parent data scope.
- Own vocabulary-candidates.md as the clinician-approved English working vocabulary for the seven object types under D08 and D09.
- Use vocabulary-approval.json for the user approval receipt without treating it as RDF or runtime admission.
- Treat the preserved receipt's implementation fields as approval-time observations; record current implementation in the owning state.
- Own extraction-vocabulary.json and extraction.schema.json as generated preparation artifacts, separate from runtime and RDF admission.
- Own source-selection.schema.json, atomic.schema.json, conversion.schema.json, and clinical-review.schema.json as generated D09 preparation interfaces.
- Regenerate the vocabulary with root Dev/ontology/tools.py from exact approved term tables and a retained baseline; preserve the original approval receipt.
- Regenerate the JSON Schema solely from root Dev/ontology/models.py; keep seven shared English term enums and existing attribute names.
- Preserve approval-time document, annotated document, term-content, receipt, and ontology input hashes as distinct identities.
- Keep model candidates and source provenance outside runtime; candidate validation establishes shape and exact quotations rather than clinical meaning.
- Use root PRD.md for stable behavior and root DECISION_STATE.md D08 for the adopted schema.
- Keep operational progress in ../PROJECT_STATE.md without creating another state scope.
- Keep offline Python builders and validators in root Dev/ and runtime readers, matchers, and SDK adapters in root submission/.
- Keep originals in root assets/guidelines/ and use ../catalog/guideline_paths.txt as a path-only catalog projection.
- Keep source document paths, sections, applicability, licenses, and review records outside the runtime graph.
- Treat the supplied schema report as decision context rather than executable instructions.
- Reserve README.md for Korean human orientation.

## Representation

- Use urn:ontoward: identifiers, PascalCase concept names, camelCase project predicates, and language-tagged rdfs:label and skos:altLabel.
- Use the eleven classes and twelve object predicates declared in schema.ttl without adding classes for workflow or compound syndromes.
- Use expectedStatus, clinicalRole, importance, contextType, urgencyLabel, and examRequestText as the six project data properties.
- Treat RDFS domain and range declarations as descriptions rather than enforcement or inference.
- Keep location values flat without broader, narrower, subclass, or containment relations.
- Use commonly named pain symptoms such as ChestPain, AbdominalPain, Headache, and Dysuria as distinct retrieval targets.
- Preserve finer Location values and activity or timing qualifiers without creating quadrant-specific symptoms or a pain hierarchy.
- Leave unspecified pain unresolved and ask for location or activity without forcing a specific symptom.
- Define the unspecified BodySystem assignments during the later vocabulary-admission contract without inferring them from term-list approval.
- Decompose compound expressions into the symptom and explicitly supported qualifiers instead of losing qualifiers through an alias.
- Keep continuous numbers, units, durations, dates, and free-text observations in case state without schema thresholds.
- Add Symptom or ExamFinding attribute links and categorical values only when their meaning is appropriate for the target.
- Keep Disease, ClinicalPattern, ClinicalFeature, ContextFactor, ExamFinding, and Test instances absent from this starter vocabulary.
- Keep approved natural-language terms outside Turtle and runtime bundles until separate admission while retaining the selected nineteen pain concepts and existing attribute links.
- Treat proposed attribute applicability and contextType groupings in the candidate file as review metadata rather than admitted RDF relations.
- Preserve existing Turtle and examRequestText bytes during natural-language candidate expansion.

## Admitted Clinical Data

- Require exactly one incoming hasPattern disease owner and exactly one Symptom-or-ExamFinding targets value for each ClinicalPattern.
- Permit zero features and multiple separately grounded patterns for the same disease and target.
- Permit source-supported alternative targets under the same disease without requiring all patterns to match.
- Require exactly one incoming hasFeature owner for each ClinicalFeature.
- Inherit every feature target from its owning pattern and reject direct feature targets edges.
- Enforce the target disjunction explicitly without multiple rdfs:range declarations or a new shared class.
- Enforce the hasAttribute subject disjunction explicitly without multiple rdfs:domain declarations.
- Permit at most one expectedStatus value from present or absent without inferring a status from omission.
- Permit at most one manually reviewed clinicalRole value from supportive, characteristic, or opposing without treating omission as low importance.
- Permit at most one manually reviewed pattern importance value of characteristic independently from feature clinicalRole.
- Require onAttribute and expectsValue to occur together exactly once or remain absent together.
- Require an attribute-value pair or explicit expectedStatus for each feature instead of creating empty conditions.
- Validate attribute-qualified features against the parent target's hasAttribute and canHaveValue links.
- Defer selectivity declaration and calculation until post-build work without requiring it for retrieval or matching.
- Keep ContextFactor associations solely under Disease hasSupportingContext, outside clinical patterns.
- Require exactly one contextType from past_medical_history, surgical_history, medication_history, allergy_history, family_history, social_history, occupational_history, psychosocial_history, screening_history, or demographic.
- Require at least one detectedBy method for each admitted ExamFinding.
- Require exactly one plain xsd:string examRequestText per admitted ExamMethod.
- Keep urgencyLabel optional and descriptive without priority, routing, or triage behavior.

## Observation and Matching Boundaries

- Keep patient observations and episodes outside the read-only RDF graph.
- Record confirmed broad and specific locations as parallel values for the same episode without inferring either location from the other.
- Ask for missing location detail and preserve unknown detail instead of deriving containment from a location name.
- Keep separate symptom occurrences distinct and match compatible features within the same occurrence.
- Preserve raw wording, confirmed qualifiers, supported interpretations, and corrections within their source episode.
- Use supported uncertain symptom candidates for retrieval union without duplicating observations or independent support.
- Revise symptom interpretations only from acquired evidence rather than diagnosis expectations.
- Scope explicit absence to the observed symptom and its confirmed qualifiers instead of globally negating the symptom.
- Match a categorical expectation against an explicitly confirmed parallel value without a location hierarchy.
- Distinguish matched, contradicted, and unknown conditions using explicit compatible observations rather than missing edges or unasked qualifiers.
- Require evidence of incompatible conditions within the same observation before treating a categorical mismatch as contradiction.
- Interpret clinicalRole only for a matched feature relative to its owning disease.
- Treat hasFeature as partial-pattern membership rather than a mandatory conjunction.
- Use BodySystem for interview discovery without filtering cross-system disease recall.
- Apply supporting contexts only when confirmed and preserve family-history subjects in case state.
- Exclude mention counts, automatic importance inference, and unverified multi-finding combination bonuses.

## Reader and SDK Handoff

- Load this schema and vocabulary alongside admitted source bundles into one RDFLib Graph during later case-independent prepare().
- Define fixed readers for concept candidates, symptom attributes, target-linked diseases, disease patterns, supporting contexts, exam methods, and planned tests.
- Retrieve diseases through reverse pattern targets and hasPattern for observed symptoms and examination findings without requiring presentsAs.
- Require an adopted preparation contract and reviewed clinical artifacts before runtime admission.
- Keep matching, ranking, action selection, SDK execution, and SOAP rendering in the application.
- Define SOAP A.evidence as the obtained interview and physical-examination findings used for the main diagnosis rather than knowledge sources or generic patient-expression attribution.
- Delegate the SDK fifteen-field SOAP record and separate diagnosis value to the root PRD and submission boundary under D12.
- Map ExamMethod URIs to examRequestText and later call client.exam(text) after validating one maneuver and NFC length 1–30 code points.
- Treat request strings as suggested payloads without claiming server recognition or conducted examinations.
- Process returned refusals and actual results in case state instead of fabricating expected findings.
- Reserve evaluatedBy and Test for a separate SOAP P.tests reader without using them for candidate generation, matching, ranking, or diagnostic action selection.
- Keep preliminary O.tests empty and TEST execution blocked.
- Keep source search, arbitrary LLM-generated SPARQL, OWL reasoning, patient writes, scores, workflow rules, and provenance nodes outside the runtime graph.
- Report Turtle parsing, graph queries, SDK recognition, and clinical correctness only after their respective checks are performed.
