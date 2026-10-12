# Account, Credits, and Public Operations

Observed **2026-10-12 KST** unless a row explicitly preserves an older observation.

## Accounts and credits

Personal development keys are owner-managed, with one active key per account. Teams share credits. Issuing a replacement revokes the previous key. Team identity changes do not expand quota. Do not connect competition credentials to coding assistants or unrelated services. [N02 rules](https://nova.snubhai.org/rules/)

Outside a case, development-only calls can select gpt-6.1-sol or gpt-6-luna. Daily team call limits are 100 and 500 respectively; Doctor calls outside sessions have a 3,000 daily limit. These reset at KST midnight and are distinct from per-case limits. Development charges and official evaluation costs are separate. [N03 development guide](https://nova.snubhai.org/docs/)

Actual balance, credentials, team registration and sample UUIDs remain unknown. The opening deck's stated development-credit allocation is historical orientation, not a current account balance.

## Dated public observations

| Surface | Observed display |
| --- | --- |
| Web/submission service, October 12 | Available |
| Login mail, October 12 | Connected / available |
| elice API, October 12 | Configured / available |
| Evaluation runner, October 12 | Connected / available |
| Development/submission private pages, October 11 | Redirected to login; not revisited |
| Leaderboard phase views, October 11 | No results displayed then; not refreshed in this slice |

Current service rows derive from [N06 status](https://nova.snubhai.org/status/). A published calendar does not prove that a submission phase is operationally enabled. No mail, authentication, API health probe or evaluation was performed.

The four public Q&A entries currently show October 12. They cover execution, model policy, external-source use and contacting organizers. [N05 Q&A](https://nova.snubhai.org/qna/)

## Project configuration

Root .env contains local development connection settings and a blank key placeholder. It is Git-ignored and excluded from archives. submission/.env contains only the application-owned manifest setting and is versioned and packaged. The official runner supplies its own credentials. Neither file creates a session or authorizes an external call.
