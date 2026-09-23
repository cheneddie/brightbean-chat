# IG-first QA Matrix

Severity:
- **P0**: blocks merge/release when applicable.
- **P1**: required before the owning development stage is complete.
- **P2**: UX/observability improvements that cannot invalidate P0/P1 correctness.

## P0 — security, isolation and duplicate-side-effect cases

| ID | Scenario | Expected result |
|---|---|---|
| QA-P0-001 | Workspace B requests Workspace A connection/object id | Generic 404; no existence leak |
| QA-P0-002 | OAuth state workspace id is modified | Reject |
| QA-P0-003 | OAuth state is expired | Reject |
| QA-P0-004 | OAuth state is replayed where one-time binding applies | Reject/no second connection side effect |
| QA-P0-005 | Token is stored then DB row is inspected | No plaintext token |
| QA-P0-006 | Token/provider error is logged | Token/secret absent from logs and error responses |
| QA-P0-007 | Invalid webhook signature | No event execution and no attacker-amplified DB logging |
| QA-P0-008 | Oversized webhook request | 413/early rejection; no queue/event write |
| QA-P0-009 | Same comment/event webhook delivered repeatedly | One logical trigger execution |
| QA-P0-010 | Worker crashes during/reafter send | Recovery does not cause duplicate logical reply/DM |
| QA-P0-011 | User-supplied URL targets loopback/private/metadata IP | SSRF guard rejects |
| QA-P0-012 | Hostile comment/profile strings contain HTML/script payloads | Stored/rendered as escaped untrusted content |
| QA-P0-013 | Cross-workspace mutation attempted with guessed id | 404 and no mutation |
| QA-P0-014 | Wrong Instagram connection selected in queued job | Job cannot send as another tenant/account |
| QA-P0-015 | Revoked/invalid account token | Mark reauth/disabled as classified; no infinite retry |

## P1 — product correctness

| ID | Scenario | Expected result |
|---|---|---|
| QA-P1-001 | Connect one Instagram professional account | ACTIVE connection |
| QA-P1-002 | Connect multiple Instagram accounts in same workspace | Independent connections/tokens/webhook routing |
| QA-P1-003 | Keyword comment matches | Trigger exactly once |
| QA-P1-004 | Non-matching keyword | No trigger |
| QA-P1-005 | Any-comment trigger with text/emoji/simple content | Trigger exactly once |
| QA-P1-006 | Public reply succeeds, DM fails | Public reply is not duplicated on DM retry |
| QA-P1-007 | Public reply fails, DM policy allows continuation | States remain independently observable |
| QA-P1-008 | Private reply/DM succeeds | Delivery state recorded once |
| QA-P1-009 | Meta 429 | Retry/backoff; no busy-loop |
| QA-P1-010 | Meta 5xx/timeout | Classified retry with bounded backoff |
| QA-P1-011 | Meta permanent 4xx/unsupported recipient/content | No pointless retry |
| QA-P1-012 | Text/image/video/link/button payloads | Correct supported Instagram renderer behavior |
| QA-P1-013 | Follow status = FOLLOWING | Protected flow branch continues |
| QA-P1-014 | Follow status = NOT_FOLLOWING | Follow prompt/recheck branch |
| QA-P1-015 | Follow API result unavailable/ambiguous | UNKNOWN; configured fallback applied |
| QA-P1-016 | Username changes | Same platform user id maps to same contact |
| QA-P1-017 | Human takeover | Automation pauses before further automated sends |
| QA-P1-018 | Human resume | Automation resumes according to explicit flow state |
| QA-P1-019 | Disconnect Instagram account | Subscription/queued work/token state cleaned or disabled safely |
| QA-P1-020 | Database backup restore drill | Restored system passes integrity/smoke checks |

## Load/reliability acceptance

Minimum baseline exercises:
- sustained 100 webhook requests/second in a controlled test;
- burst of at least 1,000 valid normalized events;
- duplicate-delivery burst;
- worker restart while jobs are in-flight;
- queue backlog and recovery;
- Meta 429 burst simulation.

Webhook HTTP handlers should do bounded verification/normalization/persistence work and return promptly; network sends and flow work belong in workers.

## Follow Gate QA rule

Never collapse an API error/missing field into `NOT_FOLLOWING`.

The adapter/service contract must preserve three states:
`FOLLOWING | NOT_FOLLOWING | UNKNOWN`.

## Evidence required in each PR

- tests added/updated;
- exact commands/checks run;
- migration impact;
- tenant-isolation impact;
- secret/token impact;
- webhook/idempotency impact where relevant;
- manual QA steps for provider behavior not safely mocked;
- rollback notes.
