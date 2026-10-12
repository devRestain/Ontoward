# Evaluation and Ranking

Observed **2026-10-12 KST**. Sources: [N04 evaluation](https://nova.snubhai.org/evaluation/), [N02 rules](https://nova.snubhai.org/rules/), [L07 slides 10–12](slides/workflow-2026-10-11.md).

| Domain | Points |
| --- | ---: |
| Information gathering | 25 |
| Diagnostic reasoning | 15 |
| Tests and follow-up | 10 |
| Safety | 15 |
| Communication | 15 |
| Efficiency | 20 |

Evaluation uses the interaction evidence, submitted record and diagnosis. Obtaining information and recording it are distinct requirements. Unsupported facts receive no credit; actual dialogue matters for communication. Private rubrics and per-case criteria remain unpublished.

| Route | Result and model boundary |
| --- | --- |
| Local devkit | Unscored simulation |
| Development key + sample.py | Unscored server sample interaction; development credits apply |
| Uploaded code sample validation | Public samples; private reference score; gpt-6-luna handles patient/examiner/judge roles |
| Preliminary leaderboard | Five nonpublic cases; gpt-6.1-sol official judging |
| Preliminary final | Ten cases; average of GPT (gpt-6.1-sol), Claude and Gemini |
| Finals | Automatic evaluation and top-five physician review; final combination to be announced |

Official evaluation is one per team/phase/KST day. Upload/build/sample validation do not consume that quota. Participant failures after evaluation starts count; confirmed service recovery does not consume an additional opportunity. Sample validation is optional before leaderboard submission. Select one version for final evaluation.

The opening deck's 40/30/30 finals breakdown is dated evidence, not the currently confirmed combination policy. See [the conflict record](CHANGES_2026-10-12.md).

The C01 deck example demonstrates actual information loss and inappropriate examinations. Its answer, prompts and reported score are development review material; they do not enter patient inputs or clinical knowledge. This workspace has not produced an official score in this slice.
