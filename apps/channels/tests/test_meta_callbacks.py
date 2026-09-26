"""Meta Instagram deauthorize and data-deletion callback contracts."""

import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlencode

import pytest
from django.db import connection as db_connection
from django.test import Client
from django.urls import reverse

from apps.channels.meta_callbacks import parse_signed_request
from apps.channels.models import ChannelConnection, MetaDataDeletionReceipt
from apps.channels.tests.instagram_support import APP_SECRET, IG_ACCOUNT_ID
from apps.common.platforms import Platform
from tests.support import Tenancy, org_platform_credential

META_APP_USER_ID = "99887766554433221"


def _signed_request(
    *,
    user_id: str = META_APP_USER_ID,
    secret: str = APP_SECRET,
    algorithm: str = "HMAC-SHA256",
) -> str:
    payload = json.dumps(
        {"algorithm": algorithm, "issued_at": 1_700_000_000, "user_id": user_id},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{encoded_signature}.{encoded_payload}"


def _post(client: Client, url: str, signed: str) -> Any:
    body = urlencode({"signed_request": signed})
    return client.post(url, data=body, content_type="application/x-www-form-urlencoded")

def _bind_lifecycle(connection: ChannelConnection, user_id: str = META_APP_USER_ID) -> None:
    connection.meta_app_scoped_user_id = user_id
    connection.save(update_fields=["meta_app_scoped_user_id", "updated_at"])


class TestSignedRequest:
    def test_valid_request_round_trips(self) -> None:
        payload = parse_signed_request(_signed_request(), app_secret=APP_SECRET)
        assert payload is not None
        assert payload["user_id"] == META_APP_USER_ID

    def test_bad_signature_is_rejected(self) -> None:
        assert parse_signed_request(_signed_request(secret="wrong"), app_secret=APP_SECRET) is None

    def test_wrong_algorithm_is_rejected_even_with_a_valid_hmac(self) -> None:
        assert parse_signed_request(_signed_request(algorithm="HMAC-SHA1"), app_secret=APP_SECRET) is None

    @pytest.mark.parametrize("value", ["", "not-a-signed-request", ".payload", "sig."])
    def test_malformed_requests_are_rejected(self, value: str) -> None:
        assert parse_signed_request(value, app_secret=APP_SECRET) is None

    def test_valid_hmac_with_standard_base64_alphabet_is_rejected(self) -> None:
        """signed_request segments are strict unpadded Base64URL, not generic Base64."""
        signed = ""
        for issued_at in range(1_700_000_000, 1_700_001_000):
            payload = json.dumps(
                {"algorithm": "HMAC-SHA256", "issued_at": issued_at, "user_id": META_APP_USER_ID},
                separators=(",", ":"),
            ).encode("utf-8")
            encoded_payload = base64.b64encode(payload).decode("ascii").rstrip("=")
            signature = hmac.new(
                APP_SECRET.encode("utf-8"),
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            encoded_signature = base64.b64encode(signature).decode("ascii").rstrip("=")
            candidate = f"{encoded_signature}.{encoded_payload}"
            if "+" in candidate or "/" in candidate:
                signed = candidate
                break

        assert signed, "fixture search must find a standard-Base64-only character"
        assert parse_signed_request(signed, app_secret=APP_SECRET) is None


@pytest.mark.django_db
class TestDataDeletionCallback:
    def test_valid_callback_deletes_the_connected_account_and_returns_status_capability(
        self, client: Client, instagram_app: dict[str, str], instagram_connection: ChannelConnection
    ) -> None:
        _bind_lifecycle(instagram_connection)
        url = reverse("instagram_data_deletion")

        response = _post(client, url, _signed_request())

        assert response.status_code == 200
        body = response.json()
        code = body["confirmation_code"]
        assert code
        status_url = reverse("instagram_data_deletion_status", kwargs={"confirmation_code": code})
        assert body["url"].endswith(status_url)
        assert not ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()

        receipt = MetaDataDeletionReceipt.objects.get()
        assert receipt.deleted_connections == 1
        assert receipt.confirmation_digest != code

        status = client.get(status_url)
        assert status.status_code == 200
        assert status.json()["status"] == "completed"
        assert status.json()["confirmation_code"] == code
        assert status.json()["deleted_connections"] == 1

    def test_signed_user_id_never_falls_back_to_external_id(
        self, client: Client, instagram_app: dict[str, str], instagram_connection: ChannelConnection
    ) -> None:
        # Make the signed lifecycle identity equal to the routing external_id,
        # while the row explicitly belongs to a different lifecycle user. A
        # callback must not "helpfully" guess and delete by external_id.
        _bind_lifecycle(instagram_connection, user_id="different-lifecycle-user")

        response = _post(
            client,
            reverse("instagram_data_deletion"),
            _signed_request(user_id=IG_ACCOUNT_ID),
        )

        assert response.status_code == 200
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()
        assert MetaDataDeletionReceipt.objects.get().deleted_connections == 0

    def test_repeated_callback_is_idempotent_after_the_connection_is_gone(
        self, client: Client, instagram_app: dict[str, str], instagram_connection: ChannelConnection
    ) -> None:
        _bind_lifecycle(instagram_connection)
        url = reverse("instagram_data_deletion")
        first = _post(client, url, _signed_request())
        second = _post(client, url, _signed_request())

        assert first.status_code == 200
        assert second.status_code == 200
        receipts = list(MetaDataDeletionReceipt.objects.order_by("created_at"))
        assert [row.deleted_connections for row in receipts] == [1, 0]

    def test_bad_signature_cannot_delete_the_connection(
        self, client: Client, instagram_app: dict[str, str], instagram_connection: ChannelConnection
    ) -> None:
        _bind_lifecycle(instagram_connection)
        response = _post(client, reverse("instagram_data_deletion"), _signed_request(secret="wrong"))

        assert response.status_code == 403
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()
        assert not MetaDataDeletionReceipt.objects.exists()

    def test_route_is_hidden_without_deployment_app_credentials(
        self, client: Client, settings: Any, instagram_connection: ChannelConnection
    ) -> None:
        _bind_lifecycle(instagram_connection)
        settings.PLATFORM_CREDENTIALS_FROM_ENV = {}
        response = _post(client, reverse("instagram_data_deletion"), _signed_request())

        assert response.status_code == 404
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()

    def test_status_capability_survives_planned_key_rotation(
        self,
        client: Client,
        instagram_app: dict[str, str],
        instagram_connection: ChannelConnection,
        settings: Any,
    ) -> None:
        _bind_lifecycle(instagram_connection)
        response = _post(client, reverse("instagram_data_deletion"), _signed_request())
        code = response.json()["confirmation_code"]
        status_url = reverse("instagram_data_deletion_status", kwargs={"confirmation_code": code})
        receipt = MetaDataDeletionReceipt.objects.get()
        old_digest = receipt.confirmation_digest
        old_secret = settings.SECRET_KEY
        old_salt = settings.ENCRYPTION_KEY_SALT

        settings.SECRET_KEY = "new-deletion-receipt-secret"
        settings.ENCRYPTION_KEY_SALT = b"new-deletion-receipt-salt"
        settings.ENCRYPTION_KEY_FALLBACKS = [
            {"secret_key": old_secret, "salt": old_salt.decode("utf-8")}
        ]

        assert client.get(status_url).status_code == 200
        receipt.refresh_from_db()

        from apps.common.encryption import hmac_digest

        assert receipt.confirmation_digest == hmac_digest(code)
        assert receipt.confirmation_digest != old_digest

        settings.ENCRYPTION_KEY_FALLBACKS = []
        assert client.get(status_url).status_code == 200

    def test_unknown_status_capability_is_404(self, client: Client) -> None:
        status_url = reverse("instagram_data_deletion_status", kwargs={"confirmation_code": "unknown"})
        response = client.get(status_url)
        assert response.status_code == 404

    def test_receipt_does_not_store_plaintext_user_id_or_confirmation_code(
        self, client: Client, instagram_app: dict[str, str], instagram_connection: ChannelConnection
    ) -> None:
        _bind_lifecycle(instagram_connection)
        response = _post(client, reverse("instagram_data_deletion"), _signed_request())
        code = response.json()["confirmation_code"]

        with db_connection.cursor() as cursor:
            cursor.execute(
                "SELECT confirmation_digest, platform, deleted_connections "
                "FROM channels_meta_data_deletion_receipt"
            )
            raw = repr(cursor.fetchone())

        assert code not in raw
        assert META_APP_USER_ID not in raw


@pytest.mark.django_db
class TestOrganizationScopedCallbacks:
    def _configure_org_app(self, tenancy: Tenancy, *, fixture_value: str = "org-meta-secret") -> None:
        org_platform_credential(
            tenancy,
            Platform.INSTAGRAM.value,
            client_id=f"org-app-{tenancy.slug}",
            client_secret=fixture_value,
        )

    def test_byo_callback_uses_the_org_secret_even_when_env_app_is_configured(
        self,
        client: Client,
        instagram_app: dict[str, str],
        tenancy: Tenancy,
        instagram_connection: ChannelConnection,
    ) -> None:
        self._configure_org_app(tenancy)
        _bind_lifecycle(instagram_connection)
        url = reverse(
            "instagram_organization_data_deletion",
            kwargs={"organization_id": tenancy.organization.pk},
        )

        wrong_namespace = _post(client, url, _signed_request(secret=APP_SECRET))
        assert wrong_namespace.status_code == 403
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()

        accepted = _post(client, url, _signed_request(secret="org-meta-secret"))
        assert accepted.status_code == 200
        assert not ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()

    def test_same_app_scoped_user_id_in_another_org_is_never_deleted(
        self,
        client: Client,
        instagram_app: dict[str, str],
        tenancy: Tenancy,
        other_tenancy: Tenancy,
        instagram_connection: ChannelConnection,
    ) -> None:
        self._configure_org_app(tenancy, fixture_value="first-org-secret")
        self._configure_org_app(other_tenancy, fixture_value="second-org-secret")
        _bind_lifecycle(instagram_connection)

        other = ChannelConnection.objects.create(
            workspace=other_tenancy.workspace,
            platform=Platform.INSTAGRAM,
            display_name="@other-org",
            external_id="17841400000000991",
            meta_app_scoped_user_id=META_APP_USER_ID,
        )
        url = reverse(
            "instagram_organization_data_deletion",
            kwargs={"organization_id": tenancy.organization.pk},
        )

        response = _post(client, url, _signed_request(secret="first-org-secret"))

        assert response.status_code == 200
        assert not ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()
        assert ChannelConnection.objects.unscoped().filter(pk=other.pk).exists()
        assert MetaDataDeletionReceipt.objects.get().deleted_connections == 1

    def test_byo_deauthorize_uses_the_same_org_boundary(
        self,
        client: Client,
        tenancy: Tenancy,
        instagram_connection: ChannelConnection,
    ) -> None:
        self._configure_org_app(tenancy, fixture_value="deauth-org-secret")
        _bind_lifecycle(instagram_connection)
        url = reverse(
            "instagram_organization_deauthorize",
            kwargs={"organization_id": tenancy.organization.pk},
        )

        response = _post(client, url, _signed_request(secret="deauth-org-secret"))

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert not ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()
        assert not MetaDataDeletionReceipt.objects.exists()

    def test_generic_callback_never_tries_an_organization_secret(
        self,
        client: Client,
        settings: Any,
        tenancy: Tenancy,
        instagram_connection: ChannelConnection,
    ) -> None:
        settings.PLATFORM_CREDENTIALS_FROM_ENV = {}
        self._configure_org_app(tenancy, fixture_value="org-only-secret")
        _bind_lifecycle(instagram_connection)

        response = _post(
            client,
            reverse("instagram_data_deletion"),
            _signed_request(secret="org-only-secret"),
        )

        assert response.status_code == 404
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()

    def test_org_url_never_tries_another_organizations_secret(
        self,
        client: Client,
        tenancy: Tenancy,
        other_tenancy: Tenancy,
        instagram_connection: ChannelConnection,
    ) -> None:
        self._configure_org_app(tenancy, fixture_value="target-secret")
        self._configure_org_app(other_tenancy, fixture_value="foreign-secret")
        _bind_lifecycle(instagram_connection)
        url = reverse(
            "instagram_organization_deauthorize",
            kwargs={"organization_id": tenancy.organization.pk},
        )

        response = _post(client, url, _signed_request(secret="foreign-secret"))

        assert response.status_code == 403
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()

    def test_org_callback_is_hidden_without_that_orgs_complete_credentials(
        self,
        client: Client,
        instagram_app: dict[str, str],
        tenancy: Tenancy,
        instagram_connection: ChannelConnection,
    ) -> None:
        _bind_lifecycle(instagram_connection)
        url = reverse(
            "instagram_organization_data_deletion",
            kwargs={"organization_id": tenancy.organization.pk},
        )

        response = _post(client, url, _signed_request(secret=APP_SECRET))

        assert response.status_code == 404
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()


@pytest.mark.django_db
class TestDeauthorizeCallback:
    def test_valid_deauthorize_removes_connection_without_creating_deletion_receipt(
        self, client: Client, instagram_app: dict[str, str], instagram_connection: ChannelConnection
    ) -> None:
        _bind_lifecycle(instagram_connection)
        response = _post(client, reverse("instagram_deauthorize"), _signed_request())

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert not ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()
        assert not MetaDataDeletionReceipt.objects.exists()

    def test_invalid_deauthorize_is_refused(
        self, client: Client, instagram_app: dict[str, str], instagram_connection: ChannelConnection
    ) -> None:
        _bind_lifecycle(instagram_connection)
        response = _post(client, reverse("instagram_deauthorize"), _signed_request(secret="wrong"))
        assert response.status_code == 403
        assert ChannelConnection.objects.unscoped().filter(pk=instagram_connection.pk).exists()
