from django.db import migrations, models
from django.core.validators import MaxValueValidator, MinValueValidator


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0040_monitoringsettings_system_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsettings",
            name="terminal_idle_timeout_seconds",
            field=models.PositiveIntegerField(
                default=3600,
                help_text="Maximum inactivity before an unattended web terminal is closed.",
                validators=[MinValueValidator(600), MaxValueValidator(604800)],
            ),
        ),
    ]
