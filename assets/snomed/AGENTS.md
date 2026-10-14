# SNOMED CT Source Contract

- Preserve the manually supplied International 2026-05-01 and Korean 2026-06-15 RF2 packages byte-for-byte with their license and release metadata.
- Keep source packages read-only; never download or rewrite RF2 from preparation.
- Compose the extension with the exact base module versions declared by active Module Dependency rows.
- Read Snapshot Concept, Description, inferred Relationship, optional Concrete Values, Language Refset, and Module Dependency files.
- Select the latest effectiveTime for a component across supplied snapshots before active filtering; reject conflicting same-version rows and unsatisfied dependencies.
- Preserve SCTIDs as strings, component modules and dates, relationship groups, language expressions, and file hashes.
- Link Korean descriptions to the same SCTID and preserve Korean-specific module origin.
- Keep preparation code in Dev/ontology/source_projection.py and derivative evidence in data/preparation/v5/ under D09.
- Treat identifier presence, taxonomy role, semantic mapping review, and runtime admission as distinct checks.
- Keep source identities and module versions in preparation manifests; exclude original RF2 from submission archives.
