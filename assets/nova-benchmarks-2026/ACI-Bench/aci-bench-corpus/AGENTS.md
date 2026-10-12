# ACI Encounter Corpus Contract

## Source Structure

- Use `challenge_data/` as the primary challenge split collection.
- Use `src_experiment_data/` as alternate source dialogue variants for transcription experiments.
- Treat `README.txt` as the preserved upstream corpus description.
- Follow the parent dataset's license and attribution ownership.

## Data Meaning

- Treat each source-target CSV record as an encounter identifier, dialogue, and reference clinical note.
- Treat companion `*_metadata.csv` files as encounter attributes and chief-complaint metadata.
- Use the actual header's `encounter_id` or `id` field rather than assuming both collections share one key.
- Parse quoted multiline dialogue and note values with a CSV-aware reader.

## Application

- Select one transcription variant per encounter for an experiment.
- Keep alternate representations of the same encounter in one evaluation split.
- Distinguish reference-note generation from diagnosis accuracy and official NOVA scoring.

