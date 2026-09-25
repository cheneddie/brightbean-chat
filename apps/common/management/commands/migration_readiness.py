"""Executable pre/post-deploy migration readiness checks."""

from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor


@dataclass(frozen=True)
class MigrationRisk:
    migration: str
    operation: str
    reason: str


_DESTRUCTIVE_TYPES = (
    migrations.DeleteModel,
    migrations.RemoveField,
)

_CUSTOM_TYPES = (
    migrations.RunPython,
    migrations.RunSQL,
    migrations.SeparateDatabaseAndState,
)


def risks_for(migration: Any) -> list[MigrationRisk]:
    """Classify pending operations that require an explicit rollback decision."""
    label = f"{migration.app_label}.{migration.name}"
    risks: list[MigrationRisk] = []
    for operation in migration.operations:
        operation_name = type(operation).__name__
        reasons: list[str] = []
        if not operation.reversible:
            reasons.append("irreversible")
        if isinstance(operation, _DESTRUCTIVE_TYPES):
            reasons.append("destructive schema/data change")
        if isinstance(operation, _CUSTOM_TYPES):
            reasons.append("custom migration code/SQL requires review")
        for reason in reasons:
            risks.append(MigrationRisk(label, operation_name, reason))
    return risks


class Command(BaseCommand):
    help = (
        "Inspect the migration graph and pending plan before/after production deploys. "
        "Risky pending operations fail unless --allow-risky is explicit."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--allow-risky",
            action="store_true",
            help="Acknowledge reviewed irreversible/destructive/custom pending operations.",
        )
        parser.add_argument(
            "--require-clean",
            action="store_true",
            help="Fail when any migration is pending (post-deploy verification).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        executor = MigrationExecutor(connection)
        conflicts = executor.loader.detect_conflicts()
        if conflicts:
            rendered = "; ".join(
                f"{app}: {', '.join(sorted(names))}"
                for app, names in sorted(conflicts.items())
            )
            raise CommandError(f"Migration graph has conflicting leaf nodes: {rendered}")

        targets = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)
        backwards = [migration for migration, is_backwards in plan if is_backwards]
        if backwards:
            labels = ", ".join(f"{m.app_label}.{m.name}" for m in backwards)
            raise CommandError(f"Unexpected backwards migrations in deploy plan: {labels}")

        pending = [migration for migration, _is_backwards in plan]
        if not pending:
            self.stdout.write(self.style.SUCCESS("Migration readiness: database is at all leaf migrations."))
            return

        self.stdout.write(f"Pending migrations: {len(pending)}")
        for migration in pending:
            self.stdout.write(f"  - {migration.app_label}.{migration.name}")

        if options["require_clean"]:
            raise CommandError(
                "Pending migrations remain after deploy. Run migrate successfully before serving the new release."
            )

        risks = [risk for migration in pending for risk in risks_for(migration)]
        if risks:
            self.stdout.write(self.style.WARNING("Pending migration risk review:"))
            for risk in risks:
                self.stdout.write(
                    self.style.WARNING(
                        f"  - {risk.migration}: {risk.operation} — {risk.reason}"
                    )
                )
            if not options["allow_risky"]:
                raise CommandError(
                    "Risky pending migration operations require a verified backup/rollback plan. "
                    "Review them, then rerun with --allow-risky to acknowledge the decision."
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Migration readiness: pending plan is structurally valid. "
                "Take/verify the database backup before applying it."
            )
        )
