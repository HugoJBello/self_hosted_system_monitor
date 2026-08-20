from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0007_backupjob_cloudflare_tokens"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="cloudflare_auth_home",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
