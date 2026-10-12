# C03 Child Growth Concern Fixture Contract

## Case Meaning

- Treat `case.json.start_information` as the initial presentation of a six-year-old boy attending with a caregiver concerned about short stature and growth.
- Treat `patient_script` as private simulator history and `exam_results` as private examiner reference rows.
- Treat `case.md` as the full readable case representation containing both initial and simulator-only material.

## Review Materials

- Use `model_record.json` for the reference S, O, A, P, and separate diagnosis structure.
- Use `model_record.md` for human comparison after a separately scoped consultation.
- Keep reference conclusions and unrequested examination findings outside Doctor inputs.

## Application

- Use this fixture to examine caregiver history, growth measurements and timing, examination selection, and planned investigations.
- Record only returned observations as patient facts.
- Keep proposed tests and treatments separate from performed actions and results.
- Preserve all four upstream case files and keep derived review evidence in the data scope.

