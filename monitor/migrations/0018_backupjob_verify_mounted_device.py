from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0017_alter_scriptjob_schedule_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="verify_mounted_device",
            field=models.BooleanField(default=False),
        ),
    ]
