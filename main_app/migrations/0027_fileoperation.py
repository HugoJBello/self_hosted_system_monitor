from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0026_monitoringsettings_file_manager_start_path"),
    ]

    operations = [
        migrations.CreateModel(
            name="FileOperation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("copy", "Copy"), ("move", "Move"), ("delete", "Delete"), ("upload", "Upload"), ("download", "Download")], db_index=True, max_length=16)),
                ("status", models.CharField(choices=[("running", "Running"), ("paused", "Paused"), ("success", "Success"), ("failed", "Failed"), ("cancelled", "Cancelled")], db_index=True, default="running", max_length=16)),
                ("sources", models.JSONField(blank=True, default=list)),
                ("completed_sources", models.JSONField(blank=True, default=list)),
                ("destination_path", models.CharField(blank=True, default="", max_length=500)),
                ("current_path", models.CharField(blank=True, default="", max_length=500)),
                ("total_count", models.PositiveIntegerField(default=0)),
                ("processed_count", models.PositiveIntegerField(default=0)),
                ("summary", models.CharField(blank=True, default="", max_length=255)),
                ("log_output", models.TextField(blank=True, default="")),
                ("process_pid", models.PositiveIntegerField(blank=True, null=True)),
                ("runner_label", models.CharField(blank=True, default="", max_length=255)),
                ("pause_requested_at", models.DateTimeField(blank=True, null=True)),
                ("cancel_requested_at", models.DateTimeField(blank=True, null=True)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("-started_at",),
            },
        ),
    ]
