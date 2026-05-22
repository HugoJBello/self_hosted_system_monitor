from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0006_backups"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="cloudflare_service_token_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="cloudflare_service_token_secret",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
