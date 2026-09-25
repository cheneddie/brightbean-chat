"""Operational key-rotation integration tests."""

from io import StringIO
from typing import Any, cast

import pytest
from django.core.management import call_command
from django.db import connection as db_connection

from apps.channels.models import ChannelConnection
from apps.common.platforms import Platform
from tests.support import Tenancy
from tests.testapp.models import EncryptionProbe


def _rotate_settings(settings: Any) -> None:
    old_secret = settings.SECRET_KEY
    old_salt = settings.ENCRYPTION_KEY_SALT
    settings.SECRET_KEY = "new-primary-secret-for-command-rotation-tests"
    settings.ENCRYPTION_KEY_SALT = b"new-primary-salt-for-command-rotation-tests"
    settings.ENCRYPTION_KEY_FALLBACKS = [{"secret_key": old_secret, "salt": old_salt.decode("utf-8")}]
    settings.SECRET_KEY_FALLBACKS = [old_secret]


@pytest.mark.django_db
class TestRotateEncryptedData:
    def test_rewrites_ciphertext_and_channel_digest_then_survives_without_fallback(
        self, settings: Any, tenancy: Tenancy, secret_value: str
    ) -> None:
        probe = EncryptionProbe.objects.create(
            secret=secret_value,
            payload=cast(Any, {"token": secret_value}),
        )
        channel = ChannelConnection(
            workspace=tenancy.workspace,
            platform=Platform.TELEGRAM,
            display_name="Rotation bot",
            external_id="rotation-bot",
        )
        webhook_secret = channel.rotate_webhook_secret()
        old_digest = channel.webhook_secret_digest
        channel.save()

        with db_connection.cursor() as cursor:
            cursor.execute(
                "SELECT secret FROM testapp_encryptionprobe WHERE id = %s",
                [str(probe.pk)],
            )
            old_ciphertext = cursor.fetchone()[0]

        _rotate_settings(settings)
        out = StringIO()
        call_command("rotate_encrypted_data", stdout=out)
        assert "Rewrote" in out.getvalue()

        with db_connection.cursor() as cursor:
            cursor.execute(
                "SELECT secret FROM testapp_encryptionprobe WHERE id = %s",
                [str(probe.pk)],
            )
            new_ciphertext = cursor.fetchone()[0]
        assert new_ciphertext != old_ciphertext

        settings.ENCRYPTION_KEY_FALLBACKS = []
        settings.SECRET_KEY_FALLBACKS = []

        stored = EncryptionProbe.objects.get(pk=probe.pk)
        assert stored.secret == secret_value
        assert stored.payload == {"token": secret_value}

        channel.refresh_from_db()
        assert channel.webhook_secret_digest != old_digest
        assert ChannelConnection.resolve_by_webhook_secret(webhook_secret) == channel

    def test_dry_run_does_not_rewrite_ciphertext(self, settings: Any, secret_value: str) -> None:
        probe = EncryptionProbe.objects.create(secret=secret_value)
        with db_connection.cursor() as cursor:
            cursor.execute(
                "SELECT secret FROM testapp_encryptionprobe WHERE id = %s",
                [str(probe.pk)],
            )
            before = cursor.fetchone()[0]

        _rotate_settings(settings)
        call_command("rotate_encrypted_data", "--dry-run", stdout=StringIO())

        with db_connection.cursor() as cursor:
            cursor.execute(
                "SELECT secret FROM testapp_encryptionprobe WHERE id = %s",
                [str(probe.pk)],
            )
            after = cursor.fetchone()[0]
        assert after == before
