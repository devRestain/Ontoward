# Public NOVA Samples Contract

## File Meanings

- Treat `case.json` as the machine-readable case with `case_id`, `start_information`, `patient_script`, and `exam_results`.
- Treat `case.md` as the readable presentation of those same initial facts, simulator script, and examination table.
- Treat `model_record.json` as the reference SOAP sections plus a separate top-level `diagnosis`.
- Treat `model_record.md` as the readable reference note for post-run review.

## Input Boundaries

- Give the Doctor only `start_information` at case initialization.
- Give `patient_script` only to the patient simulator and `exam_results` only to the examiner simulation boundary.
- Acquire later Doctor observations through actual SAY and EXAM responses.
- Keep reference records outside runtime prompts, diagnosis selection, and clinical retrieval inputs.
- Separate the top-level `diagnosis` from S, O, A, and P when studying the SDK submission shape.
- Treat reference notes as writing examples rather than perfect answers or an official scoring rubric.

## Use

- Use C01 for a sleep complaint, C03 for a caregiver's concern about a child's growth, and C10 for unintended weight loss.
- Use these fictional public cases for separately scoped simulator development and post-run comparison.
- Preserve both public-package and devkit copies without consolidating their directories.

