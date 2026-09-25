"""D7 runtime acceptance for the first-class human handoff node."""

from typing import Any

import pytest

from apps.channels.models import ChannelConnection
from apps.common.platforms import Platform
from apps.flows.engine import start_flow
from apps.flows.models import ExecutionStatus, StartedBy
from apps.flows.tests.support import contact_for, graph, node, published_flow
from apps.messaging.models import Conversation, ConversationState

pytestmark = pytest.mark.django_db


def _connection(workspace: Any) -> ChannelConnection:
    return ChannelConnection.objects.create(
        workspace=workspace,
        platform=Platform.INSTAGRAM.value,
        display_name="Handoff",
        external_id="ig-human-handoff",
    )


class TestHumanHandoffNode:
    def test_opens_and_assigns_the_inbox_then_ends_the_flow(self, tenancy: Any) -> None:
        contact = contact_for(tenancy.workspace)
        connection = _connection(tenancy.workspace)
        agent = tenancy.user_for("agent")
        flow = published_flow(
            tenancy.workspace,
            graph([node("handoff", "human_handoff", {"member": str(agent.pk)})]),
        )

        execution = start_flow(
            contact,
            flow,
            started_by=StartedBy.API,
            connection=connection,
        )

        conversation = Conversation.objects.for_workspace(tenancy.workspace).get(
            contact=contact,
            channel_connection=connection,
        )
        assert execution.status == ExecutionStatus.COMPLETED
        assert conversation.state == ConversationState.OPEN
        assert conversation.assignee == agent

    def test_blank_member_leaves_the_thread_in_the_shared_inbox(self, tenancy: Any) -> None:
        contact = contact_for(tenancy.workspace)
        connection = _connection(tenancy.workspace)
        flow = published_flow(
            tenancy.workspace,
            graph([node("handoff", "human_handoff", {})]),
        )

        execution = start_flow(
            contact,
            flow,
            started_by=StartedBy.API,
            connection=connection,
        )

        conversation = Conversation.objects.for_workspace(tenancy.workspace).get()
        assert execution.status == ExecutionStatus.COMPLETED
        assert conversation.assignee is None

    def test_foreign_member_cannot_be_assigned(self, tenancy: Any, other_tenancy: Any, caplog: Any) -> None:
        contact = contact_for(tenancy.workspace)
        connection = _connection(tenancy.workspace)
        stranger = other_tenancy.owner
        flow = published_flow(
            tenancy.workspace,
            graph([node("handoff", "human_handoff", {"member": str(stranger.pk)})]),
        )

        with caplog.at_level("WARNING"):
            execution = start_flow(
                contact,
                flow,
                started_by=StartedBy.API,
                connection=connection,
            )

        conversation = Conversation.objects.for_workspace(tenancy.workspace).get()
        assert execution.status == ExecutionStatus.COMPLETED
        assert conversation.assignee is None
        assert "is not in this workspace" in caplog.text

    def test_without_a_channel_connection_the_handoff_fails_explicitly(self, tenancy: Any) -> None:
        contact = contact_for(tenancy.workspace)
        flow = published_flow(
            tenancy.workspace,
            graph([node("handoff", "human_handoff", {})]),
        )

        execution = start_flow(contact, flow, started_by=StartedBy.API)

        assert execution.status == ExecutionStatus.FAILED
        assert "requires a channel connection" in execution.last_error
        assert not Conversation.objects.for_workspace(tenancy.workspace).exists()
