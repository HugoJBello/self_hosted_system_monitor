from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0002_notificationsettings"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="monitoringsettings",
            name="notifications_public_base_url",
        ),
        migrations.RemoveField(
            model_name="monitoringsettings",
            name="ntfy_base_url",
        ),
        migrations.RemoveField(
            model_name="monitoringsettings",
            name="ntfy_enabled",
        ),
        migrations.RemoveField(
            model_name="monitoringsettings",
            name="ntfy_topic",
        ),
    ]
