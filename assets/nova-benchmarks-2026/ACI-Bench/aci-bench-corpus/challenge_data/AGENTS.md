# ACI Challenge Splits Contract

## File Meanings

- Use `train.csv` and `valid.csv` as the training and validation dialogue-note pairs.
- Use `clinicalnlp_taskB_test1.csv`, `clinicalnlp_taskC_test2.csv`, and `clef_taskC_test3.csv` as three distinct test collections.
- Treat `dataset`, `encounter_id`, `dialogue`, and `note` as the source-target CSV columns.
- Treat matching `*_metadata.csv` files as names, demographic fields, `cc`, and additional complaints.

## Application

- Join source-target and metadata records through `encounter_id` within the selected split and dataset identity.
- Keep the source `dialogue` separate from the target `note`.
- Preserve training, validation, and test membership when preparing an evaluation.
- Parse embedded newlines and quoted values without counting physical lines as encounters.

## Interpretation

- Inspect speaker attribution before deriving clinical facts from `[doctor]` and `[patient]` labels.
- Treat any SOAP mapping as an app-owned transformation requiring explicit preparation evidence.
- Keep reference notes outside evaluated generation inputs.

