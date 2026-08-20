from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
import os


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class MonitoringSettings(models.Model):
    DISPLAY_TIME_MODE_CHOICES = [
        ("browser", "Browser locale and timezone"),
        ("fixed", "Fixed timezone for all users"),
    ]

    sample_interval_seconds = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(10), MaxValueValidator(3600)],
    )
    top_process_limit = models.PositiveIntegerField(
        default=8,
        validators=[MinValueValidator(3), MaxValueValidator(30)],
    )
    history_retention_days = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(3650)],
    )
    notifications_enabled = models.BooleanField(default=False)
    notifications_api_url = models.URLField(
        blank=True,
        default="",
        max_length=500,
    )
    notifications_api_token = models.CharField(blank=True, default="", max_length=255)
    notifications_default_channels = models.CharField(blank=True, default="email", max_length=255)
    notifications_default_tags = models.CharField(blank=True, default="", max_length=255)
    notifications_default_user = models.CharField(blank=True, default="", max_length=255)
    notifications_default_origin = models.CharField(blank=True, default="system-monitor", max_length=255)
    notifications_default_status = models.CharField(blank=True, default="warning", max_length=64)
    notifications_default_priority = models.CharField(blank=True, default="high", max_length=64)
    notifications_default_action = models.CharField(blank=True, default="notify", max_length=64)
    notifications_timeout_seconds = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
    )
    app_public_base_url = models.URLField(
        blank=True,
        default="",
        max_length=500,
    )
    http_backup_token = models.CharField(blank=True, default="change_this_token", max_length=255)
    display_time_mode = models.CharField(
        max_length=16,
        choices=DISPLAY_TIME_MODE_CHOICES,
        default="browser",
    )
    display_timezone = models.CharField(
        max_length=64,
        default="Europe/Madrid",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        settings_obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "notifications_enabled": _env_bool("NOTIFICATIONS_ENABLED", False),
                "notifications_api_url": os.getenv(
                    "NOTIFICATIONS_API_URL",
                    "http://127.0.0.1:49231/notifications/api/receive/",
                ),
                "notifications_api_token": os.getenv("NOTIFICATIONS_API_TOKEN", ""),
                "notifications_default_channels": os.getenv("NOTIFICATIONS_DEFAULT_CHANNELS", "email"),
                "notifications_default_tags": os.getenv("NOTIFICATIONS_DEFAULT_TAGS", ""),
                "notifications_default_user": os.getenv("NOTIFICATIONS_DEFAULT_USER", ""),
                "notifications_default_origin": os.getenv("NOTIFICATIONS_DEFAULT_ORIGIN", "system-monitor"),
                "notifications_default_status": os.getenv("NOTIFICATIONS_DEFAULT_STATUS", "warning"),
                "notifications_default_priority": os.getenv("NOTIFICATIONS_DEFAULT_PRIORITY", "high"),
                "notifications_default_action": os.getenv("NOTIFICATIONS_DEFAULT_ACTION", "notify"),
                "notifications_timeout_seconds": int(os.getenv("NOTIFICATIONS_TIMEOUT_SECONDS", "10")),
                "app_public_base_url": os.getenv("SYSTEM_MONITOR_PUBLIC_BASE_URL", ""),
                "http_backup_token": os.getenv("HTTP_BACKUP_TOKEN", "change_this_token"),
                "display_time_mode": os.getenv("SYSTEM_MONITOR_DISPLAY_TIME_MODE", "browser"),
                "display_timezone": os.getenv("SYSTEM_MONITOR_DISPLAY_TIMEZONE", "Europe/Madrid"),
            },
        )
        return settings_obj

    @property
    def notifications_channels_list(self):
        return [item.strip() for item in self.notifications_default_channels.replace(",", ";").split(";") if item.strip()]

    @property
    def notifications_tags_list(self):
        return [item.strip() for item in self.notifications_default_tags.replace(",", ";").split(";") if item.strip()]

    @property
    def normalized_app_public_base_url(self):
        return (self.app_public_base_url or "").rstrip("/")

    def __str__(self):
        return "Monitoring Settings"


# Compatibility exports: model classes live in their owning apps,
# but keep main_app.models imports stable while preserving app_label="monitor".
from monitor_app.models import ProcessSnapshot, SystemSnapshot
from alerts_app.models import AlertEvent, AlertRule
from reports_app.models import ReportRule, ReportRun
from jobs_app.models import ScriptJob, ScriptJobRun
from backups_app.models import BackupJob, BackupRun
from volumes_app.models import VolumeMountPreference, VolumeOperation


__all__ = [
    "AlertEvent",
    "AlertRule",
    "BackupJob",
    "BackupRun",
    "MonitoringSettings",
    "ProcessSnapshot",
    "ReportRule",
    "ReportRun",
    "ScriptJob",
    "ScriptJobRun",
    "SystemSnapshot",
    "VolumeMountPreference",
    "VolumeOperation",
]
