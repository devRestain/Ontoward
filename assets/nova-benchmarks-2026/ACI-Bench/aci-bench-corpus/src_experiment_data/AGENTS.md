# ACI Transcription Experiments Contract

## File Meanings

- Distinguish `aci` and `virtscribe` filename groups as source transcription collections.
- Interpret `asr` as speech-recognition text, `asrcorr` as corrected speech-recognition text, and `humantrans` as human transcription.
- Treat the supplied filename combinations as the available variants without assuming every split has every variant.
- Treat `dataset`, `id`, `dialogue`, and `note` as source-target columns.
- Treat matching `*_metadata.csv` files as demographic, name, and chief-complaint metadata.

## Application

- Join variant records and metadata through `id` within their dataset, split, and variant context.
- Use aligned variants to study transcription sensitivity in a separately scoped note-generation experiment.
- Keep all representations of one encounter in one evaluation split.
- Select only the intended variant instead of merging alternate transcripts as independent patients.

## Interpretation

- Preserve transcription errors and speaker labels in upstream files.
- Inspect possible reversed doctor and patient labels before assigning observed facts.
- Keep reference notes outside model inputs and record any corrected derivative in the data scope.

