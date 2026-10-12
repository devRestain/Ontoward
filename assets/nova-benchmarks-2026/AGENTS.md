# Reference Benchmarks Contract

## Dataset Roles

- Use `AgentClinic-MedQA/` for English simulated history, physical examination, testing, and diagnosis cases.
- Use `DDXPlus/` for coded synthetic symptom and antecedent questioning with diagnostic labels.
- Use `ACI-Bench/` for encounter-dialogue to clinical-note generation.
- Treat these text datasets as external research references rather than NOVA evaluation cases.

## Use Boundaries

- Follow each dataset's nested contract before selecting input fields or labels.
- Keep held-out diagnoses, reference notes, and simulator answers separate from agent-visible inputs.
- Preserve upstream training, validation, and test divisions when a later evaluation slice uses them.
- Account for English source text and differing schemas before mapping data into the Korean NOVA interaction contract.
- Keep adaptation code in `app/` and any admitted derivatives and provenance in `data/`.

## Provenance

- Preserve dataset license files and source attribution with any separately authorized derivative.
- Distinguish organizer-reported collection details and checksum claims from locally performed verification.
- Record dataset conversion, splitting, simulation, and evaluation only when those actions actually occur.

