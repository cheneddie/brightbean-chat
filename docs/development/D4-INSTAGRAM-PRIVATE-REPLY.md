# D4 — Instagram Comment Private Reply Boundary

Status: **implementation under CI validation**

Tracking issue: `#10`

## Problem fixed

A public Instagram comment is not an inbound DM. The prior implementation created an identity and opened the ordinary messaging window for a claimed comment, then treated the one allowed private reply as if it had opened a normal thread. That could allow later flow sends before the person actually sent a message.

## New contract

- An unclaimed public comment creates no contact or DM state.
- A claimed comment may create the contact/identity and consent audit needed to route the automation.
- A claimed comment does **not** set `last_inbound_at` or `window_expires_at`.
- The durable `HandledComment` row is bound to `FlowExecution.private_reply_claim`.
- Flow authors cannot forge that authority through variables.
- The send chokepoint revalidates the claim against workspace, connection, commenter, contact, deadline and spent state.
- Only a platform whose capability declares `comment_private_reply=True` may receive the one-time compliance grant.
- Instagram revalidates the exact claim immediately before the provider call.
- A private reply must render as exactly one provider message. Multi-part opening content fails before any provider call.
- After a successful private reply, later automation remains outside the ordinary messaging window until the person genuinely replies.
- A real inbound DM opens the ordinary window and normal follow-up messages then use the platform user id.
- Retry reconstructs the claim id from the persisted message body and revalidates it; stale or spent claims do not bypass compliance.

## Security invariants

- Cross-workspace or cross-connection claims are rejected when the execution is created and again at the send boundary.
- Model-level save validation rejects a mismatched claim even if code bypasses `start_flow()`.
- An invalid claim id is stripped before ordinary compliance runs.
- Provider fallback from a lost private-reply claim to an ordinary DM is forbidden.
- Opt-out, opt-in, active connection, plan, rate-limit and idempotency controls remain active for private replies.

## QA

Added/updated acceptance coverage for:

- comment -> public reply + one private reply;
- claimed comment does not open the normal DM window;
- second flow send before a real user DM is refused;
- multi-part opening content is refused before provider send;
- after the person sends a DM, ordinary follow-up sends work;
- private-reply compliance does not bypass opt-out / no-consent / no-connection;
- the private-reply flag grants no escape on platforms without the capability.

## Merge gate

- models/migrations agree;
- Ruff green;
- mypy/TypeScript green;
- pytest green;
- gitleaks green;
- dependency audits/front-end deterministic build green;
- Docker production smoke green.
