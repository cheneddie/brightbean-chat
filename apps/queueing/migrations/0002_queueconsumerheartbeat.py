from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("queueing", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="QueueConsumerHeartbeat",
            fields=[
                (
                    "key",
                    models.CharField(
                        default="queue",
                        editable=False,
                        max_length=32,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("source", models.CharField(max_length=32)),
                ("last_seen_at", models.DateTimeField()),
            ],
            options={"db_table": "queueing_consumer_heartbeat"},
        ),
    ]
