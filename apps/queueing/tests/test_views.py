"""``/internal/tick`` — the token gate and the drain behind it."""

from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.queueing.health import HEARTBEAT_KEY, touch_queue_consumer
from apps.queueing.models import ActionStatus, QueueConsumerHeartbeat, ScheduledAction
from apps.queueing.tests.support import make_action, temporary_handler
from tests.support import Tenancy

TOKEN = "tick-token-for-tests"
PROBE = "view_probe"


def _noop(payload: dict[str, Any], action: ScheduledAction) -> None:
    return None


@pytest.fixture
def url() -> str:
    return reverse("internal_tick")


@pytest.fixture
def status_url() -> str:
    return reverse("internal_queue_status")


@pytest.mark.django_db
class TestTokenGate:
    def test_404s_when_no_token_is_configured(self, client: Client, url: str, settings: Any) -> None:
        """An unconfigured deployment must not advertise that the route exists."""
        settings.TICK_TOKEN = ""
        assert client.get(url).status_code == 404
        assert client.get(f"{url}?token=anything").status_code == 404

    def test_404s_on_a_wrong_token(self, client: Client, url: str, settings: Any) -> None:
        settings.TICK_TOKEN = TOKEN
        response = client.get(f"{url}?token=wrong")

        assert response.status_code == 404
        # Bare 404, no hint about what was wrong (SECURITY-BASELINE §4).
        assert TOKEN not in response.content.decode()

    def test_404s_on_a_missing_token(self, client: Client, url: str, settings: Any) -> None:
        settings.TICK_TOKEN = TOKEN
        assert client.get(url).status_code == 404

    def test_a_prefix_of_the_token_is_not_enough(self, client: Client, url: str, settings: Any) -> None:
        settings.TICK_TOKEN = TOKEN
        assert client.get(f"{url}?token={TOKEN[:-1]}").status_code == 404

    def test_whitespace_around_a_configured_token_is_ignored(self, client: Client, url: str, settings: Any) -> None:
        """A trailing newline in an env var should not silently disable the route."""
        settings.TICK_TOKEN = f"  {TOKEN}\n"
        assert client.get(f"{url}?token={TOKEN}").status_code == 200

    def test_the_comparison_is_constant_time(self, client: Client, url: str, settings: Any, monkeypatch: Any) -> None:
        """Pin the helper, not a timing measurement — a timing test is a flake generator."""
        from apps.queueing import views

        calls: list[tuple[str, str]] = []
        real = views.constant_time_compare

        def spy(left: str, right: str) -> bool:
            calls.append((left, right))
            return real(left, right)

        monkeypatch.setattr(views, "constant_time_compare", spy)
        settings.TICK_TOKEN = TOKEN
        client.get(f"{url}?token=wrong")

        assert calls == [("wrong", TOKEN)]

    @pytest.mark.parametrize("method", ["delete", "put", "patch", "head", "options"])
    def test_an_unauthenticated_caller_learns_nothing_from_the_method(
        self, client: Client, url: str, settings: Any, method: str
    ) -> None:
        """A 405 here would be a route-existence oracle.

        The method check has to run *after* the token check, or an
        unauthenticated HEAD answers 405 with an Allow header while every
        unmounted path answers 404 — which tells a caller holding no token that
        this route exists, and so that the deployment runs this queue.
        Same reasoning as CONTRIBUTING.md's rule for stacking @require_POST
        innermost on the tenant views.
        """
        settings.TICK_TOKEN = TOKEN
        bad_token = getattr(client, method)(f"{url}?token=wrong")
        no_token = getattr(client, method)(url)

        assert bad_token.status_code == 404
        assert no_token.status_code == 404
        assert "Allow" not in bad_token

    @pytest.mark.parametrize("method", ["get", "post", "delete", "head"])
    def test_an_unconfigured_deployment_answers_404_whatever_the_method(
        self, client: Client, url: str, settings: Any, method: str
    ) -> None:
        settings.TICK_TOKEN = ""
        assert getattr(client, method)(url).status_code == 404

    def test_the_token_never_reaches_the_logs(self, client: Client, url: str, settings: Any, caplog: Any) -> None:
        """It rides in a query string, and request paths are logged (SECURITY-BASELINE §5)."""
        settings.TICK_TOKEN = TOKEN
        with caplog.at_level("DEBUG"):
            client.get(f"{url}?token={TOKEN}")

        assert TOKEN not in caplog.text


