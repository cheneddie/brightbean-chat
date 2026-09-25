# Production Incident Runbook

This runbook is deliberately vendor-neutral. BrightBean can report its own
operational state; the operator chooses whether cron, systemd, an uptime service,
Sentry, Prometheus exporters, or another monitoring system calls the checks.

## Primary probes

### Web/database liveness

```text
GET /healthz
```

HTTP 503 means the web process cannot complete its database round-trip.

### Queue liveness

When `TICK_TOKEN` is configured:

```text
GET /internal/queue-status?token=<TICK_TOKEN>
```

This is read-only. It never drains or repairs the queue.

### Deployment snapshot

From the host/container:

```bash
python manage.py ops_snapshot --json
# compose shortcut
make prod-ops ARGS="--json"
```

For a monitor that should page only on hard errors:

```bash
python manage.py ops_snapshot --json --fail-on-error
```

To make degraded state non-zero as well:

```bash
python manage.py ops_snapshot --json --fail-on-degraded
```

## Severity contract

| Signal | Default threshold | Severity | First response |
|---|---:|---|---|
| Database health | `/healthz` returns 503 | error | Check Postgres reachability, credentials, saturation, disk and recent deploy/migration. |
| Queue consumer heartbeat | missing or older than 120s | error | Check `worker` process or tick scheduler. Do not enqueue more work as a “test”. |
| Stale running queue work | older than zombie threshold (10m) | error | Check worker crashes/timeouts and housekeeping. Preserve the rows for diagnosis. |
| Webhook stuck in `received` | older than 300s | error | Inspect webhook processor logs/database health. Do not delete the event log to make the count disappear. |
| Oldest due queue item | 60s+ overdue | degraded | Check worker throughput, provider throttling and backlog growth. |
| Terminal queue failures | any in previous 24h | degraded | Inspect action type + scrubbed `last_error`; determine transient vs permanent failure. |
| Webhook failures | 5+ within 15m | degraded | Check provider payload/signature changes and application exceptions. |
| Connection `needs_reauth` | any | degraded | Reconnect the affected channel; token refresh has already declared it unusable. |

Thresholds are deployment settings:

```text
QUEUE_STATUS_OVERDUE_WARN_SECONDS
QUEUE_CONSUMER_HEARTBEAT_MAX_AGE_SECONDS
OPS_WEBHOOK_STUCK_SECONDS
OPS_WEBHOOK_FAILURE_WINDOW_SECONDS
OPS_WEBHOOK_FAILURE_WARN_COUNT
```

## Triage order

1. **Check `/healthz`.** If the database is unavailable, every higher-level
   symptom is secondary.
2. **Check `ops_snapshot --json`.** Record the output before changing state.
3. **Check queue consumer freshness.** A healthy web process with no worker is a
   partial outage, not a healthy deployment.
4. **Check recent deploy/migration.** Run
   `python manage.py migration_readiness --require-clean`.
5. **Inspect logs by the failing subsystem.** Useful stable messages include:
   - `Queue action failed`
   - `could not be finalised; leaving it to zombie recovery`
   - `needs reconnecting`
   - `Instagram token refresh failed`
6. **Fix the cause, then observe recovery.** Do not “clean” failed/stale rows
   before understanding them; they are the evidence needed to explain the
   incident.

## Queue incidents

### Consumer stale, queue empty

The web app is alive but no supported queue consumer has updated the deployment
heartbeat. Check:

- Compose: `docker compose -f docker-compose.prod.yml ps worker`
- Worker logs: `docker compose -f docker-compose.prod.yml logs worker`
- Tick mode: scheduler interval and last successful request.

A worker heartbeat is throttled to 15 seconds. Tick mode writes on every run.
Set `QUEUE_CONSUMER_HEARTBEAT_MAX_AGE_SECONDS` comfortably above the scheduler
interval when not using a long-lived worker.

### Backlog growing

Do not first increase provider send rates. Determine whether the backlog is:

- CPU/database bound;
- blocked by provider 429 / Retry-After;
- dominated by one failing action type;
- caused by a dead/slow worker.

The queue supports multiple workers through `FOR UPDATE SKIP LOCKED`, but
provider rate limits remain authoritative. Scaling workers does not make a Meta
rate limit disappear.

### Stale running rows

A stale running row means work was claimed and then stopped making progress long
enough to cross zombie recovery's threshold. Preserve it and inspect logs around
its `updated_at`. Housekeeping normally returns abandoned work to pending.

## Webhook incidents

### Failed events rising

A few isolated failures are degraded rather than a process outage. A burst may
mean:

- provider payload/schema change;
- application exception;
- signature/app-secret mismatch after deployment;
- connection/token state changed.

Use the stored WebhookEventLog status and application logs together. The raw
payload is attacker-controlled data; do not paste secrets/tokens into tickets.

### Events stuck in received

A WebhookEventLog that remains `received` beyond the threshold is stronger
evidence than a failed row: processing never reached a terminal classification.
Treat it as a hard error and inspect database transactions/process crashes.

## Credential incidents

### `needs_reauth`

The platform rejected credentials strongly enough that automatic refresh marked
the connection unusable. Reconnect through Settings → Channels. Do not edit
encrypted credential columns in SQL.

### Suspected SECRET_KEY / encryption-key compromise

Follow the key-rotation section in `docs/self-hosting.md`. For a compromised
key, do not keep the compromised generation in fallback merely to preserve old
links.

## Deploy / migration incidents

Before migration:

```bash
make prod-migration-check
```

After migration:

```bash
make prod-migration-verify
```

A risky migration is not automatically wrong. The preflight requires an explicit
`--allow-risky` acknowledgement because rollback is an operator decision backed
by a verified database backup.

If the new app must be rolled back, decide database rollback separately. Do not
blindly target an older Django migration because the operation reports itself as
reversible; data deletion/rewrites may still require restoring the verified
backup.

## Incident close criteria

Close an incident only after:

- `/healthz` is healthy;
- `ops_snapshot --json` is `ok` or every remaining `degraded` item has an
  explicit owner/accepted explanation;
- queue backlog is shrinking or empty;
- no stale running rows remain;
- webhook failure/stuck counts have returned below threshold;
- affected `needs_reauth` connections are either reconnected or deliberately
  disabled;
- the cause, remediation and any threshold/runbook change are recorded.
