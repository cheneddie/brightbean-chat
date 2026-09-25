"""Instagram Follow Gate provider semantics.

Meta's User Profile API exposes is_user_follow_business only for an IGSID in a
messaging-consent context. Every inability to answer stays UNKNOWN; it is never
evidence that the person does not follow the business.
"""

from types import SimpleNamespace

import pytest

from apps.channels.follow import FollowStatus
from apps.channels.models import ChannelConnection, ConnectionStatus
from apps.channels.providers.instagram import InstagramAdapter
from apps.channels.tests.instagram_support import IG_USER_ID, Reply, fake_graph

pytestmark = pytest.mark.django_db


def identity(user_id: str = IG_USER_ID):
    return SimpleNamespace(platform_user_id=user_id)


class TestInstagramFollowStatus:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, FollowStatus.FOLLOWING),
            (False, FollowStatus.NOT_FOLLOWING),
        ],
    )
    def test_meta_boolean_maps_to_three_state(
        self,
        instagram_connection: ChannelConnection,
        value: bool,
        expected: FollowStatus,
    ) -> None:
        with fake_graph(lambda api: api.reply(IG_USER_ID, Reply(body={"is_user_follow_business": value}))) as api:
            result = InstagramAdapter().check_follow_status(instagram_connection, identity())

        assert result is expected
        assert api.paths() == [IG_USER_ID]
        assert api.tokens and api.tokens[0].startswith("Bearer ")

    def test_missing_field_is_unknown(self, instagram_connection: ChannelConnection) -> None:
        with fake_graph(lambda api: api.reply(IG_USER_ID, Reply(body={"username": "someone"}))):
            result = InstagramAdapter().check_follow_status(instagram_connection, identity())

        assert result is FollowStatus.UNKNOWN

    @pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
    def test_non_boolean_field_is_unknown(
        self,
        instagram_connection: ChannelConnection,
        value: object,
    ) -> None:
        with fake_graph(lambda api: api.reply(IG_USER_ID, Reply(body={"is_user_follow_business": value}))):
            result = InstagramAdapter().check_follow_status(instagram_connection, identity())

        assert result is FollowStatus.UNKNOWN

    def test_missing_igsid_is_unknown_without_call(self, instagram_connection: ChannelConnection) -> None:
        with fake_graph() as api:
            result = InstagramAdapter().check_follow_status(instagram_connection, identity(""))

        assert result is FollowStatus.UNKNOWN
        assert api.calls == []

    def test_rate_limit_is_unknown_not_not_following(self, instagram_connection: ChannelConnection) -> None:
        with fake_graph(lambda api: api.reply(IG_USER_ID, Reply(status=429, headers={"Retry-After": "2"}))):
            result = InstagramAdapter().check_follow_status(instagram_connection, identity())

        assert result is FollowStatus.UNKNOWN
        instagram_connection.refresh_from_db()
        assert instagram_connection.status == ConnectionStatus.ACTIVE

    def test_auth_failure_marks_reauth_but_status_is_unknown(
        self,
        instagram_connection: ChannelConnection,
    ) -> None:
        error = Reply(
            status=400,
            body={"error": {"message": "expired", "code": 190, "type": "OAuthException"}},
        )
        with fake_graph(lambda api: api.reply(IG_USER_ID, error)):
            result = InstagramAdapter().check_follow_status(instagram_connection, identity())

        assert result is FollowStatus.UNKNOWN
        instagram_connection.refresh_from_db()
        assert instagram_connection.status == ConnectionStatus.NEEDS_REAUTH
