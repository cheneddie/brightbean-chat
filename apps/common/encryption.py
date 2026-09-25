"""AES-256-GCM encrypted model fields.

Ported near-verbatim from BrightBean Studio's ``apps/common/encryption.py``.
The key is derived from ``SECRET_KEY`` via HKDF-SHA256 salted with
``settings.ENCRYPTION_KEY_SALT``; values are stored as base64 of a 12-byte
nonce concatenated with the AES-GCM ciphertext (which carries its own tag).

The only deliberate change from Studio is the HKDF ``info`` constant, so a
key derived for Chat can never decrypt a Studio ciphertext or vice versa.

Every credential or token this project persists goes in one of these fields —
never a plain column (SECURITY-BASELINE §5).

Where a row has to be found *by* a secret rather than by its owner, use
:func:`hmac_digest` to store a deterministic sidecar column and query that. It
is keyed on ``SECRET_KEY``, so a stolen database gives up neither the values nor
the ability to recompute them without the key.

**These encrypted fields cannot be used in queryset lookups.** Every write encrypts under
a fresh random nonce, so the same plaintext produces different ciphertext every
time and ``.filter(secret=value)`` compares two unrelated strings. It does not
raise — it silently matches nothing, which reads as "no such row" and is
miserable to debug. To look a record up by a secret (resolving an inbound
webhook to its connection, say), store a separate deterministic column
alongside — an HMAC of the value under ``SECRET_KEY`` — and query that.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
from functools import lru_cache
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

# Domain separation for the derived key. Do not change: it would make every
# stored ciphertext undecryptable.
HKDF_INFO = b"brightbean-chat-field-encryption"

# Separate domain for the lookup digest, so a digest can never collide with, or
# be mistaken for, key material derived for encryption.
HKDF_DIGEST_INFO = b"brightbean-chat-lookup-digest"

NONCE_BYTES = 12


@lru_cache(maxsize=8)
def _hkdf(secret: bytes, salt: bytes) -> bytes:
    """HKDF-SHA256 over (secret, salt), memoised.

    Studio re-derives on every single field read and write, so listing a
    thousand rows with an encrypted column performs a thousand derivations of
    a key that is constant for the life of the process. Keying the cache on
    the inputs rather than memoising a no-argument function keeps
    ``override_settings`` and the ``settings`` fixture working: change either
    input and you get a different entry, not a stale key.
    """
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        info=HKDF_INFO,
    ).derive(secret)


def _normalise_salt(value: Any) -> bytes:
    if not value:
        raise ValueError(
            "ENCRYPTION_KEY_SALT must be set. Generate a random value and add it "
            "to your environment variables. This is required for secure encryption."
        )
    return value.encode("utf-8") if isinstance(value, str) else bytes(value)


def _primary_material() -> tuple[bytes, bytes]:
    return settings.SECRET_KEY.encode("utf-8"), _normalise_salt(getattr(settings, "ENCRYPTION_KEY_SALT", None))


def _fallback_materials() -> tuple[tuple[bytes, bytes], ...]:
    materials: list[tuple[bytes, bytes]] = []
    for item in getattr(settings, "ENCRYPTION_KEY_FALLBACKS", ()) or ():
        if not isinstance(item, dict):
            continue
        secret = str(item.get("secret_key") or "").encode("utf-8")
        salt_value = item.get("salt")
        if not secret or not salt_value:
            continue
        materials.append((secret, _normalise_salt(salt_value)))
    return tuple(materials)


def _derive_key() -> bytes:
    """Derive the primary 256-bit encryption key."""
    secret, salt = _primary_material()
    return _hkdf(secret, salt)


def _decryption_keys() -> tuple[bytes, ...]:
    """Primary key first, then unique previous generations."""
    pairs = (_primary_material(), *_fallback_materials())
    keys: list[bytes] = []
    for secret, salt in pairs:
        key = _hkdf(secret, salt)
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def _digest_for_material(value: str, secret: bytes, salt: bytes) -> str:
    key = _hkdf(secret, salt + HKDF_DIGEST_INFO)
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_digest(value: str) -> str:
    """The deterministic lookup digest under the current key generation."""
    secret, salt = _primary_material()
    return _digest_for_material(value, secret, salt)


def hmac_digest_candidates(value: str) -> tuple[str, ...]:
    """Current lookup digest followed by unique fallback-generation digests.

    Readers use this during key rotation so an existing opaque token remains
    valid while new writes immediately move to the primary key generation.
    """
    pairs = (_primary_material(), *_fallback_materials())
    digests: list[str] = []
    for secret, salt in pairs:
        digest = _digest_for_material(value, secret, salt)
        if digest not in digests:
            digests.append(digest)
    return tuple(digests)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded nonce+ciphertext."""
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_value(encrypted: str) -> str:
    """Decrypt with the current key, then configured previous generations."""
    raw = base64.b64decode(encrypted)
    nonce = raw[:NONCE_BYTES]
    ciphertext = raw[NONCE_BYTES:]
    last_error: InvalidTag | None = None
    for key in _decryption_keys():
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
        except InvalidTag as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise InvalidTag


class EncryptedTextField(models.TextField):
    """A TextField that encrypts its value at rest using AES-256-GCM.

    Not usable in queryset lookups — ``.filter()``/``.get()`` on this field
    silently match nothing. See the module docstring.
    """

    def get_prep_value(self, value: Any) -> str | None:
        if value is None:
            return None
        return encrypt_value(str(value))

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> str | None:
        if value is None:
            return None
        try:
            return decrypt_value(value)
        except (InvalidTag, ValueError, binascii.Error) as e:
            # Log the exception type only — never the value, which is the
            # ciphertext of a credential.
            logger.error("Failed to decrypt EncryptedTextField: %s", type(e).__name__)
            raise ValueError("Decryption failed - possibly wrong SECRET_KEY or corrupted data") from e

    def to_python(self, value: Any) -> Any:
        return value


class EncryptedJSONField(models.TextField):
    """A field that stores JSON data encrypted at rest using AES-256-GCM.

    Not usable in queryset lookups — ``.filter()``/``.get()`` on this field
    silently match nothing. See the module docstring.
    """

    def get_prep_value(self, value: Any) -> str | None:
        if value is None:
            return None
        return encrypt_value(json.dumps(value))

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:
        if value is None:
            return None
        try:
            return json.loads(decrypt_value(value))
        except (InvalidTag, ValueError, binascii.Error) as e:
            logger.error("Failed to decrypt EncryptedJSONField: %s", type(e).__name__)
            raise ValueError("Decryption failed - possibly wrong SECRET_KEY or corrupted data") from e

    def to_python(self, value: Any) -> Any:
        if isinstance(value, dict | list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                # Value is likely already-encrypted ciphertext from the DB,
                # which will be handled by from_db_value. Return as-is.
                return value
        return value
