# BODHI Source Contract

- Preserve original_readme.md and bodhi-s/ upstream files unchanged; keep project guidance separate.
- Ingest all eight bodhi-s/csv files under the 2026-10-15 full-source request; use PRESENT_IN for current diagnostic associations and retain other source roles without unsupported runtime conversion.
- Preserve Symptom UUIDs, raw nullable SNOMED fields, root identifiers, qualifier axes, selection metadata, raw labels, and source row positions.
- Verify raw SNOMED fields against supplied RF2 before asserting a mapping; identifier presence alone does not prove semantic correctness.
- Check Condition execution role before registering Disease; retain non-disease, history, inactive, and unknown-ID dispositions.
- Keep symptom_given_condition and condition_given_symptom directions distinct; preserve strong_predictor without a score bonus.
- Keep each source variant's required conditions together and defer unresolved linked findings as whole variants.
- Use Dev/ontology/source_projection.py build/export/admit for full SQLite custody and reviewed v5.0 assets; retain original rows, hashes, role judgments, raw assertions, and unresolved variants in data/preparation/v5/.
- Keep clinical review and runtime admission separate from source projection and preserve upstream attribution and license notices.
