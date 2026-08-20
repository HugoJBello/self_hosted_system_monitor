from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class VolumeMountPreference(models.Model):
    volume_key = models.CharField(max_length=255, unique=True, db_index=True)
    device = models.CharField(max_length=255, blank=True, default="")
    uuid = models.CharField(max_length=255, blank=True, default="")
    label = models.CharField(max_length=255, blank=True, default="")
    model = models.CharField(max_length=255, blank=True, default="")
    serial = models.CharField(max_length=255, blank=True, default="")
    mountpoint = models.CharField(max_length=500)
    last_mounted_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "monitor"
        ordering = ("volume_key",)

    def __str__(self):
        return f"{self.volume_key} -> {self.mountpoint}"


class VolumeOperation(models.Model):
    ACTION_CHOICES = [
        ("label", "Update label"),
        ("format", "Format"),
    ]
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    device = models.CharField(max_length=255, db_index=True)
    fstype = models.CharField(max_length=32, blank=True, default="")
    label = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running", db_index=True)
    summary = models.CharField(max_length=255, blank=True, default="")
    log_output = models.TextField(blank=True, default="")
    command_line = models.TextField(blank=True, default="")
    process_pid = models.PositiveIntegerField(blank=True, null=True)
    runner_label = models.CharField(max_length=255, blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "monitor"
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.get_action_display()} {self.device} @ {self.started_at:%Y-%m-%d %H:%M:%S}"
