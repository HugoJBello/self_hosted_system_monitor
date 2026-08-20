import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0020_scriptjob_script_arguments"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scriptjob",
            name="schedule_minutes",
            field=models.PositiveIntegerField(
                default=60,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(43200),
                ],
            ),
        ),
    ]
