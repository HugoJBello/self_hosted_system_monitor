from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0018_backupjob_verify_mounted_device"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="schedule_mode",
            field=models.CharField(
                choices=[
                    ("interval", "Recurring schedule"),
                    ("manual", "Run only when clicking Run now"),
                ],
                default="interval",
                max_length=16,
            ),
        ),
    ]
