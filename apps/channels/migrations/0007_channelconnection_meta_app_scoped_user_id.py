from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("channels", "0006_metadatadeletionreceipt"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelconnection",
            name="meta_app_scoped_user_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Meta lifecycle identity from OAuth code exchange. Instagram deauthorize/data-deletion "
                    "callbacks resolve by this value, never by external_id."
                ),
                max_length=200,
            ),
        ),
        migrations.AddIndex(
            model_name="channelconnection",
            index=models.Index(
                fields=["platform", "meta_app_scoped_user_id"],
                name="channelconn_meta_user_idx",
            ),
        ),
    ]
