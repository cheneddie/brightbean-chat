from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("flows", "0006_flowimport"),
    ]

    operations = [
        migrations.AddField(
            model_name="flowexecution",
            name="private_reply_claim",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="flows.handledcomment",
            ),
        ),
    ]
