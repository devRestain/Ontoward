# Competition Profile and Calendar

Source snapshot: **2026-10-14 KST**. Source IDs resolve in [SOURCES.md](SOURCES.md); changes are in [the current update](CHANGES_2026-10-14.md).

## Published profile

NOVA 2026 expands to *Navigating Optimal clinical decisions via Virtual-patient Agents*. The task is a clinical agent workflow: obtain information from a virtual patient, perform permitted actions, explain care, and submit an initial record with one main diagnosis. The home page identifies SNUBH Medical AI Center and elice as organizers. [N01: Home](https://nova.snubhai.org/)

Participation: individual or ≤4 members/team; one team/person. All team roles can submit/select. [N02: Rules](https://nova.snubhai.org/rules/)

## Calendar

| Milestone | Published 2026 date, KST |
| --- | --- |
| Registration | September 13–October 3 |
| Online opening | October 6; 10:00–12:00 on the status calendar |
| Preliminary | October 12–22 |
| Finals | October 27–November 10 |
| Awards | November 20 |

Sources: [N01: Home](https://nova.snubhai.org/), [N06: Status](https://nova.snubhai.org/status/). Multi-day dates do not establish exact opening or closing clock times. N05 separately announces official preliminary leaderboard submissions from October 13 afternoon KST; no exact opening clock time is published. [N05: Notices](https://nova.snubhai.org/qna/)

## Phase orientation

| Phase | Engineering route | Deliverables |
| --- | --- | --- |
| Preliminary | Fixed `openai/gpt-6-luna` Doctor through the SDK from October 13; CPU-side retrieval and preparation | Python code ZIP |
| Finals | Locally loaded participant model on one GPU | Code ZIP, separate model ZIP, PPT/PPTX |

Ten teams advance to finals based on preliminary results. The later physician review concerns the final five teams. [N05: Notices](https://nova.snubhai.org/qna/), [N04: Evaluation](https://nova.snubhai.org/evaluation/)

Detailed limits belong to [EXECUTION_AND_SUBMISSION.md](EXECUTION_AND_SUBMISSION.md), action differences to [API_AND_RECORD.md](API_AND_RECORD.md), and ranking rules to [EVALUATION.md](EVALUATION.md). Sources: [N02: Rules](https://nova.snubhai.org/rules/), [N04: Evaluation](https://nova.snubhai.org/evaluation/).

Published workflow: registered-email login → development key and samples → code upload with optional sample validation or direct leaderboard evaluation → select one final version. Registration or sample testing does not itself request official evaluation. [N01: Home](https://nova.snubhai.org/)

Awards total KRW 5,000,000: one grand prize of 2,500,000, one excellence prize of 1,500,000, and two encouragement prizes of 500,000. [N01: Home](https://nova.snubhai.org/)

## Project interpretation

Use this package to locate requirements for a bounded implementation slice. The adopted route and unresolved choices remain in root [PRD.md](../../PRD.md) and [DECISION_STATE.md](../../DECISION_STATE.md). Describing finals here does not activate finals implementation or change the current preliminary route.
