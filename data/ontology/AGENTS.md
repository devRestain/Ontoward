# Ontology Contract

- Own schema.ttl as the authored schema_version 5.0 contract for knowledge_contract v5-enum-1. Keep its runtime copy synchronized.
- Keep extraction code in root Extraction/ and runtime validation in submission/knowledge/. Record progress only in ../PROJECT_STATE.md.
- Use language-tagged English/Korean labels and bilingual aliases; keep upstream identities in preparation and new role-specific identifiers in the runtime graph.
- Connect Disease through hasAssociation to DiseasePatternAssociation and one shared ClinicalPattern. Require one Disease owner, one Pattern, explicit targetScope, applicability, and diagnosticEffect per Association.
- Permit exactly one Symptom, ExamFinding, or ContextFactor Target and distinct nonempty ClinicalFeature conditions per Pattern. Keep each Feature local to one Pattern.
- Identify a relation by Disease, Target/full conditions, target_scope, and canonical applicability independently of effect. Reject conflicting effects unless the final classification resolves them.
- Export support, strong_support, against, and strong_against only. Keep neutral as a completed work-DB judgment and omit it from runtime RDF.
- Preserve paired onAttribute/ExpectedValue, presence/absence, concept/concept_set, any_of/all_of, numeric operators, interval bounds, and units. Preserve registered directed ValueMatch paths without source-required runtime metadata.
- Reject old scores, weights, typicality, predictiveness, sourceRef, and hasSupportingContext. Provide no compatibility conversion, scoring/reasoning policy, or old admission status.
- Use ContextFactor targets and applicability over the same CaseFacts. Keep patient/family/member, timing, observation, and episode scopes distinct; do not generalize one member's absence to a whole family.
- Recall new candidates through positive-effect scoped Target or applicability paths. Activate effects only after every condition matches. Preserve partial/unknown separately and never reverse a mismatch into an effect.
- Stop asking remaining conditions of an explicitly contradicted impossible relation. Refine matched patterns only within the same effect, applicability, scope, and observation; never add repeated observations as numeric support.
- Keep rule time any separate from concrete current/past/unspecified question time. Require same-target/scope presence before attribute questions, including attribute-only Patterns.
- Keep question order, SOAP category, and clarification in questions JSON attribute_roles. Require NFC Korean executable text of 1-30 codepoints and concrete physical EXAM paths.
- Require a six-file hashed bundle: schema, vocabulary, clinical, questions with attribute_roles, guideline index, and manifest. Resolve paths relative to the manifest and reject boundary escape/hash mismatch.
- Permit empty guideline selections for a new Disease; preserve document-relative paths/hashes/citations where documents are selected. Keep originals outside the submission ZIP.
- Keep the active manifest absent until a real verified build is installed; use synthetic bundles only under Tmp/ and do not infer clinical validity from loader acceptance.
