"""Instagram Follow Gate flow node.

This node performs one live User Profile API check and routes on a three-state
result. It is deliberately not synchronous-safe: provider I/O must not extend
an inbound webhook's inline budget.

UNKNOWN is not NOT_FOLLOWING. The author chooses the fallback policy, with
FAIL_OPEN as the explicit default.
"""

from apps.channels.follow import FollowStatus
from apps.channels.models import ConnectionStatus
from apps.channels.registry import adapter_for
from apps.common.platforms import Platform
from apps.flows.engine.context import NodeContext
from apps.flows.engine.nodes.base import Node
from apps.flows.engine.registry import register_node
from apps.flows.engine.results import Continue, StepResult
from apps.messaging.models import ContactChannelIdentity

__all__ = [
    "ASK_AGAIN",
    "DEFAULT_UNKNOWN_POLICY",
    "FAIL_CLOSED",
    "FAIL_OPEN",
    "InstagramFollowGateNode",
]

FAIL_OPEN = "fail_open"
FAIL_CLOSED = "fail_closed"
ASK_AGAIN = "ask_again"
DEFAULT_UNKNOWN_POLICY = FAIL_OPEN


@register_node
class InstagramFollowGateNode(Node):
    type = "instagram_follow_gate"
    synchronous_safe = False

    def execute(self, ctx: NodeContext) -> StepResult:
        status = _follow_status(ctx)
        if status is FollowStatus.FOLLOWING:
            return Continue("follow:following")
        if status is FollowStatus.NOT_FOLLOWING:
            return Continue("follow:not_following")

        policy = str(ctx.config.get("unknown_policy") or DEFAULT_UNKNOWN_POLICY)
        if policy == FAIL_CLOSED:
            return Continue("follow:not_following")
        if policy == ASK_AGAIN:
            return Continue("follow:unknown")
        return Continue("follow:following")


def _follow_status(ctx: NodeContext) -> FollowStatus:
    connection = ctx.connection
    if (
        connection is None
        or connection.platform != Platform.INSTAGRAM.value
        or connection.status != ConnectionStatus.ACTIVE
    ):
        return FollowStatus.UNKNOWN

    identity = (
        ContactChannelIdentity.objects.for_workspace(ctx.workspace)
        .filter(
            contact=ctx.contact,
            channel_connection=connection,
            platform=Platform.INSTAGRAM.value,
        )
        .first()
    )
    if identity is None:
        return FollowStatus.UNKNOWN

    status = adapter_for(connection.platform).check_follow_status(connection, identity)
    return status if isinstance(status, FollowStatus) else FollowStatus.UNKNOWN
