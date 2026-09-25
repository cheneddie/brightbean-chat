import apps.common.uuid7
import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inbox", "0003_deferred_work_idempotency"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationAudit",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=apps.common.uuid7.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "event",
                    models.CharField(
                        choices=[
                            ("assigned", "Assigned"),
                            ("unassigned", "Unassigned"),
                            ("automation_paused", "Automation paused"),
                            ("automation_resumed", "Automation resumed"),
                            ("state_opened", "Reopened"),
                            ("state_done", "Marked done"),
                            ("human_handoff", "Human handoff"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("human", "Human"), ("system", "System")],
                        max_length=16,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="conversation_audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("actor_label", models.CharField(blank=True, default="", max_length=160)),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audit_events",
                        to="messaging.conversation",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)ss",
                        to="workspaces.workspace",
                    ),
                ),
            ],
            options={
                "db_table": "inbox_conversation_audit",
                "ordering": ["-created_at", "-id"],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name="conversationaudit",
            index=models.Index(
                fields=["workspace", "conversation", "-created_at"],
                name="convaudit_ws_conv_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="conversationaudit",
            index=models.Index(
                fields=["workspace", "event", "-created_at"],
                name="convaudit_ws_event_created_idx",
            ),
        ),
    ]
