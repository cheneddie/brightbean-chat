"""Deployment operational snapshot severity contracts."""

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.channels.models import ChannelConnection, ConnectionStatus, WebhookEventLog, WebhookEventStatus
from apps.common.management.commands.ops_snapshot import collect_snapshot
from apps.common.platforms import Platform
from apps.queueing.models import QueueConsumerHeartbeat
from tests.support import Tenancy


def _heartbeat(source: str = "worker") -> QueueConsumerHeartbeat:
    return QueueConsumerHeartbeat.objects.create(
        key="queue",
        source=source,
        last_seen_at=timezone.now(),
    )


def _connection(tenancy: Tenancy, *, status: str = ConnectionStatus.ACTIVE) -> ChannelConnection:
    return ChannelConnection.objects.create(
        workspace=tenancy.workspace,
        platform=Platform.INSTAGRAM,
        display_name="@ops",
        external_id=f"ops-{status}",
        status=status,
    )


@pytest.mark.django_db
class TestOpsSnapshot:
    def test_fresh_consumer_and_no_incidents_is_ok(self) -> None:
        _heartbeat()
        snapshot = collect_snapshot()
        assert snapshot.status == "ok"
        assert snapshot.consumer_stale is False

    def test_missing_consumer_is_error_even_when_queue_is_empty(self) -> None:
        snapshot = collect_snapshot()
        assert snapshot.status == "error"
        assert snapshot.consumer_stale is True

    def test_recent_webhook_failures_crossing_threshold_are_degraded(
        self, tenancy: Tenancy, settings: Any
    ) -> None:
        _heartbeat()
        settings.OPS_WEBHOOK_FAILURE_WARN_COUNT = 1
        connection = _connection(tenancy)
        WebhookEventLog.objects.create(
            connection=connection,
            platform=Platform.INSTAGRAM,
            provider_event_id="failed-1",
            status=WebhookEventStatus.FAILED,
        )

        snapshot = collect_snapshot()
        assert snapshot.status == "degraded"
        assert snapshot.webhook_failed_window == 1

    def test_stuck_received_webhook_is_error(self, tenancy: Tenancy, settings: Any) -> None:
        _heartbeat()
        settings.OPS_WEBHOOK_STUCK_SECONDS = 60
        connection = _connection(tenancy)
        event = WebhookEventLog.objects.create(
            connection=connection,
            platform=Platform.INSTAGRAM,
            provider_event_id="stuck-1",
            status=WebhookEventStatus.RECEIVED,
        )
        WebhookEventLog.objects.filter(pk=event.pk).update(
            received_at=timezone.now() - timedelta(minutes=2)
        )

        snapshot = collect_snapshot()
        assert snapshot.status == "error"
        assert snapshot.webhook_stuck_received == 1

    def test_needs_reauth_is_degraded(self, tenancy: Tenancy) -> None:
        _heartbeat()
        _connection(tenancy, status=ConnectionStatus.NEEDS_REAUTH)
        snapshot = collect_snapshot()
        assert snapshot.status == "degraded"
        assert snapshot.connections_needing_reauth == 1

    def test_fail_on_error_returns_nonzero_for_monitoring(self) -> None:
        with pytest.raises(CommandError, match="Operational status is error"):
            call_command("ops_snapshot", "--json", "--fail-on-error", stdout=StringIO())
