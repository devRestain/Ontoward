# SNOMED CT Source Contract

- Preserve the manually supplied International 2026-05-01 and Korean 2026-06-15 RF2 packages byte-for-byte with their license and release metadata.
- Keep source packages read-only; never download or rewrite RF2 from preparation.
- Compose the extension with the exact base module versions declared by active Module Dependency rows.
- Ingest every supplied Snapshot TXT including Concept, Description, Text Definition, inferred Relationship, Concrete Values, OWL, identifiers, and refsets plus release metadata; exclude Full historical files and runtime OWL inference.
- Select the latest effectiveTime for a component across supplied snapshots before active filtering; reject conflicting same-version rows and unsatisfied dependencies.
- Preserve SCTIDs as strings, component modules and dates, relationship groups, language expressions, and file hashes.
- Link Korean descriptions to the same SCTID and preserve Korean-specific module origin.
- Keep current preparation code in Extraction/ontoward_extraction/ and new durable evidence in data/extraction/v5-enum/ under D49; preserve old data/preparation/v5/ custody read-only.
- Treat identifier presence, taxonomy role, semantic mapping review, and runtime admission as distinct checks.
- Keep source identities and module versions in preparation manifests; exclude original RF2 from submission archives.
