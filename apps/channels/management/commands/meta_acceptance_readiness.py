"""Deployment-local readiness checks for Meta production acceptance.

This command intentionally cannot claim Meta App Review or real-account E2E
success. It answers the part BrightBean can prove locally: exact callback URLs,
scope names, credential shape, legal URL shape, webhook verification token and
the credential-resolution mode an operator is about to submit to Meta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from apps.channels import instagram_oauth
from apps.common.platforms import Platform
from apps.credentials.models import PlatformCredential, derive_is_configured
from apps.credentials.resolution import env_credentials
from apps.organizations.models import Organization


@dataclass(frozen=True)
class ReadinessItem:
    label: str
    ok: bool
    detail: str


def _absolute(path: str) -> str:
    return urljoin(settings.APP_URL.rstrip("/") + "/", path.lstrip("/"))


def _public_https(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and parsed.username is None and parsed.password is None


def _legal_items() -> list[ReadinessItem]:
    items: list[ReadinessItem] = []
    for setting_name, label in (
        ("PRIVACY_POLICY_URL", "Privacy Policy"),
        ("TERMS_OF_SERVICE_URL", "Terms of Service"),
        ("DATA_DELETION_INSTRUCTIONS_URL", "Data Deletion Instructions"),
    ):
        value = str(getattr(settings, setting_name, "") or "").strip()
        items.append(
            ReadinessItem(
                label,
                _public_https(value),
                value or f"{setting_name} is not configured",
            )
        )
    return items


def _deployment_items() -> list[ReadinessItem]:
    credentials = env_credentials(Platform.INSTAGRAM.value)
    app_ready = derive_is_configured(Platform.INSTAGRAM.value, credentials)
    verify_token = str(credentials.get("verify_token") or "").strip()
    return [
        ReadinessItem("APP_URL", _public_https(settings.APP_URL), settings.APP_URL),
        ReadinessItem(
            "Deployment Instagram app",
            app_ready,
            "client id + client secret configured" if app_ready else "missing complete deployment app credentials",
        ),
        ReadinessItem(
            "Instagram webhook verify token",
            bool(verify_token),
            "configured" if verify_token else "PLATFORM_INSTAGRAM_VERIFY_TOKEN is not configured",
        ),
        *_legal_items(),
    ]


def _organization_items(organization: Organization) -> list[ReadinessItem]:
    env_app = env_credentials(Platform.INSTAGRAM.value)
    env_ready = derive_is_configured(Platform.INSTAGRAM.value, env_app)
    row = PlatformCredential.objects.for_org(organization).filter(platform=Platform.INSTAGRAM.value).first()
    credentials: dict[str, Any] = dict(row.credentials or {}) if row is not None else {}  # type: ignore[arg-type]
    org_ready = derive_is_configured(Platform.INSTAGRAM.value, credentials)

    return [
        ReadinessItem("APP_URL", _public_https(settings.APP_URL), settings.APP_URL),
        ReadinessItem(
            "Organization Instagram app",
            org_ready,
            "client id + client secret configured" if org_ready else "missing complete organization app credentials",
        ),
        ReadinessItem(
            "Deployment app does not shadow BYO",
            not env_ready,
            (
                "organization credential will be used"
                if not env_ready
                else "deployment Instagram app is complete and wins OAuth resolution; remove it to use this BYO app"
            ),
        ),
        ReadinessItem(
            "Instagram webhook verify token",
            bool(str(env_app.get("verify_token") or "").strip()),
            (
                "configured"
                if str(env_app.get("verify_token") or "").strip()
                else "PLATFORM_INSTAGRAM_VERIFY_TOKEN is not configured"
            ),
        ),
        *_legal_items(),
    ]


class Command(BaseCommand):
    help = (
        "Print exact Meta Dashboard callback values and fail on deployment-local blockers. "
        "This never claims App Review, Business Verification or real-account acceptance."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--organization",
            type=UUID,
            help="Check one organization/BYO Meta App instead of deployment-level app credentials.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit non-zero when any deployment-local readiness item is not ready.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        organization_id: UUID | None = options["organization"]
        organization: Organization | None = None
        if organization_id is not None:
            organization = Organization.objects.filter(pk=organization_id).first()
            if organization is None:
                raise CommandError(f"Organization {organization_id} does not exist.")

        self.stdout.write("Meta production acceptance — deployment-local readiness")
        self.stdout.write(f"Mode: {'organization/BYO' if organization is not None else 'deployment app'}")
        if organization is not None:
            self.stdout.write(f"Organization: {organization.name} ({organization.pk})")

        self.stdout.write("")
        self.stdout.write("Instagram OAuth")
        self.stdout.write(f"  Redirect URI: {_absolute(reverse('instagram_callback'))}")
        self.stdout.write(f"  Scopes: {', '.join(instagram_oauth.SCOPES)}")

        self.stdout.write("")
        self.stdout.write("Meta lifecycle callbacks")
        if organization is None:
            self.stdout.write(f"  Deauthorize callback: {_absolute(reverse('instagram_deauthorize'))}")
            self.stdout.write(f"  Data deletion callback: {_absolute(reverse('instagram_data_deletion'))}")
        else:
            self.stdout.write(
                "  Deauthorize callback: "
                + _absolute(reverse("instagram_organization_deauthorize", kwargs={"organization_id": organization.pk}))
            )
            self.stdout.write(
                "  Data deletion callback: "
                + _absolute(
                    reverse("instagram_organization_data_deletion", kwargs={"organization_id": organization.pk})
                )
            )
        self.stdout.write(
            "  Deletion status pattern: "
            + _absolute(reverse("instagram_data_deletion_status", kwargs={"confirmation_code": "CONFIRMATION_CODE"}))
        )

        items = _organization_items(organization) if organization is not None else _deployment_items()

        self.stdout.write("")
        self.stdout.write("Local gates")
        for item in items:
            prefix = "PASS" if item.ok else "BLOCK"
            self.stdout.write(f"  [{prefix}] {item.label}: {item.detail}")

        self.stdout.write("")
        self.stdout.write("External Meta gates — always manual")
        for line in (
            "Meta Dashboard accepts the OAuth, deauthorize and data-deletion callback URLs.",
            "Required Instagram permissions receive Advanced Access / App Review approval.",
            "Human Agent is separately approved if the 24h–7d human-reply path is offered.",
            "Business Verification is completed when Meta requires it.",
            "A Professional Account whose owner has no app role completes real OAuth/webhook/send E2E.",
            "Real deauthorize and data-deletion callbacks are observed end to end.",
            "Organization/BYO mode is tested with that real BYO Meta App before it is called production accepted.",
        ):
            self.stdout.write(f"  [MANUAL] {line}")

        blockers = [item for item in items if not item.ok]
        if blockers and options["strict"]:
            labels = ", ".join(item.label for item in blockers)
            raise CommandError(f"Meta acceptance has deployment-local blockers: {labels}")

        if blockers:
            self.stdout.write(self.style.WARNING(f"Local readiness: {len(blockers)} blocker(s) remain."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Local readiness: PASS. This is not Meta production acceptance; complete the manual gates above."
                )
            )
