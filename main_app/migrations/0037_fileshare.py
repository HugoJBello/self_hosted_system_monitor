from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import file_manager_app.models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0036_fileoperation_uncompress"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="FileShare",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(db_index=True, default=file_manager_app.models._share_token, editable=False, max_length=64, unique=True)),
                ("name", models.CharField(blank=True, default="", max_length=160)),
                ("paths", models.JSONField(default=list)),
                ("public_link", models.BooleanField(default=True)),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="created_file_shares", to=settings.AUTH_USER_MODEL)),
                ("recipient", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="received_file_shares", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddField(
            model_name="fileoperation",
            name="file_share",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="download_operations", to="monitor.fileshare"),
        ),
        migrations.AddField(
            model_name="fileoperation",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="file_operations", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="UserFileAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("path", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("granted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="granted_file_accesses", to=settings.AUTH_USER_MODEL)),
                ("source_share", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="access_grants", to="monitor.fileshare")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="file_accesses", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("path",)},
        ),
        migrations.AddConstraint(model_name="userfileaccess", constraint=models.UniqueConstraint(fields=("user", "path", "source_share"), name="unique_user_file_share_access")),
    ]
