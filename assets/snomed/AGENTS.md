# SNOMED CT Source Contract

## Ownership and Source Boundary

- This directory is the local input location for an authorized International Edition RF2 release.
- Add licensed RF2 files here manually; preparation commands never download terminology data.
- Keep the supplied release files byte-for-byte unchanged and preserve the distributor's release notes and license notices alongside them.
- Do not place a Korean Edition or other extension here for this pipeline; the initial extraction uses International Edition clinical concepts and relationships.
- The preparation container mounts this directory read-only. Derived SQLite, mapping, response, review, and preview artifacts belong in `data/preparation/snomed/`.
- Keep licensing and distribution conditions with the release and review them before moving derived artifacts outside the project.

## Accepted Input

- Provide a single RF2 Snapshot directory tree with Concept, Description, inferred Relationship, English Language Refset, and Module Dependency Refset files.
- Concrete Values files are optional and are retained as source evidence without conversion to categorical runtime features.
- Provide the release date and English language refset SCTIDs explicitly to the import command. The release date is not hard-coded in this contract.
- The importer records file hashes and module dependency metadata and rejects mixed, future-dated, conflicting, or non-International rows.
