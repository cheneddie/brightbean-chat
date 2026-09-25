"""Runtime acceptance for the Instagram Follow Gate node."""

from typing import Any

import pytest

from apps.channels.follow import FollowStatus
from apps.channels.models import ChannelConnection, ConnectionStatus
from apps.channels.providers.instagram import InstagramAdapter
from apps.common.platforms import Platform
from apps.flows.engine import start_flow
from apps.flows.models import StartedBy
from apps.flows.tests.support import contact_for, edge, graph, node, published_flow
from apps.messaging.models import ContactChannelIdentity

pytestmark = pytest.mark.django_db


def _action(tag: str) -> dict[str, Any]:
    return {"actions": [{"verb": "add_tag", "tag": tag}]}


def _gate_flow(workspace: Any, policy: str | None = "fail_open"):
    config = {} if policy is None else {"unknown_policy": policy}
    return published_flow(
        workspace,
        graph(
            [
                node("gate", "instagram_follow_gate", config),
                node("yes", "action", _action("following"), x=250),
                node("no", "action", _action("not-following"), x=250),
                node("unknown", "action", _action("unknown"), x=250),
            ],
            [
                edge("gate", "follow:following", "yes"),
                edge("gate", "follow:not_following", "no"),
                edge("gate", "follow:unknown", "unknown"),
            ],
        ),
    )


def _connection(workspace: Any, *, platform: str = Platform.INSTAGRAM.value) -> ChannelConnection:
    return ChannelConnection.objects.create(
        workspace=workspace,
        platform=platform,
        display_name="Follow gate",
        external_id=f"{platform}-follow-gate",
    )


def _identity(contact: Any, connection: ChannelConnection) -> ContactChannelIdentity:
    return ContactChannelIdentity.objects.create(
        contact=contact,
        channel_connection=connection,
        platform=connection.platform,
        platform_user_id="6789012345678901",
    )


def _tags(contact: Any) -> set[str]:
    return set(contact.tags.values_list("name", flat=True))


class TestInstagramFollowGateRouting:
    @pytest.mark.parametrize(
        ("status", "policy", "expected"),
        [
            (FollowStatus.FOLLOWING, "fail_open", "following"),
            (FollowStatus.FOLLOWING, "fail_closed", "following"),
            (FollowStatus.NOT_FOLLOWING, "fail_open", "not-following"),
            (FollowStatus.NOT_FOLLOWING, "ask_again", "not-following"),
            (FollowStatus.UNKNOWN, "fail_open", "following"),
            (FollowStatus.UNKNOWN, "fail_closed", "not-following"),
            (FollowStatus.UNKNOWN, "ask_again", "unknown"),
        ],
    )
    def test_three_state_routes_with_explicit_unknown_policy(
        self,
        tenancy: Any,
        monkeypatch: pytest.MonkeyPatch,
        status: FollowStatus,
        policy: str,
        expected: str,
    ) -> None:
        contact = contact_for(tenancy.workspace)
        connection = _connection(tenancy.workspace)
        _identity(contact, connection)
        monkeypatch.setattr(InstagramAdapter, "check_follow_status", lambda self, conn, ident: status)

        start_flow(
            contact,
            _gate_flow(tenancy.workspace, policy),
            started_by=StartedBy.API,
            connection=connection,
        )

        assert _tags(contact) == {expected}

    def test_unknown_defaults_to_fail_open(
        self,
        tenancy: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        contact = contact_for(tenancy.workspace)
        connection = _connection(tenancy.workspace)
        _identity(contact, connection)
        monkeypatch.setattr(
            InstagramAdapter,
            "check_follow_status",
            lambda self, conn, ident: FollowStatus.UNKNOWN,
        )

        start_flow(
            contact,
            _gate_flow(tenancy.workspace, None),
            started_by=StartedBy.API,
            connection=connection,
        )

        assert _tags(contact) == {"following"}


class TestInstagramFollowGateUnknownSources:
    @pytest.mark.parametrize(
        ("platform", "status"),
        [
            (Platform.TELEGRAM.value, ConnectionStatus.ACTIVE),
            (Platform.INSTAGRAM.value, ConnectionStatus.DISABLED),
        ],
    )
    def test_wrong_or_inactive_connection_is_unknown_without_provider_call(
        self,
        tenancy: Any,
        monkeypatch: pytest.MonkeyPatch,
        platform: str,
        status: str,
    ) -> None:
        contact = contact_for(tenancy.workspace)
        connection = _connection(tenancy.workspace, platform=platform)
        connection.status = status
        connection.save(update_fields=["status", "updated_at"])
        _identity(contact, connection)

        def forbidden(*args: Any, **kwargs: Any) -> FollowStatus:
            raise AssertionError("provider must not be called")

        monkeypatch.setattr(InstagramAdapter, "check_follow_status", forbidden)

        start_flow(
            contact,
            _gate_flow(tenancy.workspace, "ask_again"),
            started_by=StartedBy.API,
            connection=connection,
        )

        assert _tags(contact) == {"unknown"}

    def test_missing_identity_is_unknown_without_provider_call(
        self,
        tenancy: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        contact = contact_for(tenancy.workspace)
        connection = _connection(tenancy.workspace)

        def forbidden(*args: Any, **kwargs: Any) -> FollowStatus:
            raise AssertionError("provider must not be called")

        monkeypatch.setattr(InstagramAdapter, "check_follow_status", forbidden)

        start_flow(
            contact,
            _gate_flow(tenancy.workspace, "fail_closed"),
            started_by=StartedBy.API,
            connection=connection,
        )

        assert _tags(contact) == {"not-following"}
