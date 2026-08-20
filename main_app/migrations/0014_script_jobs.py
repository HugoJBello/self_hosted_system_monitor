from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0013_http_backup_jobs"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScriptJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "schedule_mode",
                    models.CharField(
                        choices=[
                            ("interval", "Recurring every N minutes"),
                            ("one_off", "Run once at a specific date and time"),
                        ],
                        default="interval",
                        max_length=16,
                    ),
                ),
                (
                    "schedule_minutes",
                    models.PositiveIntegerField(
                        default=60,
                        validators=[django.core.validators.MinValueValidator(5), django.core.validators.MaxValueValidator(43200)],
                    ),
                ),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("working_directory", models.CharField(blank=True, default="", max_length=500)),
                ("script_body", models.TextField(default="")),
                ("run_as_sudo", models.BooleanField(default=False)),
                ("sudo_password", models.CharField(blank=True, default="", max_length=255)),
                (
                    "run_timeout_seconds",
                    models.PositiveIntegerField(
                        default=7200,
                        validators=[django.core.validators.MinValueValidator(30), django.core.validators.MaxValueValidator(604800)],
                    ),
                ),
                (
                    "idle_timeout_seconds",
                    models.PositiveIntegerField(
                        default=900,
                        validators=[django.core.validators.MinValueValidator(30), django.core.validators.MaxValueValidator(86400)],
                    ),
                ),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("position", "id"),
            },
        ),
        migrations.CreateModel(
            name="ScriptJobRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "Running"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                            ("timed_out", "Timed out"),
                        ],
                        default="success",
                        max_length=16,
                    ),
                ),
                ("exit_code", models.IntegerField(default=0)),
                ("summary", models.CharField(blank=True, default="", max_length=255)),
                ("log_output", models.TextField(blank=True, default="")),
                (
                    "launched_by",
                    models.CharField(
                        choices=[("manual", "Manual"), ("scheduler", "Scheduler")],
                        default="manual",
                        max_length=16,
                    ),
                ),
                ("process_pid", models.PositiveIntegerField(blank=True, null=True)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("last_output_at", models.DateTimeField(blank=True, null=True)),
                ("stop_requested_at", models.DateTimeField(blank=True, null=True)),
                ("command_line", models.TextField(blank=True, default="")),
                ("runner_label", models.CharField(blank=True, default="", max_length=255)),
                (
                    "job",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="monitor.scriptjob"),
                ),
            ],
            options={
                "ordering": ("-started_at",),
            },
        ),
    ]
