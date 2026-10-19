# Data Contract

- Own durable source inventories, withdrawal receipts, preparation history, extraction checkpoints/results, and artifact provenance. Record progress only in PROJECT_STATE.md and choices only in root DECISION_STATE.md.
- Apply D49 before historical scoring, source-only generation, NOVA-only continuation, or admission rules. Keep older accepted artifacts as historical custody rather than executable knowledge.
- Preserve supplied assets, source-custody SQLite, previous preparation results, accepted ZIPs, and receipts byte-for-byte.
- Keep retired active runtime assets and old builders in extraction/retired-d42-2026-10-19/ with per-file hashes and archive hashes in withdrawal.json.
- Keep new build work/output under extraction/v5-enum/ in distinct fingerprint directories. Never feed historical generated DBs, vocabularies, questions, or policies into the new extractor.
- Keep source inspection/build/request identity in the work SQLite; exclude credentials. Preserve received responses, rejected attempts, explicit retries, neutral results, usage, and unknown outcomes.
- Keep the authored v5.0 structure in ontology/schema.ttl synchronized with submission/knowledge/schema.ttl. Use ontology/AGENTS.md for qualitative relation semantics.
- Install only verified build-specific files and replace the active manifest last. Require new v5-enum-1 hashes; provide no old-format conversion or default policy.
- Preserve relationship provenance in preparation as needed, but export no relationship source, confidence, or reviewer fields to runtime clinical input. Preserve actual patient acquisition and Education document citations in their own owners.
- Record final D49 image, code, synthetic artifact, withdrawal, and performed-check hashes in provenance/algorithm-d49-2026-10-19.json without rewriting historical receipts.
- Mark real model generation, login, real bundle installation, clinical validity, and official evaluation as not_run for this slice. Leave the real active manifest absent.
