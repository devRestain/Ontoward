# ACI-Bench Dataset Contract

## Structure

- Treat `aci-bench-corpus/` as the upstream dialogue and clinical-note corpus.
- Use `challenge_data/` for the primary note-generation splits.
- Use `src_experiment_data/` for alternate transcription and speech-recognition experiment inputs.
- Preserve `LICENSE.txt` as the CC BY 4.0 source attribution for this dataset.

## Application

- Use the dataset for separately scoped note-generation and observed-fact fidelity review.
- Treat reference `note` values as targets rather than input dialogue.
- Avoid treating the corpus as a standalone labeled diagnosis benchmark.
- Follow nested contracts for join keys, split identity, and transcription variants.

## Ownership

- Preserve upstream corpus files and source attribution.
- Keep SOAP mappings and evaluation code in `app/`.
- Keep derived mappings, preparation evidence, and evaluation outputs in `data/`.

