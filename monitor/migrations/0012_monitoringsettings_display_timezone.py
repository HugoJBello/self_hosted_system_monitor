from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0011_local_backup_jobs"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsettings",
            name="display_time_mode",
            field=models.CharField(
                choices=[
                    ("browser", "Browser locale and timezone"),
                    ("fixed", "Fixed timezone for all users"),
                ],
                default="browser",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="display_timezone",
            field=models.CharField(default="Europe/Madrid", max_length=64),
        ),
    ]
