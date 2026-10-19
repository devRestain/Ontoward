# Data Contract

- Own durable source inventories, withdrawal receipts, preparation history, extraction checkpoints/results, and artifact provenance. Record progress only in PROJECT_STATE.md and choices only in root DECISION_STATE.md.
- Apply D49 before historical scoring, source-only generation, NOVA-only continuation, or admission rules. Keep older accepted artifacts as historical custody rather than executable knowledge.
- Preserve supplied assets, source-custody SQLite, previous preparation results, accepted ZIPs, and receipts byte-for-byte.
- Keep retired active runtime assets and old builders in extraction/retired-d42-2026-10-19/ with per-file hashes and archive hashes in withdrawal.json.
- Keep new build work/output under extraction/v5-enum/ in distinct fingerprint directories. Never feed historical generated DBs, vocabularies, questions, or policies into the new extractor.
- Keep source inspection/build/request identity in the work SQLite; exclude credentials. Preserve received responses, rejected attempts, explicit retries, neutral results, usage, and unknown outcomes.
- Preserve the failed zero-result NOVA normalization checkpoint byte-for-byte during explicit recover-normalize. Keep the completed raw index in a separate current-fingerprint copy, carry usage and requests forward, and record the original identity and prior attempts in recovery.json and SQLite metadata.
- Preserve paused normalization checkpoints and done result bytes during recover-normalize-text. Keep raw responses and usage identical, record local pending-row acceptance from saved responses, and retain prior recovery metadata in the new checkpoint history.
- Preserve completed rows and attempt counters during recover-normalize-provider. Keep accepted requests and usage unchanged; retain known PROVIDER_RESPONSE_INVALID payloads and errors while recording their terminal failed state in the new checkpoint. Never reclassify unknown outcomes as confirmed failures.
- Preserve every job row, attempt counter, request, response, usage row, and source checkpoint byte during recover-normalize-batch. Require a settled paused normalization checkpoint and unchanged input, configuration, prompt, and clinical contracts; record the scheduler-only transition in recovery.json without model calls.
- Keep the authored v5.0 structure in ontology/schema.ttl synchronized with submission/knowledge/schema.ttl. Use ontology/AGENTS.md for qualitative relation semantics.
- Install only verified build-specific files and replace the active manifest last. Require new v5-enum-1 hashes; provide no old-format conversion or default policy.
- Preserve relationship provenance in preparation as needed, but export no relationship source, confidence, or reviewer fields to runtime clinical input. Preserve actual patient acquisition and Education document citations in their own owners.
- Record final D49 image, code, synthetic artifact, withdrawal, and performed-check hashes in provenance/algorithm-d49-2026-10-19.json without rewriting historical receipts.
- Record D50 runtime source and synthetic artifact evidence in provenance/algorithm-d50-2026-10-20.json without changing active extraction ownership or historical D49 receipts.
- Mark real model generation, login, real bundle installation, clinical validity, and official evaluation as not_run for this slice. Leave the real active manifest absent.
