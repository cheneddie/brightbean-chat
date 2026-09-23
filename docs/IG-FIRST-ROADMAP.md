# IG-first Development Roadmap

This project treats the following roadmap and final acceptance list as the engineering source of truth.

## D0 — Baseline, governance and security gates

Tasks:
- Freeze upstream/fork commit baseline.
- Confirm CI on the fork.
- Preserve the existing BrightBean security baseline and traceability tests.
- Add project-specific QA and PR acceptance rules.
- Decide and document Python transitive dependency locking/hashing strategy.
- Record AGPL-3.0 implications before production commercialization.
- Keep `main` protected by process: branch -> PR -> CI/security -> review -> merge.

Exit criteria:
- Fork CI is green without business-logic changes.
- Security/dependency scans execute on the fork.
- D0 documentation exists and is reviewed.
- Supply-chain gap has an explicit remediation task.

## D1 — Instagram OAuth and multi-account connections

Tasks:
- Reuse existing Organization/Workspace/RBAC/ChannelConnection architecture.
- Instagram Login OAuth with signed, expiring state.
- Bind OAuth initiation to authenticated workspace and authorized initiator.
- Encrypt tokens at rest.
- Support multiple Instagram professional accounts in one workspace.
- Prevent accidental cross-workspace duplicate ownership of the same Instagram external account unless a later explicit agency-sharing model is designed.
- Connection states: ACTIVE / NEEDS_REAUTH / DISABLED.
- Token lifecycle and reauthorization UX.
- Webhook subscription lifecycle and disconnect/revoke handling.

Exit criteria includes:
- state tamper/replay/expiry tests;
- tenant isolation tests;
- token/log leakage tests;
- multi-account tests;
- revoked-token tests.

## D2 — Instagram comment event normalization and triggers

Tasks:
- Normalize comment webhook events into a stable internal event contract.
- Supported trigger modes: selected content, supported all-content scope, keyword list, exact/contains as applicable, any comment.
- Deduplicate by stable platform event/comment identifiers.
- Self-comment / system-generated-loop prevention.
- Persist enough immutable event context for downstream flow execution.

## D3 — Public comment replies

Tasks:
- No reply / fixed reply / reply pool.
- Separate delivery state from DM state.
- Idempotent retry semantics.
- Failure telemetry without duplicating comments.

## D4 — Comment to private reply / DM

Tasks:
- Official Meta private-reply/DM path only.
- Respect Meta time windows and platform policy.
- Opening message -> user interaction -> flow continuation.
- Delivery receipts/failures where available.
- Permanent vs retryable error classification.

## D5 — Instagram rich-message rendering

Canonical internal message types:
- text
- image
- video
- link
- button
- quick reply
- card/gallery where supported by the active Instagram API capability

Rule: flows author abstract messages; the Instagram adapter renders supported platform payloads. Unsupported capabilities fail visibly or downgrade only when explicitly safe.

## D6 — Instagram Follow Gate

Implement natively in BrightBean.

Flow state:
- FOLLOWING
- NOT_FOLLOWING
- UNKNOWN

Behavior:
- FOLLOWING -> continue protected branch/content.
- NOT_FOLLOWING -> follow prompt + retry/check action.
- UNKNOWN -> configurable fallback policy.

Fallback strategies:
- FAIL_OPEN
- FAIL_CLOSED
- ASK_AGAIN

Default for transient/unsupported status should be chosen explicitly and tested; an API failure must never be silently interpreted as NOT_FOLLOWING.

OpenReply may be consulted for behavioral/reference logic only.

## D7 — Visual Flow Builder integration

Required nodes/conditions:
- Instagram comment trigger.
- Public reply.
- Send message/media.
- Follow-status condition.
- Tag add/remove.
- Custom-field condition/action.
- Delay/wait.
- Branch/end.
- Human handoff.

Ship an opinionated template for:
`Comment -> Public Reply -> Opening DM -> Follow Check -> Content/Follow Prompt`

