from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0003_remove_unused_notification_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlertRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                ("severity", models.CharField(choices=[("info", "Info"), ("warning", "Warning"), ("critical", "Critical")], default="warning", max_length=16)),
                ("metric", models.CharField(choices=[("cpu_percent", "CPU percent"), ("memory_percent", "Memory percent"), ("swap_percent", "Swap percent"), ("disk_percent", "Disk percent"), ("load_avg_1", "Load average 1m"), ("load_avg_5", "Load average 5m"), ("load_avg_15", "Load average 15m"), ("network_sent_rate_kbps", "Network sent kbps"), ("network_recv_rate_kbps", "Network received kbps"), ("process_count_total", "Total processes"), ("process_count_running", "Running processes"), ("process_count_zombie", "Zombie processes")], max_length=64)),
                ("evaluation_mode", models.CharField(choices=[("current", "Current value"), ("avg", "Average in window"), ("max", "Maximum in window"), ("min", "Minimum in window")], default="current", max_length=16)),
                ("comparator", models.CharField(choices=[("gt", ">"), ("gte", ">="), ("lt", "<"), ("lte", "<=")], default="gte", max_length=8)),
                ("threshold", models.FloatField(default=80)),
                ("window_minutes", models.PositiveIntegerField(default=5)),
                ("min_occurrences", models.PositiveIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10000)])),
                ("cooldown_minutes", models.PositiveIntegerField(default=30, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(10080)])),
                ("notifications_enabled", models.BooleanField(default=True)),
                ("notification_channels", models.CharField(blank=True, default="", max_length=255)),
                ("notification_tags", models.CharField(blank=True, default="", max_length=255)),
                ("notification_user", models.CharField(blank=True, default="", max_length=255)),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("position", "id")},
        ),
        migrations.CreateModel(
            name="AlertEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("message", models.TextField()),
                ("severity", models.CharField(choices=[("info", "Info"), ("warning", "Warning"), ("critical", "Critical")], max_length=16)),
                ("metric", models.CharField(max_length=64)),
                ("comparator", models.CharField(max_length=8)),
                ("threshold", models.FloatField()),
                ("evaluated_value", models.FloatField()),
                ("matching_count", models.PositiveIntegerField(default=0)),
                ("sample_count", models.PositiveIntegerField(default=1)),
                ("window_minutes", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("triggered_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("notification_sent", models.BooleanField(default=False)),
                ("notification_status_code", models.IntegerField(blank=True, null=True)),
                ("notification_response", models.JSONField(blank=True, null=True)),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="monitor.alertrule")),
                ("snapshot", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alert_events", to="monitor.systemsnapshot")),
            ],
            options={"ordering": ("-triggered_at",)},
        ),
    ]
