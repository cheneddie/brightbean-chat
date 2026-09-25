"""Re-encrypt recoverable encrypted fields under the current key generation."""

from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone

from apps.common.encryption import EncryptedJSONField, EncryptedTextField, hmac_digest


class Command(BaseCommand):
    help = (
        "Rewrite every recoverable EncryptedTextField/EncryptedJSONField using "
        "the current SECRET_KEY + ENCRYPTION_KEY_SALT. Configure the previous "
        "pair(s) in ENCRYPTION_KEY_FALLBACKS before running."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count affected rows without writing them.")
        parser.add_argument("--batch-size", type=int, default=200)

    def handle(self, *args: Any, **options: Any) -> None:
        fallbacks = getattr(settings, "ENCRYPTION_KEY_FALLBACKS", ()) or ()
        if not fallbacks:
            raise CommandError(
                "ENCRYPTION_KEY_FALLBACKS is empty. Add the previous secret_key/salt pair before rotating data."
            )
        batch_size = int(options["batch_size"])
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")
        dry_run = bool(options["dry_run"])

        model_count = 0
        row_count = 0
        for model in apps.get_models():
            encrypted_fields = [
                field
                for field in model._meta.local_fields
                if isinstance(field, EncryptedTextField | EncryptedJSONField)
            ]
            if not encrypted_fields:
                continue
            model_count += 1
            names = [field.name for field in encrypted_fields]
            queryset = model._base_manager.only(model._meta.pk.name, *names).order_by(model._meta.pk.name)
            count = queryset.count()
            self.stdout.write(f"{model._meta.label}: {count} row(s), fields={','.join(names)}")
            if dry_run:
                row_count += count
                continue

            for obj in queryset.iterator(chunk_size=batch_size):
                values = {name: getattr(obj, name) for name in names}
                # ChannelConnection.webhook_secret has a deterministic sidecar
                # derived from the same key generation. It is recoverable
                # because the encrypted plaintext is present on the row.
                if model._meta.label_lower == "channels.channelconnection":
                    secret = values.get("webhook_secret")
                    if isinstance(secret, str) and secret:
                        values["webhook_secret_digest"] = hmac_digest(secret)
                model._base_manager.filter(pk=obj.pk).update(**values)
                row_count += 1

        prefix = "Would rewrite" if dry_run else "Rewrote"
        self.stdout.write(self.style.SUCCESS(f"{prefix} {row_count} row(s) across {model_count} encrypted model(s)."))
        self._opaque_dependency_report()

    def _opaque_dependency_report(self) -> None:
        """Report digest-only credentials that cannot be migrated without presentation."""
        now = timezone.now()
        lines: list[str] = []

        api_key_model = apps.get_model("api", "ApiKey")
        if api_key_model is not None:
            active_keys = api_key_model._base_manager.filter(revoked_at__isnull=True).count()
            lines.append(
                f"API keys still potentially depend on fallback digests: {active_keys}. "
                "They lazy-rehash on successful authentication; rotate/revoke any never-used keys "
                "before removing fallbacks."
            )

        invitation_model = apps.get_model("members", "Invitation")
        if invitation_model is not None:
            live_invites = invitation_model._base_manager.filter(
                accepted_at__isnull=True, expires_at__gt=now
            ).count()
            lines.append(
                f"Live invitation links using digest-only tokens: {live_invites}. "
                "They remain valid through fallback lookup; resend or wait for expiry before removing fallbacks."
            )

        preview_model = apps.get_model("channels", "FlowPreviewLink")
        if preview_model is not None:
            live_previews = preview_model._base_manager.filter(expires_at__gt=now).count()
            lines.append(
                f"Live flow preview handles: {live_previews}. "
                "They lazy-rehash when claimed and otherwise expire after their short TTL."
            )

        for line in lines:
            self.stdout.write(self.style.WARNING(line))