## D8 — Inbox, CRM and human handoff

Tasks:
- Stable contact identity based on workspace + channel connection + platform user id, never username alone.
- Conversation history.
- Tags/custom fields/source attribution.
- Pause automation on human takeover.
- Explicit resume semantics.
- Assignment and audit trail.

## D9 — Reliability, abuse resistance and production hardening

Tasks:
- Queue/retry/backoff.
- Meta rate-limit handling.
- Webhook/body limits.
- Worker crash recovery and exactly-once-effect/idempotent outcomes.
- Tenant quotas and noisy-neighbor controls.
- Metrics and alerts.
- Load/burst testing.
- Backup and restore exercises.
- Encryption-key rotation procedure.
- Deployment rollback/migration safety.

## D10 — Meta production readiness

Tasks:
- Business/app verification prerequisites as required.
- App Review evidence/demo.
- Privacy policy/terms/data deletion callback.
- Production callback/webhook domains and HTTPS.
- Permission minimization.
- Real-account end-to-end production-like acceptance.

## D11 — Facebook Page / Messenger parity

Only begins after D0-D10 Instagram acceptance is green.

---

# Final production acceptance — 55 controls

These are the final objectives unless explicitly changed by a later product decision.

1. Official Instagram API integration.
2. Official Meta OAuth/login authorization.
3. Organization/workspace multi-tenancy.
4. Multiple Instagram professional accounts per workspace.
5. Strong tenant scoping for all tenant data.
6. RBAC for account, automation and inbox administration.
7. Selected-post/content comment trigger.
8. Broad supported-post/content comment trigger.
9. Keyword comment trigger.
10. Any-comment trigger.
11. Public comment auto reply.
12. Comment-to-private-reply/DM.
13. DM text.
14. DM image.
15. DM video.
16. DM link.
17. DM button/quick action where supported.
18. Card/gallery abstraction where supported.
19. Instagram Follow Gate.
20. FOLLOWING/NOT_FOLLOWING/UNKNOWN semantics.
21. Visual flow builder integration.
22. CRM contacts.
23. Tags/custom fields.
24. Shared inbox.
25. Human takeover/pause/resume.
26. Queue-based asynchronous work.
27. Retry with exponential/backoff policy.
28. Meta rate-limit handling.
29. Idempotent webhook/event processing.
30. Idempotent outbound side effects.
31. OAuth state signing, expiry and anti-replay binding.
32. Token encryption at rest.
33. Secret/token log redaction.
34. Webhook HMAC/signature verification.
35. Request body-size limits before expensive processing/DB writes where possible.
36. CSRF protection for session-authenticated mutations.
37. CSP/security headers.
38. SSRF guard for user-influenced server-side URLs.
39. IDOR/cross-workspace fuzz tests.
40. Media MIME/content validation and quotas.
41. Authentication abuse/rate protection.
42. Non-root production containers.
43. Dependency vulnerability auditing.
44. Secret scanning/security lint in CI.
45. Meta App Review/production-readiness documentation.
46. Automated database backup policy.
47. Tested restore/disaster-recovery procedure with defined RPO/RTO.
48. Encryption-key rotation/re-encryption procedure.
49. Account disconnect/revocation cleanup semantics.
50. Data retention/export/deletion/anonymization governance.
51. Security/admin audit trail.
52. Deployment, migration and rollback procedure.
53. Meta API version/deprecation compatibility process.
54. Tenant quotas/abuse/noisy-neighbor controls.
55. Production SLO/incident monitoring for webhook, queue, DB, worker, token and Meta API failures.

## Acceptance rule

A checkbox is not proof. Every applicable item must point to one or more of:
- automated test,
- security test,
- integration test,
- load test,
- migration/rollback exercise,
- documented manual QA with evidence,
- operational runbook exercise.

P0 security and tenant-isolation failures block release.
