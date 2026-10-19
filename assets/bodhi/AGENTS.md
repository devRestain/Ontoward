# BODHI Source Contract

- Preserve original_readme.md and bodhi-s/ upstream files unchanged; keep project guidance separate.
- Ingest all eight bodhi-s/csv files under the 2026-10-15 full-source request; use PRESENT_IN for current diagnostic associations and retain other source roles without unsupported runtime conversion.
- Preserve Symptom UUIDs, raw nullable SNOMED fields, root identifiers, qualifier axes, selection metadata, raw labels, and source row positions.
- Verify raw SNOMED fields against supplied RF2 before asserting a mapping; identifier presence alone does not prove semantic correctness.
- Check Condition execution role before registering Disease; retain non-disease, history, inactive, and unknown-ID dispositions.
- Keep symptom_given_condition and condition_given_symptom directions distinct; preserve strong_predictor without a score bonus.
- Keep every source variant's required conditions together; let D49 final classification complete general relationships from model knowledge without fabricating patient observations.
- Use Extraction/ontoward_extraction/ for a fresh D49 work DB and qualitative v5-enum-1 assets. Preserve old preparation custody and receipts as historical records; never use them as new builder inputs.
- Keep clinical review and runtime admission separate from source projection and preserve upstream attribution and license notices.
