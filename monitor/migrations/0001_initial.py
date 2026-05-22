from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MonitoringSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "sample_interval_seconds",
                    models.PositiveIntegerField(
                        default=60,
                        validators=[
                            django.core.validators.MinValueValidator(10),
                            django.core.validators.MaxValueValidator(3600),
                        ],
                    ),
                ),
                (
                    "top_process_limit",
                    models.PositiveIntegerField(
                        default=8,
                        validators=[
                            django.core.validators.MinValueValidator(3),
                            django.core.validators.MaxValueValidator(30),
                        ],
                    ),
                ),
                (
                    "history_retention_days",
                    models.PositiveIntegerField(
                        default=30,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(3650),
                        ],
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="SystemSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("captured_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("hostname", models.CharField(max_length=255)),
                ("platform_label", models.CharField(max_length=255)),
                ("boot_time", models.DateTimeField()),
                ("uptime_seconds", models.BigIntegerField()),
                ("cpu_percent", models.FloatField()),
                ("cpu_count_logical", models.PositiveIntegerField()),
                ("cpu_count_physical", models.PositiveIntegerField(default=0)),
                ("load_avg_1", models.FloatField(default=0)),
                ("load_avg_5", models.FloatField(default=0)),
                ("load_avg_15", models.FloatField(default=0)),
                ("per_cpu_percent", models.JSONField(default=list)),
                ("memory_total_mb", models.FloatField()),
                ("memory_used_mb", models.FloatField()),
                ("memory_available_mb", models.FloatField()),
                ("memory_percent", models.FloatField()),
                ("swap_total_mb", models.FloatField(default=0)),
                ("swap_used_mb", models.FloatField(default=0)),
                ("swap_percent", models.FloatField(default=0)),
                ("disk_total_gb", models.FloatField()),
                ("disk_used_gb", models.FloatField()),
                ("disk_free_gb", models.FloatField()),
                ("disk_percent", models.FloatField()),
                ("network_sent_mb", models.FloatField(default=0)),
                ("network_recv_mb", models.FloatField(default=0)),
                ("network_sent_rate_kbps", models.FloatField(default=0)),
                ("network_recv_rate_kbps", models.FloatField(default=0)),
                ("process_count_total", models.PositiveIntegerField(default=0)),
                ("process_count_running", models.PositiveIntegerField(default=0)),
                ("process_count_sleeping", models.PositiveIntegerField(default=0)),
                ("process_count_stopped", models.PositiveIntegerField(default=0)),
                ("process_count_zombie", models.PositiveIntegerField(default=0)),
                ("process_status_counts", models.JSONField(default=dict)),
                ("disk_devices", models.JSONField(default=list)),
            ],
            options={"ordering": ("-captured_at",)},
        ),
        migrations.CreateModel(
            name="ProcessSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pid", models.PositiveIntegerField()),
                ("name", models.CharField(max_length=255)),
                ("username", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(blank=True, max_length=64)),
                ("cpu_percent", models.FloatField(default=0)),
                ("memory_percent", models.FloatField(default=0)),
                ("memory_rss_mb", models.FloatField(default=0)),
                ("threads", models.PositiveIntegerField(default=0)),
                ("command", models.TextField(blank=True)),
                (
                    "snapshot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="processes",
                        to="monitor.systemsnapshot",
                    ),
                ),
            ],
            options={"ordering": ("-cpu_percent", "-memory_percent", "pid")},
        ),
    ]

