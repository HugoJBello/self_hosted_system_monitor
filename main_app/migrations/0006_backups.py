from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0005_reports"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                ("source_path", models.CharField(help_text="Host path, for example /home/user/Documents", max_length=500)),
                ("schedule_minutes", models.PositiveIntegerField(default=60, validators=[django.core.validators.MinValueValidator(5), django.core.validators.MaxValueValidator(43200)])),
                ("remote_host", models.CharField(max_length=255)),
                ("remote_user", models.CharField(max_length=255)),
                ("remote_dir", models.CharField(max_length=500)),
                ("ssh_port", models.PositiveIntegerField(default=22, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(65535)])),
                ("connection_mode", models.CharField(choices=[("direct", "Direct SSH"), ("cloudflare", "Cloudflare Access SSH")], default="direct", max_length=32)),
                ("auth_mode", models.CharField(choices=[("key", "SSH key only"), ("password_file", "Password file"), ("password_value", "Saved password")], default="key", max_length=32)),
                ("password_file_path", models.CharField(blank=True, default="", max_length=500)),
                ("ssh_password", models.CharField(blank=True, default="", max_length=255)),
                ("public_key_path", models.CharField(blank=True, default="", max_length=500)),
                ("install_public_key", models.BooleanField(default=False)),
                ("delete_enabled", models.BooleanField(default=True)),
                ("max_size", models.CharField(blank=True, default="100m", max_length=32)),
                ("exclude_patterns", models.TextField(blank=True, default="")),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("position", "id")},
        ),
        migrations.CreateModel(
            name="BackupRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("success", "Success"), ("failed", "Failed")], default="success", max_length=16)),
                ("exit_code", models.IntegerField(default=0)),
                ("summary", models.CharField(blank=True, default="", max_length=255)),
                ("log_output", models.TextField(blank=True, default="")),
                ("created_remote_dir", models.BooleanField(default=False)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="monitor.backupjob")),
            ],
            options={"ordering": ("-started_at",)},
        ),
    ]
