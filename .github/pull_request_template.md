## Summary

What problem does this PR solve?

## Development stage / acceptance mapping

- Stage: D__
- Final acceptance controls: #

## Changes

- 

## Security impact

- [ ] Tenant-scoped data access reviewed
- [ ] Cross-workspace/IDOR tests added or not applicable
- [ ] No new plaintext credentials/tokens
- [ ] Log/error redaction reviewed
- [ ] CSRF/session implications reviewed
- [ ] Webhook signature/body-limit implications reviewed
- [ ] SSRF implications reviewed
- [ ] User/platform content treated as untrusted
- [ ] No new secret committed

Explain any applicable item:

## Idempotency / retries

Could this code run more than once because of webhook retries, queue retries or worker recovery? If yes, explain the idempotency key/invariant.

## Meta/platform policy impact

Permissions, messaging-window behavior, rate limits or provider constraints changed:

## Database / migrations

- [ ] No migration
- [ ] Migration included and tested
- Rollback/compatibility notes:

## Tests / QA

Commands/checks run:

- 

Relevant QA IDs from `docs/QA-MATRIX.md`:

- 

## Rollback

How to safely revert this change:

## Known limitations / follow-ups

- 
