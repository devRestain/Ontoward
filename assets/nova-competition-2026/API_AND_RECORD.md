# Session API, Actions, and Final Record

Observed **2026-10-14 KST**. Use the preserved [SDK 1.0.1](../nova-starter/nova_sdk.py), [N03](https://nova.snubhai.org/docs/) and [the current update](CHANGES_2026-10-14.md); [L07](slides/workflow-2026-10-11.md) is dated context. No competition API was called during this review.

## Session and model calls

The SDK routes sample and official requests separately. Development uses NOVA_DEV_KEY; official execution supplies NOVA_RUN_TOKEN and NOVA_SESSION_ID. run_agent calls prepare, ready and consult in order. Official session responses contain initial information and budgets, not the full events history (L07 slides 4–6/11–12).

Relevant routes are GET /v1/session, POST /v1/session/actions, GET /v1/sample/cases, POST /v1/sample/sessions, GET /v1/sample/sessions/{id}, POST /v1/sample/sessions/{id}/actions, POST /v1/chat/completions, and POST /_nova/ready. The SDK chooses the appropriate action route.

Preliminary Doctor is openai/gpt-6-luna from October 13, confirmed by the user under D01. Omitting model selects that Doctor. Calls remain minimum one and maximum 200 per case, input 500,000 and output 100,000 tokens, without interaction turns. Empty responses count toward calls but not token-budget use or Doctor cost. Use messages, max_tokens and reasoning_effort (low/medium/high); temperature is accepted but ignored. Reasoning consumes the output allowance and may need a larger max_tokens budget. Do not assume tools, stream or response_format support. The separate session-free development route is unavailable to submitted consultation code. [N02](https://nova.snubhai.org/rules/), [N03](https://nova.snubhai.org/docs/), [N05](https://nova.snubhai.org/qna/)

The guide specifies a 180-second provider response-start limit and recommends a longer client wait; its described new SDK default is 240 seconds. The locally pinned 1.0.1 client defaults to 120 seconds. Retain its bytes and record transport alignment as unperformed application work; no new SDK download or version identity was established. [N03](https://nova.snubhai.org/docs/)

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
| PROVIDER_UNAVAILABLE | Provider outage or no response start within 180 seconds; guide recommends waiting and retrying the same ID |
| REQUEST_PENDING (503/409) | Same call still processing or another case call active; preserve exact payload and request ID for later recovery |
| MODEL_CALL_LIMIT / MODEL_TOKEN_BUDGET | Stop further model-dependent work and finalize within remaining limits |

Use response/session budgets, not a local assumption that every failure is free. Repeated delivery of the same request retains the same ID and content; a corrected action is a new request. The guide describes pending-call recovery, but the application has not implemented or exercised that recovery. D11's no-automatic-retry policy remains the current implementation boundary pending a bounded alignment slice. A refusal is not an examination finding.

## Exact SOAP wire shape

```json
{
  "S": {"cc": "", "hpi": "", "pmh": "", "fh": "", "sh": "", "ros": ""},
  "O": {"exam": "", "tests": ""},
  "A": {"evidence": "", "differential": ""},
  "P": {"tests": "", "treatment": "", "disposition": "", "follow_up": "", "education": ""}
}
```

Send these 15 string fields as note and one nonblank main diagnosis as the separate diagnosis argument. D12 selects this format and the current public record table explicitly instructs separate transmission. Do not add note.A.diagnosis. The organizer workflow deck says the record must not be entirely empty (slide 6).

For preliminary cases, O.tests stays empty and proposed investigations go in P.tests. The record limit is 100,000 UTF-8 bytes; diagnosis is limited to 500 bytes. Preserve obtained findings and turn provenance, distinguish unknown from negative and unperformed from planned, and state concise evidence rather than internal reasoning transcripts. Education written in P does not substitute for actual SAY delivery.

L07 slide 21 shows completed, record_digest and pending scoring in a diagnosis response. Treat that as an example response to validate at the boundary; a printed file, process exit or pending score is not independently confirmed evaluation success.
