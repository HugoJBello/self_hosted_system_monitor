from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0004_alert_rules_and_events"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringsettings",
            name="app_public_base_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.CreateModel(
            name="ReportRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                ("period_hours", models.PositiveIntegerField(default=24, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(720)])),
                ("cadence_hours", models.PositiveIntegerField(default=24, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(720)])),
                ("send_notifications", models.BooleanField(default=True)),
                ("notification_channels", models.CharField(blank=True, default="", max_length=255)),
                ("notification_tags", models.CharField(blank=True, default="", max_length=255)),
                ("notification_user", models.CharField(blank=True, default="", max_length=255)),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("position", "id")},
        ),
        migrations.CreateModel(
            name="ReportRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("message", models.TextField()),
                ("window_start", models.DateTimeField()),
                ("window_end", models.DateTimeField()),
                ("generated_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("sample_count", models.PositiveIntegerField(default=0)),
                ("report_data", models.JSONField(default=dict)),
                ("notification_sent", models.BooleanField(default=False)),
                ("notification_status_code", models.IntegerField(blank=True, null=True)),
                ("notification_response", models.JSONField(blank=True, null=True)),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="monitor.reportrule")),
            ],
            options={"ordering": ("-generated_at",)},
        ),
    ]
