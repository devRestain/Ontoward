# DDXPlus Dataset Contract

## File Meanings

- Use `release_evidences.json` to map evidence codes to English questions, data types, default values, antecedent flags, and possible-value meanings.
- Use `release_conditions.json` to map conditions to names, ICD-10 identifiers, severity, symptoms, and antecedents.
- Treat `release_train_patients.zip`, `release_validate_patients.zip`, and `release_test_patients.zip` as separate source splits.
- Read each ZIP as a single extensionless CSV member without modifying the archive.
- Interpret `AGE`, `SEX`, and `INITIAL_EVIDENCE` as patient context and starting evidence.
- Interpret `EVIDENCES` as the coded complete symptom and history set.
- Treat `PATHOLOGY` and `DIFFERENTIAL_DIAGNOSIS` as reference diagnosis targets.

## Application

- Use release_evidences.json and release_conditions.json as D49 knowledge-preparation metadata. Keep patient ZIPs reserved for separately scoped evaluation and never ingest them into Extraction/.
- Resolve `E_*` and encoded value suffixes through the evidence dictionary before interpreting answers.
- Parse list-shaped CSV strings as data without evaluating them as executable expressions.
- Reveal only the requested evidence through a constructed simulator boundary.
- Avoid inventing physical-examination or laboratory observations from this history-only dataset.
- Preserve split boundaries and keep translations or generated dialogues as identified data-owned derivatives.

## Provenance

- Preserve `LICENSE.txt` and the DDXPlus version-2 attribution.
- Distinguish source-condition severity and differential probabilities from NOVA action availability or official scores.
- Record any archive extraction or transformation as a separate preparation action.

