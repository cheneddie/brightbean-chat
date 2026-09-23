# D1 — Instagram OAuth & Multi-account Acceptance

Status: **implementation complete for current D1 scope; D0 merged; full CI validation pending on this branch**

Base: `main`
Tracking issue: `#5`

## Existing upstream capabilities verified

- Instagram API with Instagram Login.
- Official scopes:
  - `instagram_business_basic`
  - `instagram_business_manage_messages`
  - `instagram_business_manage_comments`
- Signed OAuth state bound to workspace and user.
- 10-minute state expiry.
- Short-lived -> long-lived token exchange.
- Encrypted credential storage.
- Expiry tracking and refresh before expiry.
- Refresh failure -> `NEEDS_REAUTH` + notification.
- Deployment-wide uniqueness of `(platform, external_id)` prevents one IG account being silently stolen by another workspace.
- Workspace-scoped reconnect path.
- Shared Instagram webhook endpoint resolves inbound deliveries by professional-account id.
- Meta webhook field subscription is app-level dashboard configuration; it is not a per-ChannelConnection API lifecycle in this integration.

## D1 changes in this branch

### 1. OAuth state replay protection

Added:
- random nonce in signed state;
- nonce bound to initiating Django session;
- bounded pending-state list;
- one-time state consumption before Meta code exchange;
- shared database-cache claim to close concurrent callback replay across workers.

Acceptance:
- tampered/expired state rejected;
- wrong user/workspace rejected;
- state from another browser session rejected;
- same valid callback state accepted at most once.

### 2. Multi-account OAuth acceptance

Added test proving one workspace can connect two distinct Instagram professional accounts without overwriting the first.

### 3. Multi-account post picker

Previous behavior silently selected the oldest active Instagram connection.

New behavior:
- the trigger form sends its selected `channel_connection` to the Instagram post picker;
- selected connection is resolved inside the current workspace;
- a foreign-workspace id returns 404;
- a non-Instagram connection returns a safe prompt;
- an inactive Instagram connection asks for reconnect;
- when multiple active Instagram accounts exist and no account is selected, the UI refuses to guess;
- when exactly one active Instagram account exists, existing single-account convenience remains.

### 4. Inactive connection send boundary

Added a final provider-call guard:
- only `ACTIVE` channel connections can send;
- `NEEDS_REAUTH` / `DISABLED` sends fail with machine-readable `connection_inactive`;
- the same guard applies to inline sends and queued send retries.

This is intentionally platform-independent: a revoked credential must not keep retrying just because one caller forgot to check status.

## Disconnect / revocation semantics

Current local deletion already cascades connection-owned identities, conversations and bound triggers. Queued handlers re-resolve tenant-scoped ids, so a deleted connection cannot be recovered from an untrusted queued payload.

The new inactive-connection boundary covers the more important non-deletion state: a row that still exists but is disabled or needs reauthorization cannot reach the provider.

No Instagram-specific remote unsubscribe endpoint is implemented unless an official Instagram API with Instagram Login endpoint is verified. A WhatsApp `subscribed_apps` endpoint must not be copied into Instagram by analogy.

## QA added

- OAuth state single-use.
- OAuth state session binding.
- Multiple Instagram accounts in one workspace.
- Selected account controls post picker.
- Multiple accounts require explicit picker selection.
- Foreign-workspace picker id -> 404.
- Wrong-platform picker selection -> safe prompt.
- Inactive IG picker -> reconnect prompt.
- Trigger form propagates selected channel to picker.
- Inactive connection -> no provider call.
- Queued retry stops after connection moves to `NEEDS_REAUTH`.

## Required before D1 merge

- D0 PR #1 merged. ✅
- Fork GitHub Actions actually creates CI runs.
- Full upstream CI/security suite green.
- Focused Instagram OAuth/multi-account tests green.
- No regression in messaging retry/idempotency tests.
- Review final diff for secret/token logging.
- Meta sandbox/manual OAuth round-trip once deployment credentials are available.
