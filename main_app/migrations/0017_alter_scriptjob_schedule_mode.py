from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0016_systemsnapshot_memory_breakdown"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scriptjob",
            name="schedule_mode",
            field=models.CharField(
                choices=[
                    ("manual", "Run only when clicking Run now"),
                    ("interval", "Recurring schedule"),
                    ("one_off", "Run once at a specific date and time"),
                ],
                default="interval",
                max_length=16,
            ),
        ),
    ]
