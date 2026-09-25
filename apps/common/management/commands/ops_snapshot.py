"""Deployment-wide operational snapshot for cron/monitoring agents."""

import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


@dataclass(frozen=True)
class OpsSnapshot:
    status: str
    queue_due_pending: int
    queue_oldest_overdue_seconds: int
    queue_running: int
    queue_stale_running: int
    queue_failed_last_24h: int
    consumer_source: str
    consumer_age_seconds: int | None
    consumer_stale: bool
    webhook_failed_window: int
    webhook_stuck_received: int
    connections_needing_reauth: int


def collect_snapshot(now: Any = None) -> OpsSnapshot:
    """Read operational signals without mutating or repairing any state."""
    now = now or timezone.now()
    action_model = apps.get_model("queueing", "ScheduledAction")
    heartbeat_model = apps.get_model("queueing", "QueueConsumerHeartbeat")
    connection_model = apps.get_model("channels", "ChannelConnection")
    event_model = apps.get_model("channels", "WebhookEventLog")

    actions = action_model._base_manager
    due = actions.filter(status="pending", run_at__lte=now)
    oldest_due = due.order_by("run_at").values_list("run_at", flat=True).first()
    oldest_due_age = max(0, int((now - oldest_due).total_seconds())) if oldest_due else 0
    running = actions.filter(status="running")

    zombie_after = max(1, int(getattr(settings, "QUEUE_ZOMBIE_AFTER_SECONDS", 10 * 60)))
    stale_running = running.filter(updated_at__lt=now - timedelta(seconds=zombie_after)).count()
    queue_failed = actions.filter(status="failed", updated_at__gte=now - timedelta(hours=24)).count()

    heartbeat = heartbeat_model._base_manager.filter(pk="queue").first()
    heartbeat_age = (
        max(0, int((now - heartbeat.last_seen_at).total_seconds()))
        if heartbeat is not None
        else None
    )
    heartbeat_max_age = max(
        1, int(getattr(settings, "QUEUE_CONSUMER_HEARTBEAT_MAX_AGE_SECONDS", 120))
    )
    heartbeat_stale = heartbeat_age is None or heartbeat_age > heartbeat_max_age

    failure_window = max(1, int(getattr(settings, "OPS_WEBHOOK_FAILURE_WINDOW_SECONDS", 900)))
    webhook_failed = event_model._base_manager.filter(
        status="failed",
        received_at__gte=now - timedelta(seconds=failure_window),
    ).count()
    stuck_seconds = max(1, int(getattr(settings, "OPS_WEBHOOK_STUCK_SECONDS", 300)))
    webhook_stuck = event_model._base_manager.filter(
        status="received",
        received_at__lt=now - timedelta(seconds=stuck_seconds),
    ).count()
    needs_reauth = connection_model._base_manager.filter(status="needs_reauth").count()

    due_warn = max(1, int(getattr(settings, "QUEUE_STATUS_OVERDUE_WARN_SECONDS", 60)))
    failure_warn = max(1, int(getattr(settings, "OPS_WEBHOOK_FAILURE_WARN_COUNT", 5)))

    if stale_running or heartbeat_stale or webhook_stuck:
        status = "error"
    elif oldest_due_age >= due_warn or queue_failed or webhook_failed >= failure_warn or needs_reauth:
        status = "degraded"
    else:
        status = "ok"

    return OpsSnapshot(
        status=status,
        queue_due_pending=due.count(),
        queue_oldest_overdue_seconds=oldest_due_age,
        queue_running=running.count(),
        queue_stale_running=stale_running,
        queue_failed_last_24h=queue_failed,
        consumer_source=heartbeat.source if heartbeat is not None else "",
        consumer_age_seconds=heartbeat_age,
        consumer_stale=heartbeat_stale,
        webhook_failed_window=webhook_failed,
        webhook_stuck_received=webhook_stuck,
        connections_needing_reauth=needs_reauth,
    )


class Command(BaseCommand):
    help = "Print a deployment-wide queue/channel operational snapshot without changing state."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--fail-on-error", action="store_true")
        parser.add_argument("--fail-on-degraded", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        snapshot = collect_snapshot()
        payload = asdict(snapshot)
        if options["as_json"]:
            self.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        else:
            self.stdout.write(f"Operational status: {snapshot.status}")
            for key, value in payload.items():
                if key != "status":
                    self.stdout.write(f"  {key}: {value}")

        if options["fail_on_degraded"] and snapshot.status != "ok":
            raise CommandError(f"Operational status is {snapshot.status}.")
        if options["fail_on_error"] and snapshot.status == "error":
            raise CommandError("Operational status is error.")
