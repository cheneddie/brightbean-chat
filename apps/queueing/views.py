"""``/internal/tick`` — an HTTP drain for hosts with no long-lived worker.

SPEC §15: "``/internal/tick?token=`` HTTP wrapper (constant-time token compare,
env ``TICK_TOKEN``) for external pingers. Behavior identical to one worker
cycle; safe to run concurrently with a worker."

The concurrency safety is not a claim made here — it is the ``FOR UPDATE SKIP
LOCKED`` claim in ``apps.queueing.worker``. This view calls the same
``drain()`` every worker calls; nothing about being reached over HTTP changes
what a claim does.

**Why a bare token rather than the shared signer.** ``apps/common/signing.py``
lists this route among its consumers, and this is a deliberate, documented
divergence. A signed token buys expiry and purpose-scoping; the caller here is a
third-party pinger (cron-job.org, Uptime Robot, a Kubernetes CronJob) that
stores one URL in its configuration and calls it forever, so the token would
have to be minted with ``max_age=None`` — at which point it is a bare token with
extra steps, and rotating it means re-minting and re-pasting rather than
changing one environment variable. The properties that actually matter are kept:
constant-time comparison, and a bare 404 for every failure including a missing
configuration (SECURITY-BASELINE §4).
"""

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt

from apps.queueing.health import HEARTBEAT_KEY, touch_queue_consumer
from apps.queueing.housekeeping import ZOMBIE_AFTER, ensure_housekeeping_scheduled
from apps.queueing.models import ActionStatus, QueueConsumerHeartbeat, ScheduledAction
from apps.queueing.worker import drain

logger = logging.getLogger(__name__)

#: Deliberately shorter than ``manage.py tick``'s 55 s.
#:
#: Gunicorn runs at its default 30 s worker timeout in the Dockerfile and the
#: compose stack alike, so a request that worked for 55 s would be killed
#: mid-batch — the rows would sit in ``running`` until zombie recovery ten
#: minutes later, and
#: the operator would see a 502 from a tick that was working perfectly well.
#: The budget is checked between batches, so the real ceiling is this plus one
#: batch.
MAX_SECONDS = 20

#: Smaller than the worker's 50, because this budget is enforced by gunicorn.
#:
#: drain() checks the deadline between actions, so the overrun is bounded by
#: one slow handler rather than a whole batch — but the claim itself is still
#: work this request has taken responsibility for, and a smaller claim means
#: less to hand back when the budget runs out. A deployment whose handlers are
#: slow enough for this to matter wants a real worker process; this endpoint is
#: the fallback for hosts that cannot run one.
BATCH_SIZE = 10


def _require_tick_token(request: HttpRequest) -> None:
    """Authenticate a deployment-level queue operations endpoint."""
    expected = (getattr(settings, "TICK_TOKEN", "") or "").strip()
    if not expected:
        raise Http404
    provided = request.GET.get("token", "")
    if not constant_time_compare(provided, expected):
        logger.warning("Rejected internal queue endpoint: bad or missing token")
        raise Http404


@csrf_exempt  # Token-authenticated, not session-authenticated: an external pinger has no CSRF cookie.
def internal_tick(request: HttpRequest) -> HttpResponse:
    """Drain the queue once. 404 unless the caller presents ``TICK_TOKEN``.

    The method check is inside the body, *after* the token check, rather than in
    a ``@require_http_methods`` decorator. A decorator runs first, so an
    unauthenticated ``HEAD`` or ``DELETE`` would answer ``405`` with an
    ``Allow`` header while every unmounted path answers ``404`` — which
    confirms this route exists, and with it that the deployment runs this
    queue, to a caller holding no token at all. That is the same reasoning
    CONTRIBUTING.md gives for stacking ``@require_POST`` innermost on the
    tenant views: the check that reveals nothing has to run before the one that
    reveals something.
    """
    _require_tick_token(request)

    # Only now, with the caller proven, is it safe to say something specific.
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])

    started = time.monotonic()
    ensure_housekeeping_scheduled()
    touch_queue_consumer("http_tick", force=True)
    result = drain(batch_size=BATCH_SIZE, max_seconds=MAX_SECONDS)
    touch_queue_consumer("http_tick", force=True)
    duration_ms = int((time.monotonic() - started) * 1000)

    logger.info(
        "Tick drained claimed=%s done=%s failed=%s retried=%s stranded=%s duration_ms=%s",
        result.claimed,
        result.done,
        result.failed,
        result.retried,
        result.stranded,
        duration_ms,
    )
    return JsonResponse(
        {
            "claimed": result.claimed,
            "done": result.done,
            "failed": result.failed,
            "retried": result.retried,
            "stranded": result.stranded,
            "duration_ms": duration_ms,
        }
    )


@csrf_exempt
def internal_queue_status(request: HttpRequest) -> HttpResponse:
    """Read-only deployment queue health for external monitoring.

    This endpoint never drains, retries, repairs or bootstraps the queue. A
    health check that mutates what it observes can hide the outage it should
    report.
    """
    _require_tick_token(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    now = timezone.now()
    actions = ScheduledAction.objects.unscoped()
    due = actions.filter(status=ActionStatus.PENDING, run_at__lte=now)
    oldest_due = due.order_by("run_at").values_list("run_at", flat=True).first()
    overdue_seconds = max(0, int((now - oldest_due).total_seconds())) if oldest_due is not None else 0
    running = actions.filter(status=ActionStatus.RUNNING)
    stale_running = running.filter(updated_at__lt=now - ZOMBIE_AFTER).count()
    failed_recent = actions.filter(
        status=ActionStatus.FAILED,
        updated_at__gte=now - timedelta(hours=24),
    ).count()
    warn_after = max(1, int(getattr(settings, "QUEUE_STATUS_OVERDUE_WARN_SECONDS", 60)))
    heartbeat_max_age = max(1, int(getattr(settings, "QUEUE_CONSUMER_HEARTBEAT_MAX_AGE_SECONDS", 120)))
    heartbeat = QueueConsumerHeartbeat.objects.filter(key=HEARTBEAT_KEY).first()
    heartbeat_age = (
        max(0, int((now - heartbeat.last_seen_at).total_seconds())) if heartbeat is not None else None
    )
    heartbeat_stale = heartbeat_age is None or heartbeat_age > heartbeat_max_age

    if stale_running or heartbeat_stale:
        overall = "error"
        http_status = 503
    elif overdue_seconds >= warn_after or failed_recent:
        overall = "degraded"
        http_status = 200
    else:
        overall = "ok"
        http_status = 200

    return JsonResponse(
        {
            "status": overall,
            "consumer": {
                "source": heartbeat.source if heartbeat is not None else "",
                "age_seconds": heartbeat_age,
                "max_age_seconds": heartbeat_max_age,
                "stale": heartbeat_stale,
            },
            "queue": {
                "due_pending": due.count(),
                "running": running.count(),
                "stale_running": stale_running,
                "failed_last_24h": failed_recent,
                "oldest_overdue_seconds": overdue_seconds,
                "overdue_warn_after_seconds": warn_after,
                "zombie_after_seconds": int(ZOMBIE_AFTER.total_seconds()),
            },
        },
        status=http_status,
    )
