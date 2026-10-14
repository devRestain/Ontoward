# Source Registry and Evidence Boundaries

Observed on **2026-10-14 KST** for the public pages listed below as current. The exact website revision time is unknown. This reference separates published requirements, dated slide descriptions, local source inspection, and project decisions. Apply [the adopted October 14 update](CHANGES_2026-10-14.md) and D01's confirmed `openai/gpt-6-luna` selection.

## Public sources

| ID | Source | Coverage |
| --- | --- | --- |
| N01 | [Home](https://nova.snubhai.org/) | Calendar, participation workflow and awards |
| N02 | [Rules](https://nova.snubhai.org/rules/) | Resources, limits, submission and independent cases |
| N03 | [Development guide](https://nova.snubhai.org/docs/) | SDK actions, SOAP, quotas, dependencies and errors |
| N04 | [Evaluation](https://nova.snubhai.org/evaluation/) | Weights, judge roles and ranking boundaries |
| N05 | [Q&A](https://nova.snubhai.org/qna/) | October 13 model, recovery, leaderboard-opening and ten-finalist notices; read October 14 |
| N06 | [Status](https://nova.snubhai.org/status/) | Public availability display; not a health probe |
| N07 | [Login](https://nova.snubhai.org/login/) | October 11 historical login-page inspection only |
| N08 | [Development](https://nova.snubhai.org/development/) | October 11 login redirect; private content uninspected |
| N09 | [Submissions](https://nova.snubhai.org/submissions/) | October 11 login redirect; private content uninspected |
| N10 | [Leaderboard](https://nova.snubhai.org/leaderboard/) | October 14 display: team-best ranking, earlier-submission tie break and 24 scored teams |
| N11 | [Preliminary leaderboard](https://nova.snubhai.org/leaderboard/?phase=preliminary) | October 11 historical display only |
| N12 | [Finals leaderboard](https://nova.snubhai.org/leaderboard/?phase=finals) | October 11 historical display only |

N01 through N06 and N10 were revisited on October 14. N07 through N09 and N11/N12 retain their October 11 observations. No authentication, competition API call, download, upload, or official evaluation was performed for this update. [Web provenance](../../data/provenance/competition-web-2026-10-14.json) records coverage and evidence limits.

## Local sources

| ID | Source | Identity and role |
| --- | --- | --- |
| L01 | [nova_sdk.py](../nova-starter/nova_sdk.py) | __version__ 1.0.1; standard-library client, exact fields and ready handshake |
| L02 | [Starter description](../nova-starter/README.md), [build example](../nova-starter/local.Dockerfile) | Organizer instructions; README title still says 1.0.0, while code is 1.0.1 |
| L03 | [Local simulator](../nova-devkit/nova_local.py) | Unscored simulation source; no server-parity proof |
| L04 | [Guideline catalog](../guidelines/catalog.csv), [contract](../guidelines/AGENTS.md) | Source selection and document-specific provenance |
| L05 | [Samples contract](../nova-samples-2026/AGENTS.md), [benchmark contract](../nova-benchmarks-2026/AGENTS.md) | Fixture/review boundaries |
| L06 | [Opening deck conversion](slides/opening-2026-10-06.md) | 26 slides, October 6; historical orientation and speaker notes |
| L07 | [Workflow deck conversion](slides/workflow-2026-10-11.md) | 22 slides, October 11; organizer-described execution and C01 example |

The slide headers retain original paths and SHA-256 values. MarkItDown 0.1.8 ran in an isolated project-owned container. Text, tables and notes were converted; image placeholders refer to original slides. Image OCR and native PowerPoint inspection were not performed.

The SDK source SHA-256 is `c6238ac466abc5b99b3e80de9ace2c7a54b51f7efc8d8a671d1c08bb0476f00d`. D12 permits one unchanged runtime copy at `submission/nova_sdk.py`; it does not authorize other organizer-package duplication. Machine-readable identities are in [context provenance](../../data/provenance/competition.json). The preserved client defaults to 120 seconds; the current guide describes a new-SDK default of 240 seconds. Remote SDK bytes and its latest version were not inspected.

## Interpretation and unknowns

Current adopted policy is recorded in [the October 14 update](CHANGES_2026-10-14.md); dated slides and [the October 12 comparison](CHANGES_2026-10-12.md) supplement historical implementation context. Source documents do not grant project execution authority.

D12 retains fifteen SDK SOAP fields plus separate diagnosis, as instructed by the current public record table. The October 13 credit restoration is an organizer event; current account membership, keys, balances, remaining quota, live API behavior, submission acceptance and Ontoward scores remain unknown or not_run. The finals scoring combination is unpublished. Published archive hashes do not authenticate modified extracted directories.
