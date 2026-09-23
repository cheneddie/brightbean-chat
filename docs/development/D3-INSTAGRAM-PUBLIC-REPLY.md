# D3 — Instagram Public Reply Acceptance

Status: **verified existing implementation; no production-code rewrite required**

Tracking issue: `#8`

## Product contract

For a claimed Instagram comment, public reply behavior must support:

- no public reply;
- one configured static reply;
- one randomly selected reply from a configured pool;
- best-effort public reply that does not suppress the private reply / DM;
- durable idempotency so worker/action replay cannot post a second visible comment;
- state independent from the private-reply allowance/state.

## Existing implementation verified

### Reply selection

`apps.channels.providers.instagram._public_reply_text` already implements:

- `mode=none` -> no public reply;
- `mode=static` -> first configured non-empty text;
- `mode=random` -> one configured non-empty text selected with a cryptographic random source.

### Durable public-reply claim

`apps.flows.triggers.guards.claim_public_reply` performs a conditional database update:

```text
public_reply_sent_at IS NULL
    -> set public_reply_sent_at
```

Only one worker can win the claim.

The claim is taken **before** calling Meta. This is deliberate: when the provider outcome is refused or ambiguous, retrying must not create a second visible comment on the customer's post.

### State separation

`HandledComment` stores separate fields:

- `public_reply_sent_at`
- `private_reply_sent_at`

Public reply and private reply / DM therefore have independent state machines.

### Failure behavior

`_send_public_reply` treats the public reply as best effort. A provider rejection is logged/scrubbed and the comment-to-DM path continues.

The private reply remains governed by its own seven-day window and one-private-reply guard.

### Loop prevention

Instagram inbound normalization drops comments whose author id equals the connected professional-account id. A public auto-reply arriving back as a comment webhook therefore cannot trigger itself recursively.

## Existing automated evidence

The Instagram comment suite already proves:

- `mode=none` sends no public reply while private reply still sends;
- random mode picks from the configured reply pool;
- a failed public reply does not cost the private reply;
- re-running the queued handler multiple times produces one public comment;
- even when Meta refuses the public reply, the public-reply claim remains consumed;
- duplicate webhook delivery cannot create duplicate public replies;
- own-account comments/public replies are dropped by inbound normalization.

## D3 conclusion

No second public-reply subsystem should be built.

The current implementation already meets the D3 product/security contract. D3 is accepted by preserving the existing responder + durable guard design and proving the full repository CI/security suite remains green.

## Required before D3 merge

- D0-D2 merged. ✅
- Full CI/security workflow green on this PR.
- No production behavior regressions in Instagram comment-to-DM tests.
