"""Meta Dashboard readiness command contracts."""

from io import StringIO
from typing import Any
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.common.platforms import Platform
from tests.support import Tenancy, org_platform_credential

APP_SECRET = "meta-readiness-secret"
VERIFY_TOKEN = "meta-readiness-verify"


def _ready_public_settings(settings: Any) -> None:
    settings.APP_URL = "https://chat.example.test"
    settings.PRIVACY_POLICY_URL = "https://www.example.test/privacy"
    settings.TERMS_OF_SERVICE_URL = "https://www.example.test/terms"
    settings.DATA_DELETION_INSTRUCTIONS_URL = "https://www.example.test/data-deletion"


def _deployment_app(settings: Any) -> None:
    settings.PLATFORM_CREDENTIALS_FROM_ENV = {
        Platform.INSTAGRAM.value: {
            "client_id": "deployment-app",
            "client_secret": APP_SECRET,
            "verify_token": VERIFY_TOKEN,
        }
    }


@pytest.mark.django_db
class TestMetaAcceptanceReadiness:
    def test_deployment_mode_prints_exact_values_without_secrets(self, settings: Any) -> None:
        _ready_public_settings(settings)
        _deployment_app(settings)
        out = StringIO()

        call_command("meta_acceptance_readiness", "--strict", stdout=out)

        body = out.getvalue()
        assert "Mode: deployment app" in body
        assert "https://chat.example.test/channels/instagram/callback/" in body
        assert "https://chat.example.test/meta/instagram/deauthorize/" in body
        assert "https://chat.example.test/meta/instagram/data-deletion/" in body
        assert "instagram_business_basic" in body
        assert "instagram_business_manage_messages" in body
        assert "instagram_business_manage_comments" in body
        assert "Local readiness: PASS" in body
        assert APP_SECRET not in body
        assert VERIFY_TOKEN not in body

    def test_strict_mode_fails_on_local_blockers(self, settings: Any) -> None:
        _deployment_app(settings)
        settings.APP_URL = "http://chat.example.test"
        settings.PRIVACY_POLICY_URL = ""
        settings.TERMS_OF_SERVICE_URL = ""
        settings.DATA_DELETION_INSTRUCTIONS_URL = ""

        with pytest.raises(CommandError, match="APP_URL"):
            call_command("meta_acceptance_readiness", "--strict", stdout=StringIO())

    def test_byo_mode_uses_organization_callbacks_and_does_not_print_secret(
        self,
        tenancy: Tenancy,
        settings: Any,
    ) -> None:
        _ready_public_settings(settings)
        settings.PLATFORM_CREDENTIALS_FROM_ENV = {Platform.INSTAGRAM.value: {"verify_token": VERIFY_TOKEN}}
        org_platform_credential(
            tenancy,
            Platform.INSTAGRAM.value,
            client_id="org-app",
            client_secret=APP_SECRET,
        )
        out = StringIO()

        call_command(
            "meta_acceptance_readiness",
            "--organization",
            str(tenancy.organization.pk),
            "--strict",
            stdout=out,
        )

        body = out.getvalue()
        org_id = str(tenancy.organization.pk)
        assert "Mode: organization/BYO" in body
        assert f"/meta/instagram/organization/{org_id}/deauthorize/" in body
        assert f"/meta/instagram/organization/{org_id}/data-deletion/" in body
        assert "Deployment app does not shadow BYO: organization credential will be used" in body
        assert "Local readiness: PASS" in body
        assert APP_SECRET not in body
        assert VERIFY_TOKEN not in body

    def test_byo_mode_fails_when_deployment_app_shadows_it(self, tenancy: Tenancy, settings: Any) -> None:
        _ready_public_settings(settings)
        _deployment_app(settings)
        org_platform_credential(
            tenancy,
            Platform.INSTAGRAM.value,
            client_id="org-app",
            client_secret="org-readiness-secret",
        )

        with pytest.raises(CommandError, match="Deployment app does not shadow BYO"):
            call_command(
                "meta_acceptance_readiness",
                "--organization",
                str(tenancy.organization.pk),
                "--strict",
                stdout=StringIO(),
            )

    def test_unknown_organization_is_refused(self, settings: Any) -> None:
        _ready_public_settings(settings)
        settings.PLATFORM_CREDENTIALS_FROM_ENV = {Platform.INSTAGRAM.value: {"verify_token": VERIFY_TOKEN}}

        with pytest.raises(CommandError, match="does not exist"):
            call_command(
                "meta_acceptance_readiness",
                "--organization",
                str(uuid4()),
                stdout=StringIO(),
            )
