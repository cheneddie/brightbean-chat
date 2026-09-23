# Project Baseline — IG-first ManyChat Alternative

Status: **D0 baseline**
Repository: `cheneddie/brightbean-chat`
Upstream: `brightbeanxyz/brightbean-chat`
Baseline commit: `809b8ec775a3a25618835c712f8f20010794a4d4`
Baseline date: 2026-09-23
License: AGPL-3.0

## Fixed product decisions

1. BrightBean Chat is the implementation base.
2. Instagram is the first production target.
3. Facebook Page / Messenger is deferred until the Instagram production path passes acceptance.
4. OpenReply is a reference only for Follow Gate behavior; it is not a runtime dependency and its application architecture is not merged.
5. Only official Meta APIs and official OAuth are allowed. No password automation, browser automation, scraping, private APIs, or session-cookie impersonation.
6. Every change goes through a feature/development branch and pull request. `main` is not edited directly.
7. Existing BrightBean tenancy and security invariants are authoritative unless this project makes them stricter.
8. Cross-workspace access to tenant objects must return 404.
9. Platform credentials and account tokens must remain encrypted at rest and must never appear in browser responses or logs.
10. Webhook processing is asynchronous after verification/persistence: verify -> normalize -> dedupe -> persist -> 200 -> queue -> worker.
11. All event handling and outbound send paths must be idempotent.
12. Meta policy and messaging-window restrictions are product requirements, not bypass targets.

## Product objective

Provide a self-hosted, multi-tenant Instagram automation platform supporting:

- Meta/Instagram OAuth onboarding.
- Multiple Instagram professional accounts per workspace.
- Comment triggers for selected posts, all supported posts, keyword matching, and any-comment matching.
- Public comment replies.
- Comment-to-private-reply / DM flows.
- Text, image, video, link, button and supported rich-message rendering.
- Instagram Follow Gate using `is_user_follow_business` where Meta exposes the capability.
- Visual flow execution.
- CRM/contact tags and custom fields.
- Shared inbox and human handoff.
- Queueing, retries, rate control, auditability and analytics.

## Deferred scope

Until the Instagram path is production-ready:

- Facebook Page comment automation.
- Messenger automation.
- Facebook OAuth/Page selection UI beyond preserving upstream compatibility.

Deferred does **not** mean removed. New Instagram work must not unnecessarily break the existing provider abstraction.

## Upstream policy

The fork starts exactly at the upstream baseline commit above. Upstream updates are not merged automatically.

For every future upstream sync:

1. compare upstream against our current `main`;
2. review security-sensitive diffs;
3. run the complete test/security suite;
4. resolve conflicts on a dedicated `upstream/*` branch;
5. merge only through PR.

## Development sequence

`D0 -> D1 -> D2 -> D3 -> D4 -> D5 -> D6 -> D7 -> D8 -> D9 -> D10 -> D11`

No stage is considered complete until its acceptance criteria are recorded in the PR and its required automated/manual QA is green.

See:
- `docs/IG-FIRST-ROADMAP.md`
- `docs/QA-MATRIX.md`
- existing `docs/SECURITY-BASELINE.md`
