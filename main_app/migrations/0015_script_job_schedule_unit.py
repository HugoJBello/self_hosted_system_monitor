from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0014_script_jobs"),
    ]

    operations = [
        migrations.AddField(
            model_name="scriptjob",
            name="schedule_unit",
            field=models.CharField(
                choices=[("minutes", "Minutes"), ("days", "Days"), ("weeks", "Weeks")],
                default="minutes",
                max_length=16,
            ),
        ),
    ]
