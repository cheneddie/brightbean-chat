"""Meta callback verification and account-level deletion helpers.

These callbacks run before any workspace is known. Therefore the generic
deployment URLs may only use complete deployment-level Instagram app
credentials. Organization-specific Meta apps need organization-scoped callback
URLs; guessing by trying every stored app secret would be both expensive and a
poor tenancy boundary.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

from django.db import IntegrityError, transaction

from apps.channels.models import ChannelConnection, MetaDataDeletionReceipt
from apps.common.encryption import hmac_digest
from apps.common.platforms import Platform
from apps.credentials.models import PlatformCredential, derive_is_configured
from apps.credentials.resolution import SOURCE_ENV, resolve_platform_credentials

logger = logging.getLogger(__name__)

MAX_SIGNED_REQUEST_CHARS = 16_384
CONFIRMATION_BYTES = 24


def deployment_instagram_app_secret() -> str:
    """The deployment Meta app secret, or empty when generic callbacks are unsafe."""
    resolution = resolve_platform_credentials(Platform.INSTAGRAM.value)
    if resolution.source != SOURCE_ENV:
        return ""
    value = resolution.credentials.get("client_secret") or resolution.credentials.get("app_secret")
    return value if isinstance(value, str) and value else ""


def organization_instagram_app_secret(organization_id: Any) -> str:
    """Return exactly one organization's Instagram app secret, never a fallback.

    Organization-scoped lifecycle callback URLs carry the organization context
    precisely so signature verification can select one secret before trusting
    the signed payload. Using the normal env -> organization resolution chain
    here would be wrong: a configured deployment app would shadow the BYO app
    whose callback URL Meta actually invoked.
    """
    row = (
        PlatformCredential.objects.for_org(organization_id)
        .filter(platform=Platform.INSTAGRAM.value)
        .first()
    )
    if row is None:
        return ""
    credentials = dict(row.credentials or {})  # type: ignore[arg-type]
    if not derive_is_configured(Platform.INSTAGRAM.value, credentials):
        return ""
    value = credentials.get("client_secret") or credentials.get("app_secret")
    return value if isinstance(value, str) and value else ""


def parse_signed_request(signed_request: str, *, app_secret: str) -> dict[str, Any] | None:
    """Verify and decode Meta signed_request without logging either segment."""
    if not signed_request or len(signed_request) > MAX_SIGNED_REQUEST_CHARS:
        return None
    try:
        encoded_signature, encoded_payload = signed_request.split(".", 1)
    except ValueError:
        return None
    if not encoded_signature or not encoded_payload:
        return None

    try:
        signature = _b64url_decode(encoded_signature)
        payload_bytes = _b64url_decode(encoded_payload)
    except (ValueError, binascii.Error):
        return None

    expected = hmac.new(
        app_secret.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("algorithm") or "").upper() != "HMAC-SHA256":
        return None
    user_id = payload.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, (str, int)):
        return None
    user_text = str(user_id).strip()
    if not user_text or len(user_text) > 200:
        return None
    return {**payload, "user_id": user_text}


def delete_connected_instagram_account(user_id: str, *, organization_id: Any = None) -> int:
    """Delete Instagram connections belonging to one Meta lifecycle identity.

    ``signed_request.user_id`` is app-scoped, not a routing key. Generic
    deployment callbacks operate inside one deployment Meta App namespace and
    therefore may remove every matching connection across organizations.

    BYO Meta Apps are a different namespace per organization. Their callback
    passes ``organization_id``, which is a mandatory deletion boundary: an
    app-scoped id from organization A must never delete a numerically identical
    id that organization B received from a different Meta App.

    Existing foreign-key cascades remove each connection's conversations,
    trigger bindings and channel identities. CRM Contact rows are not globally
    erased: those are third parties who messaged the connected businesses.
    """
    connections = ChannelConnection.objects.unscoped().filter(
        platform=Platform.INSTAGRAM.value,
        meta_app_scoped_user_id=user_id,
    )
    if organization_id is not None:
        connections = connections.filter(workspace__organization_id=organization_id)
    count = connections.count()
    if count:
        connections.delete()
    return int(count)


def create_deletion_receipt(*, deleted_connections: int) -> tuple[str, MetaDataDeletionReceipt]:
    """Mint a one-time confirmation code while storing only its HMAC digest."""
    for _attempt in range(3):
        code = secrets.token_urlsafe(CONFIRMATION_BYTES)
        try:
            with transaction.atomic():
                receipt = MetaDataDeletionReceipt.objects.create(
                    confirmation_digest=hmac_digest(code),
                    platform=Platform.INSTAGRAM.value,
                    deleted_connections=deleted_connections,
                )
            return code, receipt
        except IntegrityError:
            continue
    raise RuntimeError("Could not mint a unique data-deletion confirmation code")


def receipt_for_code(code: str) -> MetaDataDeletionReceipt | None:
    """Resolve a public status capability without storing the plaintext code."""
    if not code or len(code) > 200:
        return None
    return MetaDataDeletionReceipt.objects.filter(confirmation_digest=hmac_digest(code)).first()


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode((value + padding).encode("ascii"), altchars=b"-_", validate=True)
