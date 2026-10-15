# Ontology Contract

## Ownership

- Own schema.ttl as the current D08 v5.0 contract and vocabulary.ttl as starter terminology under the parent data state.
- Preserve the exact previous schema and vocabulary in v4.2/ as deprecated evidence.
- Use deprecated.json to identify old extraction interfaces and preparation records that are not v5.0 inputs.
- Preserve vocabulary-candidates.md and vocabulary-approval.json as the approved 510-term seed and approval receipt, separate from clinical and runtime admission.
- Keep source-specific candidate registries, mapping decisions, raw assertions, dispositions, and previews in ../preparation/v5/.
- Keep full-source SQLite custody and pinned batch receipts in ../preparation/v5/; do not treat model normalization, structural verification, or export as human approval.
- Keep Python preparation in root Dev/ontology and runtime types and readers in root submission/knowledge.
- Reference root PRD.md and DECISION_STATE.md D08/D09; record progress only in ../PROJECT_STATE.md.
- Reserve README.md for Korean human orientation.

## v5.0 Representation

- Use urn:ontoward: identifiers and language-tagged rdfs:label and skos:altLabel.
- Require the OntologySchema schemaVersion 5.0 marker and the classes and predicates in schema.ttl.
- Treat RDFS declarations as documentation; enforce cardinalities and semantic conditions in the reader.
- Connect Disease through hasAssociation to DiseasePatternAssociation, then pattern to a shared ClinicalPattern.
- Require one Disease owner and one Pattern per Association; identify an Association by Disease, Pattern, and canonical applicability conditions.
- Keep all original source assertions in preparation and the selected evaluation and minimal sourceRef values in runtime RDF.
- Require exactly one Symptom or ExamFinding Target and distinct nonempty ClinicalFeature conditions per Pattern.
- Keep each Feature local to one Pattern; inherit its Target and reject direct Feature targets.
- Define Pattern identity independently of Disease and source from Target, typed conditions, units, operators, status, timing, and condition scope.
- Represent presence and absence with expectedStatus and attribute expectations with paired onAttribute and expected.
- Store a strict ExpectedValue JSON payload under valueJSON with concept, concept_set, quantity, or interval kind.
- Preserve any_of and all_of meaning, numeric comparison operators, interval boundaries, and explicit units.
- Validate categorical values against the Target's hasAttribute and the attribute's canHaveValue links.
- Reject v4.2 hasPattern, expectsValue, importance, and clinicalRole assertions rather than deleting meaning through a compatibility conversion.
- Keep optional supporting ContextFactor links, BodySystem interview links, ExamMethod mappings, and Test plans in their existing roles.
- Require contextType from the established ten context categories and detectedBy plus examRequestText for admitted ExamFinding.
- Use Test and evaluatedBy only for SOAP P.tests, without diagnostic TEST actions in the preliminary workflow.

## Matching and Weights

- Recall candidate Diseases broadly from a confirmed or supported uncertain Target without requiring all detailed Features.
- Activate an Association score only after every Feature and applicability condition matches confirmed observations.
- Preserve matched, contradicted, and unknown; unasked or uncertain values activate no detailed score.
- Compare compatible conditions within one observation and episode; never combine separate episodes.
- Replace matched ancestor scores with stricter matched variants even when the refined score decreases.
- Use the maximum score once among incomparable matched variants and once per Disease–Target across repetitions and sources.
- Sum distinct Target supports as ranking scores rather than probabilities.
- Use the manifest-pinned public scoring policy and preserve fractional and zero values.
- Prefer BODHI condition_given_symptom labels; retain symptom_given_condition for question ordering and strong_predictor for metadata and conflict review.
- Use exact SNOMED relation or generalized fallback only when no equivalent BODHI label is present.
- Derive FeatureContribution as refined minus baseline Association score, keeping multi-condition changes joint.
- Keep patient observations and diagnosis scores in CaseState and workflow state outside the read-only graph.
- Permit only explicit evidenced ValueMatch paths with is_a, regional_part, or approved_region meaning; do not create patient observations from those paths.
- Keep specific pain complaints as Targets and preserve finer observed location and radiation values without invented containment or global absence.
- Defer linked findings, automatic absence penalties, prevalence adjustments, graph-frequency bonuses, and calibrated probability claims.

## Admission and Handoff

- Pin schema, registry, normalization, source snapshots and file hashes, and scoring policy in every manifest.
- Keep v5.0 preview generation separate from clinical review and submission admission.
- Admit only reviewed v5.0 clinical assets to submission/knowledge/; do not load deprecated data or preview registries during consultation.
- Load admitted schema, vocabulary, and bundles into one RDFLib Graph during prepare(), then calculate read-only Association profiles and FeatureContribution records.
- Keep raw source rows, file positions, full RF2 groups and paths, licenses, and mapping judgments in preparation; keep only execution conditions, selected labels, and source references in runtime.
- Preserve the fifteen-field SOAP and separate diagnosis contract; use obtained interview and examination findings for A.evidence.
- Apply D15 manifest-pinned Korean display labels and question assets without modifying the pinned v5.0 RDF representation or scoring policy.
- Report parsing, structural source projection, clinical correctness, and SDK acceptance from their respective performed checks.
