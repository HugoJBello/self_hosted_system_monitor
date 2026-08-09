from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0021_alter_scriptjob_schedule_minutes"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="remote_direction",
            field=models.CharField(
                choices=[
                    ("push", "Local folder to remote SSH directory"),
                    ("pull", "Remote SSH directory to local folder"),
                ],
                default="push",
                max_length=16,
            ),
        ),
    ]
