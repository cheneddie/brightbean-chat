"""The acceptance criterion: two workers and a tick over 1 000 due actions.

    Two workers + tick running concurrently over 1k due actions: every action
    processed exactly once (assert via handler-side counter), including forced
    crashes mid-batch (zombie recovery test with clock manipulation).

Nothing here is mocked. Real threads, real connections, the real claim
statement. What makes it safe is ``FOR UPDATE SKIP LOCKED``: concurrent claims
select disjoint row sets, so "exactly once" is a property of the statement
rather than of the workers agreeing to take turns.

``transaction=True`` because that is what gives each thread a connection that
can commit — the ordinary ``django_db`` fixture wraps everything in one
transaction that no other thread can see into.
"""

import threading
from datetime import timedelta
from typing import Any

import pytest
from django.db import connections
from django.test import override_settings
from django.utils import timezone

from apps.queueing.housekeeping import ZOMBIE_AFTER, reset_zombie_actions
from apps.queueing.models import ActionStatus, ScheduledAction
from apps.queueing.registry import QueueAdmissionLimitError, schedule
from apps.queueing.tests.support import temporary_handler
from apps.queueing.worker import claim_batch, drain
from tests.support import create_tenancy
from tests.testapp.models import QueueProbe

PROBE = "concurrency_probe"
ACTION_COUNT = 1000
WORKER_COUNT = 2


def _run_drain() -> None:
    """One worker or tick process, in a thread with its own connection."""
    try:
        while drain(batch_size=50).claimed:
            pass
    finally:
        connections.close_all()


def _drain_concurrently(names: list[str], timeout: float = 120.0) -> None:
    """Start one drain thread per name and wait for all of them."""
    threads = [threading.Thread(target=_run_drain, name=name) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
        assert not thread.is_alive(), f"{thread.name} did not finish within {timeout}s"


@pytest.mark.django_db(transaction=True)
class TestExactlyOnce:
    def test_two_workers_and_a_tick_process_every_action_exactly_once(self) -> None:
        tenancy = create_tenancy("concurrency")
        due = timezone.now() - timedelta(seconds=1)
        ScheduledAction.objects.bulk_create(
            ScheduledAction(workspace=tenancy.workspace, run_at=due, type=PROBE, payload={"n": n})
            for n in range(ACTION_COUNT)
        )

        def record(payload: dict[str, Any], action: ScheduledAction) -> None:
            # Unique on action_id: a duplicate execution raises here, inside the
            # handler's transaction, instead of showing up as a bad total later.
            QueueProbe.objects.create(action_id=action.pk, worker=threading.current_thread().name)

        with temporary_handler(PROBE, record):
            _drain_concurrently(["worker-1", "worker-2", "tick"])

        assert QueueProbe.objects.count() == ACTION_COUNT
        assert QueueProbe.objects.values("action_id").distinct().count() == ACTION_COUNT
        assert ScheduledAction.objects.unscoped().filter(type=PROBE, status=ActionStatus.DONE).count() == ACTION_COUNT
        assert not ScheduledAction.objects.unscoped().filter(type=PROBE).exclude(status=ActionStatus.DONE).exists()

        # And prove the workers really did run concurrently — a test where one
        # thread happened to do everything would pass every assertion above
        # while proving nothing about contention.
        assert QueueProbe.objects.values("worker").distinct().count() > 1

    def test_a_crash_mid_batch_is_recovered_and_still_runs_exactly_once(self) -> None:
        """Forced crash mid-batch, then zombie recovery, with the clock driven by hand.

        The design collapses the crash window to a single point, which is what
        makes this testable without killing a process: the handler's writes and
        the row's ``done`` marking share one transaction, so a worker that dies
        can only ever die *between the claim committing and that transaction
        committing*. Claiming a batch and walking away is therefore not an
        approximation of a ``SIGKILL`` — it is the same state.

        Exactly-once holds across the recovery because the crash lands before
        any side effect. The queue's guarantee in general is at-least-once,
        which is why handlers are documented as needing to be idempotent.
        """
        tenancy = create_tenancy("crash")
        due = timezone.now() - timedelta(seconds=1)
        ScheduledAction.objects.bulk_create(
            ScheduledAction(workspace=tenancy.workspace, run_at=due, type=PROBE, payload={"n": n}) for n in range(200)
        )

        def record(payload: dict[str, Any], action: ScheduledAction) -> None:
            QueueProbe.objects.create(action_id=action.pk, worker=threading.current_thread().name)

        # The crash: a worker claims 50 rows and dies. The claim is committed,
        # so the rows say 'running' with nothing running them.
        killed = [action.pk for action in claim_batch(50)]
        assert len(killed) == 50

        with temporary_handler(PROBE, record):
            _drain_concurrently(["worker-1", "worker-2"])

        # Stranded, and no amount of draining will touch them: the claim
        # statement only ever looks at 'pending'.
        assert QueueProbe.objects.count() == 150
        assert ScheduledAction.objects.unscoped().filter(id__in=killed, status=ActionStatus.RUNNING).count() == 50
        with temporary_handler(PROBE, record):
            _drain_concurrently(["worker-1"])
        assert QueueProbe.objects.count() == 150

        # Clock manipulation: age the abandoned rows past the 10-minute cutoff,
        # which is what the hourly sweep would see ten minutes after the crash.
        ScheduledAction.objects.unscoped().filter(id__in=killed).update(
            updated_at=timezone.now() - ZOMBIE_AFTER - timedelta(minutes=1)
        )
        assert reset_zombie_actions().startswith("reset 50 zombie action(s)")

        with temporary_handler(PROBE, record):
            _drain_concurrently(["worker-1", "worker-2"])

        assert QueueProbe.objects.count() == 200
        assert QueueProbe.objects.values("action_id").distinct().count() == 200
        assert not ScheduledAction.objects.unscoped().filter(type=PROBE).exclude(status=ActionStatus.DONE).exists()

        # The crashed attempt still counted, so an action that crashes every
        # time runs out of budget instead of looping forever.
        recovered = ScheduledAction.objects.unscoped().filter(id__in=killed).first()
        assert recovered is not None
        assert recovered.attempts == 2


@pytest.mark.django_db(transaction=True)
@override_settings(QUEUE_MAX_ACTIVE_PER_WORKSPACE=25)
def test_concurrent_enqueue_cannot_overrun_workspace_admission_limit() -> None:
    """The count+insert admission decision is atomic per workspace.

    Four independent database connections race to enqueue 100 distinct actions.
    Exactly 25 may enter; without the workspace advisory lock several threads
    can observe the same final free slot and overshoot the configured cap.
    """
    tenancy = create_tenancy("admission")
    due = timezone.now() - timedelta(seconds=1)
    barrier = threading.Barrier(4)
    guard = threading.Lock()
    accepted: list[Any] = []
    failures: list[BaseException] = []

    def enqueue(worker: int) -> None:
        try:
            connections.close_all()
            barrier.wait(timeout=10)
            for index in range(25):
                try:
                    action = schedule(
                        "admission_probe",
                        due,
                        {"worker": worker, "index": index},
                        workspace=tenancy.workspace,
                    )
                except QueueAdmissionLimitError:
                    continue
                with guard:
                    accepted.append(action.pk)
        except BaseException as exc:  # pragma: no cover - surfaced below
            with guard:
                failures.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=enqueue, args=(worker,), name=f"enqueue-{worker}") for worker in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), f"{thread.name} did not finish"

    assert failures == []
    assert len(accepted) == 25
    assert len(set(accepted)) == 25
    assert (
        ScheduledAction.objects.for_workspace(tenancy.workspace)
        .filter(status__in=(ActionStatus.PENDING, ActionStatus.RUNNING))
        .count()
        == 25
    )

