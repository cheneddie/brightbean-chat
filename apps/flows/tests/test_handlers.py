"""The three queue action types, driven through the real worker.

Running them through :func:`apps.queueing.worker.process_action` rather than
calling the handler directly is deliberate: the worker is what takes the contact
lock, opens the transaction and marks the row, and the handlers are written
assuming all three. A test that called the function bare would pass with the
registration broken and the lock absent.
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.flows.engine.results import Wait
from apps.flows.models import ExecutionStatus, FlowExecution, StartedBy
from apps.flows.tests.support import contact_for, edge, graph, node, node_runtime, published_flow
from apps.inbox import services as inbox_services
from apps.messaging import services as messaging
from apps.queueing.models import ActionStatus, ActionType, ScheduledAction
from apps.queueing.registry import get_handler, schedule
from apps.queueing.worker import process_action

NOOP_ACTION = {"actions": [{"verb": "remove_tag", "tag": "not-a-tag-here"}]}
TAG_ACTION = {"actions": [{"verb": "add_tag", "tag": "resumed"}]}
WAIT_CONFIG = {"type": "buttons", "token": "t1", "handles": {}}


def _run(action: ScheduledAction) -> ScheduledAction:
    """Claim-and-run one action the way the worker does, then re-read it."""
    action.status = ActionStatus.RUNNING
    action.attempts = 1
    action.save(update_fields=["status", "attempts", "updated_at"])
    process_action(action)
    action.refresh_from_db()
    return action


#: A node type whose spec exposes both `default` and `timeout` — which is what
#: a followup timer needs somewhere to land. Its real runtime is PR 2's; here it
#: is stubbed to park, because what is under test is the queue wiring.
QUESTION = {"question": "Your email?", "reply_type": "text", "target": {"type": "custom_field", "key": "answer"}}


def _waiting_flow(workspace: Any):
    document = graph(
        [node("a", "data_collection", QUESTION), node("b", "action", TAG_ACTION, x=200)],
        [edge("a", "default", "b"), edge("a", "timeout", "b")],
    )
    return published_flow(workspace, document)


class TestRegistration:
    def test_the_three_types_are_claimed(self):
        for action_type in (ActionType.START_FLOW, ActionType.RESUME_EXECUTION, ActionType.FOLLOWUP_TIMER):
            assert get_handler(action_type) is not None


@pytest.mark.django_db
class TestStartFlowAction:
    def test_it_starts_the_flow(self, tenancy):
        flow = published_flow(tenancy.workspace, graph([node("a", "action", TAG_ACTION)]))
        contact = contact_for(tenancy.workspace)
        action = schedule(
            ActionType.START_FLOW,
            timezone.now(),
            {"contact_id": str(contact.pk), "flow_id": str(flow.pk), "started_by": StartedBy.API},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        execution = FlowExecution.objects.for_workspace(tenancy.workspace).get()
        assert execution.status == ExecutionStatus.COMPLETED
        assert {tag.name for tag in contact.tags.all()} == {"resumed"}

    def test_an_unpublished_flow_is_dropped_rather_than_retried(self, tenancy):
        """Five attempts over six hours cannot make a draft publishable."""
        from apps.flows.services import create_flow

        flow = create_flow(workspace=tenancy.workspace, name="Draft")
        contact = contact_for(tenancy.workspace)
        action = schedule(
            ActionType.START_FLOW,
            timezone.now(),
            {"contact_id": str(contact.pk), "flow_id": str(flow.pk)},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        assert not FlowExecution.objects.for_workspace(tenancy.workspace).exists()

    def test_a_payload_naming_another_tenants_flow_resolves_to_nothing(self, tenancy, other_tenancy):
        """Ids in a payload are ids, not trusted objects."""
        theirs = published_flow(other_tenancy.workspace, graph([node("a", "action", TAG_ACTION)]))
        contact = contact_for(tenancy.workspace)
        action = schedule(
            ActionType.START_FLOW,
            timezone.now(),
            {"contact_id": str(contact.pk), "flow_id": str(theirs.pk)},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        assert not FlowExecution.objects.for_workspace(tenancy.workspace).exists()
        assert {tag.name for tag in contact.tags.all()} == set()

    def test_a_version_belonging_to_another_flow_is_dropped_not_retried(self, tenancy):
        """A permanent argument fault: five attempts over six hours cannot fix it."""
        from apps.flows.services import latest_version

        flow = published_flow(tenancy.workspace, graph([node("a", "action", TAG_ACTION)]))
        other = published_flow(tenancy.workspace, graph([node("a", "action", TAG_ACTION)]), name="Other")
        contact = contact_for(tenancy.workspace)
        action = schedule(
            ActionType.START_FLOW,
            timezone.now(),
            {
                "contact_id": str(contact.pk),
                "flow_id": str(flow.pk),
                "flow_version_id": str(latest_version(other).pk),
            },
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        assert not FlowExecution.objects.for_workspace(tenancy.workspace).exists()

    def test_an_unresolvable_version_is_dropped_not_run_as_published(self, tenancy):
        """The dangerous fallback: a stale preview must not send live content.

        A payload that *asks* for a version and names one that is gone is not
        the same as a payload that asks for none. Treating them alike would run
        the published graph at a contact somebody was testing a draft against.
        """
        published = graph([node("a", "action", {"actions": [{"verb": "add_tag", "tag": "published"}]})])
        flow = published_flow(tenancy.workspace, published)
        contact = contact_for(tenancy.workspace)
        action = schedule(
            ActionType.START_FLOW,
            timezone.now(),
            {
                "contact_id": str(contact.pk),
                "flow_id": str(flow.pk),
                "flow_version_id": "0192f000-0000-7000-8000-0000000000ff",
            },
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        assert not FlowExecution.objects.for_workspace(tenancy.workspace).exists()
        assert {tag.name for tag in contact.tags.all()} == set()

    def test_an_unexpected_value_error_still_retries(self, tenancy):
        """The catch is narrow: only FlowNotRunnableError is a permanent fault.

        A ValueError from inside a node is a runtime failure the queue promised
        to retry, and swallowing it would mark the row done and lose the work.
        """
        flow = published_flow(tenancy.workspace, graph([node("a", "action", TAG_ACTION)]))
        contact = contact_for(tenancy.workspace)
        action = schedule(
            ActionType.START_FLOW,
            timezone.now(),
            {"contact_id": str(contact.pk), "flow_id": str(flow.pk)},
            workspace=tenancy.workspace,
            contact=contact,
        )

        def _explode(_ctx):
            raise ValueError("something went wrong mid-run")

        with node_runtime("action", _explode):
            assert _run(action).status == ActionStatus.PENDING

    def test_a_missing_contact_is_dropped(self, tenancy):
        flow = published_flow(tenancy.workspace, graph([node("a", "action", TAG_ACTION)]))
        action = schedule(
            ActionType.START_FLOW,
            timezone.now(),
            {"contact_id": "0192f000-0000-7000-8000-0000000000ff", "flow_id": str(flow.pk)},
            workspace=tenancy.workspace,
        )

        assert _run(action).status == ActionStatus.DONE


@pytest.mark.django_db
class TestResumeActions:
    def _parked(self, tenancy, *, connection=None):
        from apps.flows.engine import start_flow

        flow = _waiting_flow(tenancy.workspace)
        contact = contact_for(tenancy.workspace)
        with node_runtime("data_collection", lambda ctx: Wait(WAIT_CONFIG)):
            execution = start_flow(contact, flow, started_by=StartedBy.API, connection=connection)
        return contact, execution

    def test_resume_execution_follows_the_default_handle(self, tenancy):
        contact, execution = self._parked(tenancy)
        action = schedule(
            ActionType.RESUME_EXECUTION,
            timezone.now(),
            {"execution_id": str(execution.pk), "handle": "default", "token": "t1"},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        assert {tag.name for tag in contact.tags.all()} == {"resumed"}

    def test_the_followup_timer_defaults_to_the_timeout_handle(self, tenancy):
        contact, execution = self._parked(tenancy)
        action = schedule(
            ActionType.FOLLOWUP_TIMER,
            timezone.now(),
            {"execution_id": str(execution.pk), "token": "t1"},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        execution.refresh_from_db()
        assert execution.current_node_id == "b"

    @pytest.mark.parametrize("action_type", [ActionType.RESUME_EXECUTION, ActionType.FOLLOWUP_TIMER])
    def test_due_resume_is_deferred_until_human_takeover_pause_ends(self, tenancy, connection, action_type):
        contact, execution = self._parked(tenancy, connection=connection)
        conversation = messaging.open_conversation(workspace=tenancy.workspace, contact=contact, connection=connection)
        until = timezone.now() + timedelta(hours=1)
        messaging.pause_automation(conversation, until)

        payload = {"execution_id": str(execution.pk), "token": "t1"}
        if action_type == ActionType.RESUME_EXECUTION:
            payload["handle"] = "default"
        action = schedule(
            action_type,
            timezone.now(),
            payload,
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.WAITING_REPLY
        assert {tag.name for tag in contact.tags.all()} == set()

        successor = (
            ScheduledAction.objects.for_workspace(tenancy.workspace)
            .exclude(pk=action.pk)
            .get(type=action_type, status=ActionStatus.PENDING)
        )
        assert successor.payload == {**payload, "_takeover_deferred": True}
        assert successor.run_at == until
        assert successor.attempts == 0
        assert successor.max_attempts == action.max_attempts

    def test_extending_takeover_pause_defers_the_successor_again(self, tenancy, connection):
        contact, execution = self._parked(tenancy, connection=connection)
        conversation = messaging.open_conversation(workspace=tenancy.workspace, contact=contact, connection=connection)
        first_until = timezone.now() + timedelta(minutes=30)
        messaging.pause_automation(conversation, first_until)
        payload = {"execution_id": str(execution.pk), "handle": "default", "token": "t1"}
        first = schedule(
            ActionType.RESUME_EXECUTION,
            timezone.now(),
            payload,
            workspace=tenancy.workspace,
            contact=contact,
        )
        assert _run(first).status == ActionStatus.DONE
        deferred = (
            ScheduledAction.objects.for_workspace(tenancy.workspace)
            .exclude(pk=first.pk)
            .get(status=ActionStatus.PENDING)
        )

        second_until = timezone.now() + timedelta(hours=2)
        messaging.pause_automation(conversation, second_until)
        assert _run(deferred).status == ActionStatus.DONE

        pending = ScheduledAction.objects.for_workspace(tenancy.workspace).filter(status=ActionStatus.PENDING)
        assert pending.count() == 1
        second = pending.get()
        assert second.run_at == second_until
        assert second.payload == {**payload, "_takeover_deferred": True}
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.WAITING_REPLY

    def test_explicit_resume_releases_a_takeover_deferred_timer_immediately(self, tenancy, connection):
        contact, execution = self._parked(tenancy, connection=connection)
        conversation = messaging.open_conversation(workspace=tenancy.workspace, contact=contact, connection=connection)
        messaging.pause_automation(conversation, timezone.now() + timedelta(hours=1))
        payload = {"execution_id": str(execution.pk), "handle": "default", "token": "t1"}
        action = schedule(
            ActionType.RESUME_EXECUTION,
            timezone.now(),
            payload,
            workspace=tenancy.workspace,
            contact=contact,
        )
        assert _run(action).status == ActionStatus.DONE
        deferred = (
            ScheduledAction.objects.for_workspace(tenancy.workspace)
            .exclude(pk=action.pk)
            .get(status=ActionStatus.PENDING)
        )
        assert deferred.run_at > timezone.now()

        inbox_services.set_automation_pause(
            conversation,
            None,
            actor=tenancy.user_for("agent"),
        )
        deferred.refresh_from_db()
        assert deferred.run_at <= timezone.now()

        assert _run(deferred).status == ActionStatus.DONE
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        assert {tag.name for tag in contact.tags.all()} == {"resumed"}

    def test_stale_timer_is_not_deferred_just_because_takeover_is_active(self, tenancy, connection):
        contact, execution = self._parked(tenancy, connection=connection)
        conversation = messaging.open_conversation(workspace=tenancy.workspace, contact=contact, connection=connection)
        messaging.pause_automation(conversation, timezone.now() + timedelta(hours=1))
        action = schedule(
            ActionType.FOLLOWUP_TIMER,
            timezone.now(),
            {"execution_id": str(execution.pk), "token": "stale"},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        assert ScheduledAction.objects.for_workspace(tenancy.workspace).filter(status=ActionStatus.PENDING).count() == 0
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.WAITING_REPLY

    def test_a_stale_token_is_a_no_op_rather_than_a_failure(self, tenancy):
        """A timer racing a reply must lose quietly, not retry five times."""
        contact, execution = self._parked(tenancy)
        action = schedule(
            ActionType.FOLLOWUP_TIMER,
            timezone.now(),
            {"execution_id": str(execution.pk), "token": "stale"},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.WAITING_REPLY

    def test_a_vanished_execution_is_dropped(self, tenancy):
        contact = contact_for(tenancy.workspace)
        action = schedule(
            ActionType.RESUME_EXECUTION,
            timezone.now(),
            {"execution_id": "0192f000-0000-7000-8000-0000000000ff"},
            workspace=tenancy.workspace,
            contact=contact,
        )

        assert _run(action).status == ActionStatus.DONE
