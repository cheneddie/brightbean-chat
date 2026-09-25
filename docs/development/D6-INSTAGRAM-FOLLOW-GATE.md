# D6 — Instagram Follow Gate

Status: **implementation under CI validation**

Tracking issue: `#15`

## Current API boundary and verification status

BrightBean uses **Instagram API with Instagram Login** on `graph.instagram.com`. Meta's current official Instagram workspace confirms this login stack and the messaging permission set used by the project, including:
- `instagram_business_basic`
- `instagram_business_manage_messages`

D6 performs the best-effort profile lookup:

`GET https://graph.instagram.com/<IGSID>?fields=is_user_follow_business`

The field is used by current production integrations and OpenReply, but it is intentionally **not treated as a permanently guaranteed contract**. If Meta does not expose the field for this app/user, changes the surface, rate-limits the call, rejects the request, or the value is not a real boolean, BrightBean returns `UNKNOWN`.

The lookup requires a messaging-context Instagram-scoped user id. A public comment alone is not treated as proof that the profile lookup is available. This is why D6 is three-state and why an API failure can never silently become "not following".

## Three-state contract

`FollowStatus`:
- `following`
- `not_following`
- `unknown`

`unknown` covers:
- no usable IGSID / identity;
- no Instagram connection;
- inactive/re-auth-required connection;
- profile consent unavailable;
- Meta rate limiting;
- transport/API rejection;
- response missing `is_user_follow_business`.

## Follow Gate node

Node type: `instagram_follow_gate`

Handles:
- `follow:following`
- `follow:not_following`
- `follow:unknown`

Unknown policies:
- `fail_open` — route UNKNOWN to FOLLOWING (**default**);
- `fail_closed` — route UNKNOWN to NOT_FOLLOWING;
- `ask_again` — route UNKNOWN to the explicit UNKNOWN branch.

The node is intentionally `synchronous_safe = False`; a live Meta lookup never runs inside the inbound webhook inline budget.

## Intended flow

For comment-to-DM:

1. Comment trigger sends the one allowed opening private reply.
2. Opening DM contains a postback button such as "I'm following".
3. The existing button wait consumes the postback and continues.
4. `instagram_follow_gate` performs the live follow-status check.
5. FOLLOWING -> protected content.
6. NOT_FOLLOWING -> send follow prompt with postback button, then loop back to the gate.
7. UNKNOWN -> author-selected fallback policy.

No second worker or follow-specific queue is introduced. Existing BrightBean flow waits, postbacks, message compliance, retries and idempotency remain authoritative.

## Security / correctness

- Access token stays in the Authorization header through the existing Instagram `call()` helper.
- No token/profile response is stored in flow variables.
- No error path maps UNKNOWN to NOT_FOLLOWING implicitly.
- Meta auth error codes mark the connection `NEEDS_REAUTH` and return UNKNOWN.
- Wrong platform, inactive connection or missing identity performs no provider call.
- Adapter default for platforms without follower relationship support is UNKNOWN.

## D6 QA

Provider tests:
- Meta true -> FOLLOWING;
- Meta false -> NOT_FOLLOWING;
- missing or non-boolean field -> UNKNOWN;
- missing IGSID -> UNKNOWN without HTTP;
- 429 -> UNKNOWN, connection remains active;
- auth error -> UNKNOWN + NEEDS_REAUTH.

Flow tests:
- all three statuses route correctly;
- FAIL_OPEN / FAIL_CLOSED / ASK_AGAIN route UNKNOWN correctly;
- default policy is FAIL_OPEN;
- wrong platform / inactive connection / missing identity do not call provider;
- node is not synchronous-safe;
- schema and handle grammar expose all three follow handles.

## Production validation gate

Before enabling a **hard** follow gate for real customers, validate the connected Meta app with a real Instagram professional account:

1. Connect through Instagram Login with `instagram_business_basic` and `instagram_business_manage_messages`.
2. Use a person who has entered a real messaging context (for example, after the opening private reply and postback interaction).
3. Query one known follower and confirm the field returns boolean `true`.
4. Query one known non-follower and confirm the field returns boolean `false`.
5. Confirm a missing/unavailable field routes to `UNKNOWN`, not `NOT_FOLLOWING`.
6. Confirm an expired/revoked token marks the connection `NEEDS_REAUTH` and still returns `UNKNOWN`.
7. Confirm `FAIL_OPEN`, `FAIL_CLOSED`, and `ASK_AGAIN` behave as configured in the real flow.

If the Meta app does not expose a reliable boolean for the field, the feature remains safe because the runtime returns `UNKNOWN`; however, do not market or enable a hard verified-follow gate until steps 3 and 4 have been proven on that production app.

This is a deployment acceptance gate, not a reason to reinterpret an unavailable API response as "not following".

## D7 boundary

D6 implements the runtime primitive and schema. D7 will focus on visual-flow integration/templates and broader builder UX. D6 does not add a second follow-specific orchestration system.
