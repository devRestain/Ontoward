# Account, Credits, and Public Operations

Observed **2026-10-14 KST** unless a row explicitly preserves an older observation. Changes are recorded in [the current update](CHANGES_2026-10-14.md).

## Accounts and credits

Personal development keys are owner-managed, with one active key per account. Teams share credits. Issuing a replacement revokes the previous key. Team identity changes do not expand quota. Do not connect competition credentials to coding assistants or unrelated services. [N02 rules](https://nova.snubhai.org/rules/)

Outside a case, successful development calls share a team quota of 1,000/day for gpt-6-luna, including default Doctor calls, and 100/day for gpt-6.1-sol. These reset at KST midnight; in-session Doctor calls instead use per-case limits. Development sample-session creation is 100/team/day and uploaded-code sample validation is a separate 10/day. Expired or completed sample sessions do not restore creation quota. Official evaluation is one/team/phase/day. [N02 rules](https://nova.snubhai.org/rules/), [N03 development guide](https://nova.snubhai.org/docs/)

The October 13 notices restore each team's development allocation to KRW 40,000 and remove pre-12:30 KST development calls, sample sessions and validations from that day's counts. Early outage validations were cancelled without automatic replay. These are one-time recovery events, not recurring resets or a current balance. Luna prices per million tokens are KRW 152 input / 15 cached input / 761 output; D09's SNU Edu CLI remains a separate preparation route. [N05 notices](https://nova.snubhai.org/qna/), [N03 development guide](https://nova.snubhai.org/docs/)

Actual balance, credentials, team registration and sample UUIDs remain unknown. The opening deck's stated development-credit allocation is historical orientation, not a current account balance.

## Dated public observations

| Surface | Observed display |
| --- | --- |
| Web/submission service, October 14 | Available |
| Login mail, October 14 | Connected / available |
| elice API, October 14 | Configured / available |
| Evaluation runner, October 14 | Connected / available |
| Development/submission private pages, October 11 | Redirected to login; not revisited |
| Main leaderboard, October 14 | 24 scored teams; team-best score and earlier-submission tie break |
| Explicit leaderboard phase-query views, October 11 | No results displayed then; not refreshed in this slice |

Current service rows derive from [N06 status](https://nova.snubhai.org/status/). A published calendar does not prove that a submission phase is operationally enabled. No mail, authentication, API health probe or evaluation was performed.

The October 13 notices announce the Doctor replacement, recovery events, 100 daily development sessions, official preliminary opening that afternoon, and ten advancing finalists. Exact opening clock time is unknown. [N05 Q&A](https://nova.snubhai.org/qna/)

## Project configuration

Root .env is the local development credential boundary, Git-ignored and excluded from archives; its contents were not inspected in this update. submission/.env declares the application-owned manifest, parser prompt and clinical-text paths and is versioned and packaged. The official runner supplies its own credentials. Neither file creates a session or authorizes an external call.