@pytest.mark.django_db
class TestDrain:
    def test_a_good_token_drains_the_queue(self, client: Client, url: str, settings: Any, tenancy: Tenancy) -> None:
        settings.TICK_TOKEN = TOKEN
        make_action(tenancy.workspace, type=PROBE)
        make_action(tenancy.workspace, type=PROBE)

        with temporary_handler(PROBE, _noop):
            response = client.get(f"{url}?token={TOKEN}")

        assert response.status_code == 200
        body = response.json()
        assert body["claimed"] == 2
        assert body["done"] == 2
        assert body["failed"] == 0
        assert body["stranded"] == 0
        assert "duration_ms" in body
        assert ScheduledAction.objects.for_workspace(tenancy.workspace).filter(status=ActionStatus.DONE).count() == 2
        heartbeat = QueueConsumerHeartbeat.objects.get(key=HEARTBEAT_KEY)
        assert heartbeat.source == "http_tick"

    def test_post_works_too(self, client: Client, url: str, settings: Any) -> None:
        """External pingers use both verbs, and POST carries no CSRF cookie."""
        settings.TICK_TOKEN = TOKEN
        assert client.post(f"{url}?token={TOKEN}").status_code == 200

    def test_other_methods_are_refused_once_the_caller_is_proven(self, client: Client, url: str, settings: Any) -> None:
        settings.TICK_TOKEN = TOKEN
        response = client.delete(f"{url}?token={TOKEN}")

        assert response.status_code == 405
        assert response["Allow"] == "GET, POST"

    def test_the_http_path_claims_a_smaller_batch_than_the_worker(self) -> None:
        """gunicorn's 30s timeout is a real budget, and drain() takes
        responsibility for every row it claims."""
        from apps.queueing import views
        from apps.queueing.worker import DEFAULT_BATCH_SIZE

        assert views.BATCH_SIZE < DEFAULT_BATCH_SIZE
        assert views.MAX_SECONDS < 30

    def test_it_bootstraps_the_housekeeping_chain(self, client: Client, url: str, settings: Any) -> None:
        """A cron-only host never runs the worker, so the tick has to do this."""
        settings.TICK_TOKEN = TOKEN
        client.get(f"{url}?token={TOKEN}")

        assert ScheduledAction.objects.unscoped().filter(type="housekeeping").exists()

    def test_no_authentication_is_required_beyond_the_token(self, client: Client, url: str, settings: Any) -> None:
        """The caller is a cron service, not a signed-in user."""
        settings.TICK_TOKEN = TOKEN
        response = client.get(f"{url}?token={TOKEN}")

        assert response.status_code == 200
        assert "login" not in response["Content-Type"]


