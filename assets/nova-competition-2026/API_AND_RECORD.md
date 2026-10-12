# Session API, Actions, and Final Record

Observed **2026-10-12 KST**. Use [SDK 1.0.1](../nova-starter/nova_sdk.py), [N03](https://nova.snubhai.org/docs/) and [L07](slides/workflow-2026-10-11.md). No competition API was called during this review.

## Session and model calls

The SDK routes sample and official requests separately. Development uses NOVA_DEV_KEY; official execution supplies NOVA_RUN_TOKEN and NOVA_SESSION_ID. run_agent calls prepare, ready and consult in order. Official session responses contain initial information and budgets, not the full events history (L07 slides 4–6/11–12).

Relevant routes are GET /v1/session, POST /v1/session/actions, GET /v1/sample/cases, POST /v1/sample/sessions, GET /v1/sample/sessions/{id}, POST /v1/sample/sessions/{id}/actions, POST /v1/chat/completions, and POST /_nova/ready. The SDK chooses the appropriate action route.

Preliminary Doctor calls: minimum one and maximum 200 per case, input 500,000 and output 100,000 tokens. A call uses no interaction turn. Empty Doctor responses count toward calls, but not token-budget use or Doctor cost. The allowed controls are messages, max_tokens, reasoning_effort (low/medium/high), and temperature (0–2); do not assume tools, stream or response_format support. Reasoning tokens consume the output allowance. Development-only alternate models are unavailable inside a case.

## Actions and retry identity

SAY asks one question or delivers a short explanation. EXAM requests one specific maneuver. TEST is finals-only. Each accepted interaction uses one of 50 turns. Content is NFC-normalized to 1–30 code points, counting spaces and punctuation; never silently truncate. DIAGNOSE costs no turn and may follow the fiftieth response before the deadline.

| Boundary/error | Consequence |
| --- | --- |
| SDK ValueError before transmission | No request and no server turn |
| Server EMPTY_CONTENT / CONTENT_TOO_LONG for SAY/EXAM | No useful answer; one turn |
| EXAM_NOT_SPECIFIC / EXAM_NOT_RECOGNIZED | No finding; one turn |
| TEST_NOT_SPECIFIC / TEST_NOT_OFFERED / ACTION_NOT_AVAILABLE | No turn |
| INVALID_RECORD_FIELDS | Correct the record; no turn |
| PROVIDER_RESPONSE_INVALID / PATIENT_RESPONSE_INVALID / EXAMINER_RESPONSE_INVALID | Explicit server-format failure; no turn or charge; a new attempt uses a new ID |
| API_UNAVAILABLE or uncertain transport outcome | Preserve request ID and exact payload for retransmission |
| PROVIDER_UNAVAILABLE | Service outage; official recovery belongs to organizers |
| MODEL_CALL_LIMIT / MODEL_TOKEN_BUDGET | Stop further model-dependent work and finalize within remaining limits |

Use response/session budgets, not a local assumption that every failure is free. Repeated delivery of the same request retains the same ID and content; a corrected action is a new request. L07 describes server deduplication, but this project has not independently exercised it. A refusal is not an examination finding.

## Exact SOAP wire shape

```json
{
  "S": {"cc": "", "hpi": "", "pmh": "", "fh": "", "sh": "", "ros": ""},
  "O": {"exam": "", "tests": ""},
  "A": {"evidence": "", "differential": ""},
  "P": {"tests": "", "treatment": "", "disposition": "", "follow_up": "", "education": ""}
}
```

Send these 15 string fields as note and one nonblank main diagnosis as the separate diagnosis argument. D12 selects this format. The public table groups diagnosis under Assessment, while the SDK and submission example place it outside note. Do not add note.A.diagnosis. The organizer workflow deck says the record must not be entirely empty (slide 6).

For preliminary cases, O.tests stays empty and proposed investigations go in P.tests. The record limit is 100,000 UTF-8 bytes; diagnosis is limited to 500 bytes. Preserve obtained findings and turn provenance, distinguish unknown from negative and unperformed from planned, and state concise evidence rather than internal reasoning transcripts. Education written in P does not substitute for actual SAY delivery.

L07 slide 21 shows completed, record_digest and pending scoring in a diagnosis response. Treat that as an example response to validate at the boundary; a printed file, process exit or pending score is not independently confirmed evaluation success.
