from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("monitor", "0037_fileshare"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="FileShareAccessEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("view", "Opened share"), ("download", "Downloaded file"), ("archive", "Downloaded ZIP")], db_index=True, max_length=16)),
                ("path", models.CharField(blank=True, default="", max_length=500)),
                ("remote_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, default="", max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("share", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="access_events", to="monitor.fileshare")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="file_share_access_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        )
    ]
