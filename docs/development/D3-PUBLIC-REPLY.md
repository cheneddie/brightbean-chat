# D3 — Instagram Public Reply Delivery State

Status: **implementation ready for CI**
Tracking issue: `#7`
Base: `main`

## Existing behavior retained

BrightBean already supports:
- no public reply;
- static public reply;
- random reply pool;
- queueing outside the webhook request;
- public reply independent from the private reply / DM;
- pre-provider-call durable claiming so worker retries cannot post a second visible comment.

That last property is intentionally preserved.

## Gap fixed

Before D3, `HandledComment.public_reply_sent_at` was written before the Meta API call. It therefore meant "attempt claimed", not "Meta confirmed success". A refused or unknown-outcome call could be reported as sent.

D3 separates the facts:

- `public_reply_claimed_at`: one-time pre-call idempotency claim;
- `public_reply_sent_at`: provider-confirmed success only;
- `public_reply_status`: `claimed | sent | failed | legacy_unknown`;
- `public_reply_error`: bounded machine-readable failure code only.

Provider prose is never persisted because provider error text may quote request material.

## Failure behavior

A failed public reply is **not retried**. This is intentional: a timeout can mean the provider accepted the visible comment but the response was lost. Retrying would risk duplicate public comments.

The private reply / DM remains independent and continues even when the public reply fails.

## Legacy migration

Historical non-null `public_reply_sent_at` values were pre-call claims, so D3 does not pretend they were confirmed sends.

Migration behavior:
- move the old timestamp to `public_reply_claimed_at`;
- clear `public_reply_sent_at`;
- set status to `legacy_unknown`.

## Database invariant

A check constraint enforces valid timestamp/status combinations:
- blank: no claim and no sent time;
- claimed/failed/legacy_unknown: claim exists, sent time absent;
- sent: claim and sent time both exist.

## Acceptance

- successful public reply -> claimed + sent + status sent;
- refused public reply -> claimed + no sent time + status failed + sanitized code;
- no public reply -> no public-reply state;
- rerunning a successful or failed action never posts another visible comment;
- failed public reply never blocks private reply / DM;
- full CI/security suite green.
