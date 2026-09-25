from django.db import migrations, models
import apps.common.uuid7
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("channels", "0005_emailsuppression"),
    ]

    operations = [
        migrations.CreateModel(
            name="MetaDataDeletionReceipt",
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
                ("confirmation_digest", models.CharField(max_length=64, unique=True)),
                ("platform", models.CharField(default="instagram", max_length=32)),
                ("deleted_connections", models.PositiveSmallIntegerField(default=0)),
                ("completed_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"db_table": "channels_meta_data_deletion_receipt"},
        ),
    ]