@pytest.mark.django_db
class TestQueueStatus:
    def test_missing_consumer_heartbeat_is_a_hard_error(self, client: Client, status_url: str, settings: Any) -> None:
        settings.TICK_TOKEN = TOKEN
        response = client.get(f"{status_url}?token={TOKEN}")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "error"
        assert body["consumer"]["source"] == ""
        assert body["consumer"]["age_seconds"] is None
        assert body["consumer"]["stale"] is True

    def test_stale_consumer_heartbeat_is_a_hard_error(self, client: Client, status_url: str, settings: Any) -> None:
        settings.TICK_TOKEN = TOKEN
        settings.QUEUE_CONSUMER_HEARTBEAT_MAX_AGE_SECONDS = 120
        touch_queue_consumer("worker", force=True)
        QueueConsumerHeartbeat.objects.filter(key=HEARTBEAT_KEY).update(
            last_seen_at=timezone.now() - timedelta(minutes=3)
        )

        response = client.get(f"{status_url}?token={TOKEN}")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "error"
        assert body["consumer"]["source"] == "worker"
        assert body["consumer"]["age_seconds"] >= 120
        assert body["consumer"]["stale"] is True

    def test_it_is_hidden_without_the_shared_operations_token(
        self, client: Client, status_url: str, settings: Any
    ) -> None:
        settings.TICK_TOKEN = TOKEN
        assert client.get(status_url).status_code == 404
        assert client.get(f"{status_url}?token=wrong").status_code == 404

    def test_it_is_read_only_and_reports_a_healthy_empty_queue(
        self, client: Client, status_url: str, settings: Any
    ) -> None:
        settings.TICK_TOKEN = TOKEN
        settings.QUEUE_CONSUMER_HEARTBEAT_MAX_AGE_SECONDS = 120
        touch_queue_consumer("worker", force=True)
        before = ScheduledAction.objects.unscoped().count()

        response = client.get(f"{status_url}?token={TOKEN}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["consumer"]["source"] == "worker"
        assert body["consumer"]["stale"] is False
        assert body["consumer"]["age_seconds"] <= 1
        assert body["consumer"]["max_age_seconds"] == 120
        assert body["queue"] == {
            "due_pending": 0,
            "running": 0,
            "stale_running": 0,
            "failed_last_24h": 0,
            "oldest_overdue_seconds": 0,
            "overdue_warn_after_seconds": 60,
            "zombie_after_seconds": 600,
        }
        assert ScheduledAction.objects.unscoped().count() == before

    def test_old_due_work_is_degraded_but_does_not_fail_the_web_process(
        self, client: Client, status_url: str, settings: Any, tenancy: Tenancy
    ) -> None:
        settings.TICK_TOKEN = TOKEN
        settings.QUEUE_STATUS_OVERDUE_WARN_SECONDS = 60
        touch_queue_consumer("worker", force=True)
        action = make_action(tenancy.workspace)
        ScheduledAction.objects.for_workspace(tenancy.workspace).filter(pk=action.pk).update(
            run_at=timezone.now() - timedelta(minutes=2)
        )

        response = client.get(f"{status_url}?token={TOKEN}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["queue"]["due_pending"] == 1
        assert body["queue"]["oldest_overdue_seconds"] >= 60

    def test_a_stale_running_row_is_an_operational_error(
        self, client: Client, status_url: str, settings: Any, tenancy: Tenancy
    ) -> None:
        settings.TICK_TOKEN = TOKEN
        touch_queue_consumer("worker", force=True)
        action = make_action(tenancy.workspace)
        ScheduledAction.objects.for_workspace(tenancy.workspace).filter(pk=action.pk).update(
            status=ActionStatus.RUNNING,
            updated_at=timezone.now() - timedelta(minutes=11),
        )

        response = client.get(f"{status_url}?token={TOKEN}")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "error"
        assert body["queue"]["running"] == 1
        assert body["queue"]["stale_running"] == 1

    def test_recent_terminal_failure_is_visible_as_degraded(
        self, client: Client, status_url: str, settings: Any, tenancy: Tenancy
    ) -> None:
        settings.TICK_TOKEN = TOKEN
        touch_queue_consumer("worker", force=True)
        make_action(tenancy.workspace, status=ActionStatus.FAILED)

        response = client.get(f"{status_url}?token={TOKEN}")

        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["queue"]["failed_last_24h"] == 1

    def test_method_is_revealed_only_after_valid_authentication(
        self, client: Client, status_url: str, settings: Any
    ) -> None:
        settings.TICK_TOKEN = TOKEN
        assert client.post(status_url).status_code == 404
        response = client.post(f"{status_url}?token={TOKEN}")
        assert response.status_code == 405
        assert response["Allow"] == "GET"
