from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class SystemSnapshot(models.Model):
    captured_at = models.DateTimeField(default=timezone.now, db_index=True)
    hostname = models.CharField(max_length=255)
    platform_label = models.CharField(max_length=255)
    boot_time = models.DateTimeField()
    uptime_seconds = models.BigIntegerField()

    cpu_percent = models.FloatField()
    cpu_count_logical = models.PositiveIntegerField()
    cpu_count_physical = models.PositiveIntegerField(default=0)
    load_avg_1 = models.FloatField(default=0)
    load_avg_5 = models.FloatField(default=0)
    load_avg_15 = models.FloatField(default=0)
    per_cpu_percent = models.JSONField(default=list)

    memory_total_mb = models.FloatField()
    memory_used_mb = models.FloatField()
    memory_available_mb = models.FloatField()
    memory_cached_mb = models.FloatField(default=0)
    memory_buffers_mb = models.FloatField(default=0)
    memory_slab_mb = models.FloatField(default=0)
    memory_percent = models.FloatField()

    swap_total_mb = models.FloatField(default=0)
    swap_used_mb = models.FloatField(default=0)
    swap_percent = models.FloatField(default=0)

    disk_total_gb = models.FloatField()
    disk_used_gb = models.FloatField()
    disk_free_gb = models.FloatField()
    disk_percent = models.FloatField()

    network_sent_mb = models.FloatField(default=0)
    network_recv_mb = models.FloatField(default=0)
    network_sent_rate_kbps = models.FloatField(default=0)
    network_recv_rate_kbps = models.FloatField(default=0)

    process_count_total = models.PositiveIntegerField(default=0)
    process_count_running = models.PositiveIntegerField(default=0)
    process_count_sleeping = models.PositiveIntegerField(default=0)
    process_count_stopped = models.PositiveIntegerField(default=0)
    process_count_zombie = models.PositiveIntegerField(default=0)

    process_status_counts = models.JSONField(default=dict)
    disk_devices = models.JSONField(default=list)

    class Meta:
        app_label = "monitor"
        ordering = ("-captured_at",)

    @property
    def memory_reclaimable_mb(self):
        return round(float(self.memory_cached_mb or 0) + float(self.memory_buffers_mb or 0), 2)

    def __str__(self):
        return f"{self.hostname} @ {self.captured_at:%Y-%m-%d %H:%M:%S}"


class ProcessSnapshot(models.Model):
    snapshot = models.ForeignKey(SystemSnapshot, related_name="processes", on_delete=models.CASCADE)
    pid = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    username = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=64, blank=True)
    cpu_percent = models.FloatField(default=0)
    memory_percent = models.FloatField(default=0)
    memory_rss_mb = models.FloatField(default=0)
    threads = models.PositiveIntegerField(default=0)
    command = models.TextField(blank=True)

    class Meta:
        app_label = "monitor"
        ordering = ("-cpu_percent", "-memory_percent", "pid")

    def __str__(self):
        return f"{self.name} ({self.pid})"
