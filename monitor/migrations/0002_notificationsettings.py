from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_api_token",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_api_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_default_action",
            field=models.CharField(blank=True, default="notify", max_length=64),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_default_channels",
            field=models.CharField(blank=True, default="email", max_length=255),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_default_origin",
            field=models.CharField(blank=True, default="system-monitor", max_length=255),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_default_priority",
            field=models.CharField(blank=True, default="high", max_length=64),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_default_status",
            field=models.CharField(blank=True, default="warning", max_length=64),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_default_tags",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_default_user",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_public_base_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="notifications_timeout_seconds",
            field=models.PositiveIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(300),
                ],
            ),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="ntfy_base_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="ntfy_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="monitoringsettings",
            name="ntfy_topic",
            field=models.CharField(blank=True, default="notifications", max_length=255),
        ),
    ]