@pytest.mark.django_db(transaction=True)
def test_fair_claiming_remains_disjoint_across_concurrent_workers() -> None:
    noisy = create_tenancy("fair-noisy")
    quiet = create_tenancy("fair-quiet")
    noisy_due = timezone.now() - timedelta(minutes=2)
    quiet_due = timezone.now() - timedelta(minutes=1)

    ScheduledAction.objects.bulk_create(
        ScheduledAction(workspace=noisy.workspace, run_at=noisy_due, type=PROBE, payload={"n": n})
        for n in range(1_000)
    )
    ScheduledAction.objects.bulk_create(
        ScheduledAction(workspace=quiet.workspace, run_at=quiet_due, type=PROBE, payload={"n": n})
        for n in range(20)
    )

    barrier = threading.Barrier(2)
    guard = threading.Lock()
    claimed: list[tuple[Any, Any]] = []
    failures: list[BaseException] = []

    def claim(name: str) -> None:
        try:
            connections.close_all()
            barrier.wait(timeout=10)
            rows = claim_batch(50)
            with guard:
                claimed.extend((row.pk, row.workspace_id) for row in rows)
        except BaseException as exc:  # pragma: no cover - surfaced below
            with guard:
                failures.append(exc)
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=claim, args=("worker-1",), name="fair-worker-1"),
        threading.Thread(target=claim, args=("worker-2",), name="fair-worker-2"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), f"{thread.name} did not finish"

    assert failures == []
    assert len(claimed) == 100
    assert len({pk for pk, _workspace_id in claimed}) == 100
    assert sum(1 for _pk, workspace_id in claimed if workspace_id == quiet.workspace.pk) == 20
    assert sum(1 for _pk, workspace_id in claimed if workspace_id == noisy.workspace.pk) == 80

