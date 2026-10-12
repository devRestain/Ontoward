# C10 Unintended Weight Loss Fixture Contract

## Case Meaning

- Treat `case.json.start_information` as the initial presentation of a 32-year-old woman reporting unintended weight loss over three months.
- Treat `patient_script` as private simulator history and `exam_results` as private examiner reference rows.
- Treat `case.md` as the full readable case representation containing both initial and simulator-only material.

## Review Materials

- Use `model_record.json` for the reference S, O, A, P, and separate diagnosis structure.
- Use `model_record.md` for human comparison after a separately scoped consultation.
- Keep reference conclusions and unrequested examination findings outside Doctor inputs.

## Application

- Use this fixture to examine weight trajectory, related symptoms, focused examination, and the distinction between obtained findings and investigation plans.
- Record only returned observations as patient facts.
- Keep proposed tests and treatments separate from performed actions and results.
- Preserve all four upstream case files and keep derived review evidence in the data scope.

