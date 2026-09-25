# D10 — Meta Production Readiness

Status: **source implementation in progress; no executable validation in this pass**

Tracking issue: `#22`

## Already satisfied on main

- Instagram Login OAuth with signed + browser-session-bound state;
- encrypted long-lived access tokens and proactive refresh;
- only the three IG-first scopes used by the product;
- raw-body webhook HMAC verification before JSON processing;
- public HTTPS OAuth/webhook deployment guidance;
- Advanced Access / App Review / Business Verification documentation;
- channel disconnect lifecycle;
- contact-level GDPR erasure for CRM subjects.

## D10-A — Meta account lifecycle callbacks

Branch `dev/D10-meta-production-readiness` adds:

- `POST /meta/instagram/deauthorize/`;
- `POST /meta/instagram/data-deletion/`;
- `GET /meta/instagram/data-deletion/status/<confirmation_code>/`.

Security contract:

- callback body is capped at 16 KiB before form parsing;
- `signed_request` is strict Base64URL + HMAC-SHA256 verified;
- only a complete **deployment-level** Instagram Meta app secret may verify the generic callbacks;
- OAuth stores the code-exchange identity separately as `ChannelConnection.meta_app_scoped_user_id`;
- `external_id` remains the professional-account/webhook-routing id;
- lifecycle callbacks resolve only by `meta_app_scoped_user_id` and never fall back to `external_id`;
- one lifecycle identity may delete more than one connected professional account;
- deletion is idempotent (already absent => completed with zero rows deleted);
- no plaintext signed request, Meta user id or confirmation code is stored in the receipt;
- the receipt stores only confirmation HMAC, platform, deleted connection count and timestamps;
- wrong signature cannot delete a connection;
- missing deployment app configuration makes the callback 404.

Deleting matched channel connections intentionally reuses existing FK cascades for
channel-owned conversations, identities and trigger bindings. It does **not**
hard-delete every CRM Contact in the workspace: those contacts are third parties
who messaged the connected business, not the connected business account itself.

### Known boundary

A deployment that stores different Meta App credentials per Organization cannot
use one generic callback URL safely because signature verification needs the app
secret before the callback identifies a workspace. That deployment mode needs a
separate organization-scoped callback URL per Meta App and remains D10 work.

## D10-B — App Review legal/readiness guard

New production settings:

- `PRIVACY_POLICY_URL`
- `TERMS_OF_SERVICE_URL`
- `DATA_DELETION_INSTRUCTIONS_URL`

When `DEBUG=False` and a complete deployment-level Instagram Meta App is
configured, Django security checks require all three to be public-style HTTPS
URLs. The software validates configuration, not legal sufficiency or remote
availability.

## Still required before D10 can be called production-ready

- run the new callback/migration/system-check tests against the private repo + Postgres;
- verify the Meta dashboard accepts both lifecycle callback URLs;
- publish operator-reviewed Privacy Policy / Terms / Data Deletion Instructions;
- submit Advanced Access for exactly the three required scopes;
- record reviewer screencast/evidence;
- pass Business Verification if Meta requires it for the app;
- complete a real-account E2E test with an Instagram professional account whose
  owner is not an app developer/tester;
- test deauthorize + data deletion against Meta's actual callbacks;
- add organization-scoped callback support before supporting bring-your-own Meta
  Apps per organization.

## Validation boundary

Per user instruction, GitHub Actions are not used for this development pass.
Source-level tests are added, but no merge should occur until they are executed
successfully in a suitable local/private-repo environment.
