"""Operational liveness for the deployment-wide queue consumer."""

import logging
import time
from typing import Final

from django.db import DatabaseError
from django.utils import timezone

from apps.queueing.models import QueueConsumerHeartbeat

logger = logging.getLogger(__name__)

HEARTBEAT_KEY: Final[str] = "queue"
HEARTBEAT_WRITE_INTERVAL_SECONDS: Final[float] = 15.0
_last_touch_monotonic = 0.0


def touch_queue_consumer(source: str, *, force: bool = False) -> bool:
    """Record that a supported queue consumer is alive.

    The long-lived worker loops every second, so writes are throttled per
    process. CLI/HTTP tick entry points use ``force=True`` because they may run
    only once per minute or less often.

    Observability must not become a new failure mode for queue processing:
    database errors are logged and the caller continues. The protected status
    endpoint will then surface a missing/stale heartbeat.
    """
    global _last_touch_monotonic

    now_mono = time.monotonic()
    if not force and now_mono - _last_touch_monotonic < HEARTBEAT_WRITE_INTERVAL_SECONDS:
        return False

    try:
        QueueConsumerHeartbeat.objects.update_or_create(
            key=HEARTBEAT_KEY,
            defaults={"source": source[:32], "last_seen_at": timezone.now()},
        )
    except (DatabaseError, OSError) as exc:
        logger.warning("Could not update queue heartbeat (%s)", type(exc).__name__)
        return False

    _last_touch_monotonic = now_mono
    return True
