"""Migration readiness classification and deploy checks."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import migrations, models
from django.db.migrations import Migration

from apps.common.management.commands.migration_readiness import risks_for


def _migration(*operations):
    migration = Migration("0002_test", "common")
    migration.operations = list(operations)
    return migration


class TestRiskClassification:
    def test_plain_create_model_is_not_flagged(self):
        migration = _migration(
            migrations.CreateModel(
                name="Thing",
                fields=[("id", models.BigAutoField(primary_key=True))],
            )
        )
        assert risks_for(migration) == []

    def test_remove_field_is_destructive_even_when_django_can_reverse_schema(self):
        risks = risks_for(_migration(migrations.RemoveField(model_name="thing", name="old_value")))
        assert any(risk.reason == "destructive schema/data change" for risk in risks)

    def test_runpython_without_reverse_is_both_custom_and_irreversible(self):
        def forward(apps, schema_editor):
            return None

        risks = risks_for(_migration(migrations.RunPython(forward)))
        reasons = {risk.reason for risk in risks}
        assert "irreversible" in reasons
        assert "custom migration code/SQL requires review" in reasons

    def test_reversible_runsql_still_requires_manual_review(self):
        operation = migrations.RunSQL("SELECT 1", reverse_sql="SELECT 1")
        risks = risks_for(_migration(operation))
        assert {risk.reason for risk in risks} == {"custom migration code/SQL requires review"}


@pytest.mark.django_db
class TestCommandAgainstTestSchema:
    def test_fully_migrated_test_database_passes_require_clean(self):
        out = StringIO()
        call_command("migration_readiness", "--require-clean", stdout=out)
        assert "database is at all leaf migrations" in out.getvalue()
