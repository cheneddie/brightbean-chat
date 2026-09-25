"""D7 — first-class human handoff node.

The visual builder should let an author express "a person takes over here" as
one terminal step instead of knowing which generic action verbs to compose.

D8 owns the longer-lived inbox takeover/resume policy. This node intentionally
does only the D7 boundary:
- require the run to have a channel connection;
- open/reopen the conversation;
- optionally assign it to a member of this workspace;
- end the current flow successfully.
"""

import logging
from typing import Any
from uuid import UUID

from apps.flows.engine.context import NodeContext
from apps.flows.engine.nodes.base import Node
from apps.flows.engine.registry import register_node
from apps.flows.engine.results import End, Fail, StepResult
from apps.messaging import services as messaging

__all__ = ["HumanHandoffNode"]

logger = logging.getLogger(__name__)


@register_node
class HumanHandoffNode(Node):
    """Open the inbox thread, optionally assign it, and stop this flow."""

    type = "human_handoff"
    # Handoff mutates inbox ownership/state and is not part of the webhook
    # inline-safe contract. Run it on the worker side instead of extending the
    # inbound request budget.
    synchronous_safe = False

    def execute(self, ctx: NodeContext) -> StepResult:
        connection = ctx.connection
        if connection is None:
            return Fail("human_handoff requires a channel connection")

        conversation = messaging.open_conversation(
            workspace=ctx.workspace,
            contact=ctx.contact,
            connection=connection,
        )

        raw_member = ctx.config.get("member")
        if raw_member:
            member = _member(ctx, raw_member)
            if member is not None:
                messaging.assign_conversation(conversation, member)

        return End()


def _member(ctx: NodeContext, value: Any) -> Any | None:
    """Resolve a user only through membership in this execution's workspace."""
    from apps.members.models import WorkspaceMembership

    try:
        user_id = UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        logger.warning("Execution %s: %r is not a member id.", ctx.execution.pk, value)
        return None

    membership = (
        WorkspaceMembership.objects.filter(
            workspace_id=ctx.workspace_id,
            user_id=user_id,
        )
        .select_related("user")
        .first()
    )
    if membership is None:
        logger.warning(
            "Execution %s: member %s is not in this workspace; leaving handoff unassigned.",
            ctx.execution.pk,
            user_id,
        )
        return None
    return membership.user
