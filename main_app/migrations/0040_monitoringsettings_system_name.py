from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0039_userfeatureaccess"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsettings",
            name="system_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Friendly name for this deployment. The monitored host name is used when empty.",
                max_length=255,
            ),
        ),
    ]
