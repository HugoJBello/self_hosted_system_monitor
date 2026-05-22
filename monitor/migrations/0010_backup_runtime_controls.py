from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0009_backuprun_running_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="idle_timeout_seconds",
            field=models.PositiveIntegerField(
                default=900,
                validators=[MinValueValidator(30), MaxValueValidator(86400)],
            ),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="run_timeout_seconds",
            field=models.PositiveIntegerField(
                default=7200,
                validators=[MinValueValidator(60), MaxValueValidator(604800)],
            ),
        ),
        migrations.AddField(
            model_name="backuprun",
            name="command_line",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="backuprun",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backuprun",
            name="last_output_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backuprun",
            name="launched_by",
            field=models.CharField(
                choices=[("manual", "Manual"), ("scheduler", "Scheduler")],
                default="manual",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="backuprun",
            name="process_pid",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backuprun",
            name="runner_label",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="backuprun",
            name="stop_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="backuprun",
            name="status",
            field=models.CharField(
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
    ]
