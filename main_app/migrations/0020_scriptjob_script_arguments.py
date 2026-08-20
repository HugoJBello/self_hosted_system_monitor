from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0019_backupjob_schedule_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="scriptjob",
            name="script_arguments",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
