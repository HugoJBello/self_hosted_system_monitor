from django.db import models
from django.utils import timezone


class FileOperation(models.Model):
    CONFLICT_POLICY_CHOICES = [
        ("overwrite", "Overwrite"),
        ("skip", "Skip"),
        ("rename", "Rename"),
    ]
    ACTION_CHOICES = [
        ("copy", "Copy"),
        ("move", "Move"),
        ("delete", "Delete"),
        ("upload", "Upload"),
        ("download", "Download"),
    ]
    STATUS_CHOICES = [
        ("running", "Running"),
        ("paused", "Paused"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    action = models.CharField(max_length=16, choices=ACTION_CHOICES, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running", db_index=True)
    sources = models.JSONField(default=list, blank=True)
    completed_sources = models.JSONField(default=list, blank=True)
    destination_path = models.CharField(max_length=500, blank=True, default="")
    conflict_policy = models.CharField(max_length=16, choices=CONFLICT_POLICY_CHOICES, default="overwrite")
    current_path = models.CharField(max_length=500, blank=True, default="")
    total_count = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    summary = models.CharField(max_length=255, blank=True, default="")
    log_output = models.TextField(blank=True, default="")
    process_pid = models.PositiveIntegerField(blank=True, null=True)
    runner_label = models.CharField(max_length=255, blank=True, default="")
    pause_requested_at = models.DateTimeField(blank=True, null=True)
    cancel_requested_at = models.DateTimeField(blank=True, null=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "monitor"
        ordering = ("-started_at",)

    @property
    def progress_percent(self):
        if not self.total_count:
            return 0
        return min(100, round((self.processed_count / self.total_count) * 100))

    def __str__(self):
        return f"{self.get_action_display()} {self.status} @ {self.started_at:%Y-%m-%d %H:%M:%S}"
