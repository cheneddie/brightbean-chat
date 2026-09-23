"""Separate the public-reply idempotency claim from delivery outcome.

Historically public_reply_sent_at was written before the provider call so a
worker retry could not post a duplicate visible comment. That was correct for
idempotency but the field name overstated what was known: a refused or timed-out
call looked sent. Existing timestamps are therefore preserved as claims and
marked legacy_unknown rather than guessed to be successful.
"""

from django.db import migrations, models
from django.db.models import F


def move_legacy_claims(apps, schema_editor):
    handled_comment = apps.get_model("flows", "HandledComment")
    handled_comment._base_manager.filter(public_reply_sent_at__isnull=False).update(
        public_reply_claimed_at=F("public_reply_sent_at"),
        public_reply_sent_at=None,
        public_reply_status="legacy_unknown",
        public_reply_error="",
    )


def restore_legacy_shape(apps, schema_editor):
    handled_comment = apps.get_model("flows", "HandledComment")
    handled_comment._base_manager.filter(
        public_reply_status="legacy_unknown",
        public_reply_sent_at__isnull=True,
        public_reply_claimed_at__isnull=False,
    ).update(public_reply_sent_at=F("public_reply_claimed_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("flows", "0006_flowimport"),
    ]

    operations = [
        migrations.AddField(
            model_name="handledcomment",
            name="public_reply_claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="handledcomment",
            name="public_reply_error",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="handledcomment",
            name="public_reply_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("claimed", "Claimed"),
                    ("sent", "Sent"),
                    ("failed", "Failed"),
                    ("legacy_unknown", "Legacy outcome unknown"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.RunPython(move_legacy_claims, restore_legacy_shape),
        migrations.AddConstraint(
            model_name="handledcomment",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        public_reply_status="",
                        public_reply_claimed_at__isnull=True,
                        public_reply_sent_at__isnull=True,
                    )
                    | models.Q(
                        public_reply_status="claimed",
                        public_reply_claimed_at__isnull=False,
                        public_reply_sent_at__isnull=True,
                    )
                    | models.Q(
                        public_reply_status="failed",
                        public_reply_claimed_at__isnull=False,
                        public_reply_sent_at__isnull=True,
                    )
                    | models.Q(
                        public_reply_status="legacy_unknown",
                        public_reply_claimed_at__isnull=False,
                        public_reply_sent_at__isnull=True,
                    )
                    | models.Q(
                        public_reply_status="sent",
                        public_reply_claimed_at__isnull=False,
                        public_reply_sent_at__isnull=False,
                    )
                ),
                name="flows_hcomment_public_reply_state",
            ),
        ),
    ]
