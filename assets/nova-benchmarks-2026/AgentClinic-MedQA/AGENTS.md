# AgentClinic MedQA Dataset Contract

## File Meanings

- Treat `agentclinic_medqa.jsonl` as the original case collection and `agentclinic_medqa_extended.jsonl` as its larger overlapping extension.
- Parse each line as one JSON object containing `OSCE_Examination`.
- Use `Objective_for_Doctor` as task context and `Patient_Actor` as simulator demographic, history, symptom, and social information.
- Use `Physical_Examination_Findings` as examiner data and `Test_Results` as test-result data.
- Treat `Correct_Diagnosis` as a held-out diagnosis label.
- Handle optional additional fields such as `Management_and_Follow_Up` without assuming a uniform nested schema.

## Application

- Use these cases for a separately scoped simulated consultation or diagnosis evaluation.
- Avoid concatenating the base and extended collections as disjoint cases.
- Restrict test-result use according to the target phase because NOVA preliminary consultations do not execute TEST.
- Keep simulator fields and diagnosis labels outside initial Doctor prompts.
- Treat textual imaging descriptions as text without assuming image files exist.

## Provenance

- Preserve `LICENSE.txt` for AgentClinic and `LICENSE_MedQA.txt` for the underlying MedQA material.
- Retain the AgentClinic and MedQA attributions recorded by the package.
- Store conversion evidence and deduplication decisions in the data scope.

