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
        ordering = ("-cpu_percent", "-memory_percent", "pid")

    def __str__(self):
        return f"{self.name} ({self.pid})"


class AlertRule(models.Model):
    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    ]
    METRIC_CHOICES = [
        ("cpu_percent", "CPU percent"),
        ("memory_percent", "Memory percent"),
        ("swap_percent", "Swap percent"),
        ("disk_percent", "Disk percent"),
        ("load_avg_1", "Load average 1m"),
        ("load_avg_5", "Load average 5m"),
        ("load_avg_15", "Load average 15m"),
        ("network_sent_rate_kbps", "Network sent kbps"),
        ("network_recv_rate_kbps", "Network received kbps"),
        ("process_count_total", "Total processes"),
        ("process_count_running", "Running processes"),
        ("process_count_zombie", "Zombie processes"),
    ]
    EVALUATION_CHOICES = [
        ("current", "Current value"),
        ("avg", "Average in window"),
        ("max", "Maximum in window"),
        ("min", "Minimum in window"),
    ]
    COMPARATOR_CHOICES = [
        ("gt", ">"),
        ("gte", ">="),
        ("lt", "<"),
        ("lte", "<="),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default="warning")
    metric = models.CharField(max_length=64, choices=METRIC_CHOICES)
    evaluation_mode = models.CharField(max_length=16, choices=EVALUATION_CHOICES, default="current")
    comparator = models.CharField(max_length=8, choices=COMPARATOR_CHOICES, default="gte")
    threshold = models.FloatField(default=80)
    window_minutes = models.PositiveIntegerField(default=5)
    min_occurrences = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10000)],
    )
    cooldown_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(10080)],
    )
    notifications_enabled = models.BooleanField(default=True)
    notification_channels = models.CharField(blank=True, default="", max_length=255)
    notification_tags = models.CharField(blank=True, default="", max_length=255)
    notification_user = models.CharField(blank=True, default="", max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("position", "id")

    @property
    def notification_channels_list(self):
        return [item.strip() for item in self.notification_channels.replace(",", ";").split(";") if item.strip()]

    @property
    def notification_tags_list(self):
        return [item.strip() for item in self.notification_tags.replace(",", ";").split(";") if item.strip()]

    def __str__(self):
        return self.name


class AlertEvent(models.Model):
    rule = models.ForeignKey(AlertRule, related_name="events", on_delete=models.CASCADE)
    snapshot = models.ForeignKey(SystemSnapshot, related_name="alert_events", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=16, choices=AlertRule.SEVERITY_CHOICES)
    metric = models.CharField(max_length=64)
    comparator = models.CharField(max_length=8)
    threshold = models.FloatField()
    evaluated_value = models.FloatField()
    matching_count = models.PositiveIntegerField(default=0)
    sample_count = models.PositiveIntegerField(default=1)
    window_minutes = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    triggered_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(blank=True, null=True)
    notification_sent = models.BooleanField(default=False)
    notification_status_code = models.IntegerField(blank=True, null=True)
    notification_response = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ("-triggered_at",)

    def __str__(self):
        return f"{self.rule.name} @ {self.triggered_at:%Y-%m-%d %H:%M:%S}"


class ReportRule(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    period_hours = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(24 * 30)],
    )
    cadence_hours = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(24 * 30)],
    )
    send_notifications = models.BooleanField(default=True)
    notification_channels = models.CharField(blank=True, default="", max_length=255)
    notification_tags = models.CharField(blank=True, default="", max_length=255)
    notification_user = models.CharField(blank=True, default="", max_length=255)
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("position", "id")

    @property
    def notification_channels_list(self):
        return [item.strip() for item in self.notification_channels.replace(",", ";").split(";") if item.strip()]

    @property
    def notification_tags_list(self):
        return [item.strip() for item in self.notification_tags.replace(",", ";").split(";") if item.strip()]

    def save(self, *args, **kwargs):
        if self.enabled and self.next_run_at is None:
            self.next_run_at = timezone.now() + timezone.timedelta(hours=max(self.cadence_hours, 1))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ReportRun(models.Model):
    rule = models.ForeignKey(ReportRule, related_name="runs", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    message = models.TextField()
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    generated_at = models.DateTimeField(default=timezone.now, db_index=True)
    sample_count = models.PositiveIntegerField(default=0)
    report_data = models.JSONField(default=dict)
    notification_sent = models.BooleanField(default=False)
    notification_status_code = models.IntegerField(blank=True, null=True)
    notification_response = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ("-generated_at",)

    def __str__(self):
        return f"{self.rule.name} report @ {self.generated_at:%Y-%m-%d %H:%M:%S}"


class ScriptJob(models.Model):
    SCHEDULE_MODE_CHOICES = [
        ("manual", "Run only when clicking Run now"),
        ("interval", "Recurring schedule"),
        ("one_off", "Run once at a specific date and time"),
    ]
    SCHEDULE_UNIT_CHOICES = [
        ("minutes", "Minutes"),
        ("days", "Days"),
        ("weeks", "Weeks"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    schedule_mode = models.CharField(max_length=16, choices=SCHEDULE_MODE_CHOICES, default="interval")
    schedule_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(60 * 24 * 30)],
    )
    schedule_unit = models.CharField(max_length=16, choices=SCHEDULE_UNIT_CHOICES, default="minutes")
    scheduled_for = models.DateTimeField(blank=True, null=True)
    working_directory = models.CharField(max_length=500, blank=True, default="")
    script_body = models.TextField(default="")
    run_as_sudo = models.BooleanField(default=False)
    sudo_password = models.CharField(max_length=255, blank=True, default="")
    run_timeout_seconds = models.PositiveIntegerField(
        default=7200,
        validators=[MinValueValidator(30), MaxValueValidator(60 * 60 * 24 * 7)],
    )
    idle_timeout_seconds = models.PositiveIntegerField(
        default=900,
        validators=[MinValueValidator(30), MaxValueValidator(60 * 60 * 24)],
    )
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("position", "id")

    @property
    def is_one_off(self):
        return self.schedule_mode == "one_off"

    @property
    def is_manual(self):
        return self.schedule_mode == "manual"

    @property
    def cadence_delta(self):
        value = max(int(self.schedule_minutes or 0), 1)
        if self.schedule_unit == "weeks":
            return timezone.timedelta(weeks=value)
        if self.schedule_unit == "days":
            return timezone.timedelta(days=value)
        return timezone.timedelta(minutes=max(value, 5))

    @property
    def schedule_label(self):
        if self.is_manual:
            return "Run only on demand"
        if self.is_one_off:
            return (
                timezone.localtime(self.scheduled_for).strftime("%Y-%m-%d %H:%M")
                if self.scheduled_for
                else "Date pending"
            )
        unit_map = {
            "minutes": "minute",
            "days": "day",
            "weeks": "week",
        }
        unit_label = unit_map.get(self.schedule_unit, "minute")
        plural = "" if int(self.schedule_minutes or 0) == 1 else "s"
        return f"Every {self.schedule_minutes} {unit_label}{plural}"

    @property
    def script_preview(self):
        for line in (self.script_body or "").splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:120]
        return "(empty script)"

    def save(self, *args, **kwargs):
        if not self.enabled:
            self.next_run_at = None
        elif self.is_manual:
            self.next_run_at = None
        elif self.is_one_off:
            self.next_run_at = self.scheduled_for
        elif self.next_run_at is None:
            self.next_run_at = timezone.now() + self.cadence_delta
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ScriptJobRun(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
        ("timed_out", "Timed out"),
    ]
    LAUNCH_CHOICES = [
        ("manual", "Manual"),
        ("scheduler", "Scheduler"),
    ]

    job = models.ForeignKey(ScriptJob, related_name="runs", on_delete=models.CASCADE)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="success")
    exit_code = models.IntegerField(default=0)
    summary = models.CharField(max_length=255, blank=True, default="")
    log_output = models.TextField(blank=True, default="")
    launched_by = models.CharField(max_length=16, choices=LAUNCH_CHOICES, default="manual")
    process_pid = models.PositiveIntegerField(blank=True, null=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True)
    last_output_at = models.DateTimeField(blank=True, null=True)
    stop_requested_at = models.DateTimeField(blank=True, null=True)
    command_line = models.TextField(blank=True, default="")
    runner_label = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.job.name} @ {self.started_at:%Y-%m-%d %H:%M:%S}"


class BackupJob(models.Model):
    BACKUP_TYPE_CHOICES = [
        ("local", "Local memory backup"),
        ("remote", "SSH + rsync backup"),
        ("http", "HTTP server to server backup"),
    ]
    HTTP_DIRECTION_CHOICES = [
        ("push", "Copy from this server to remote server"),
        ("pull", "Copy from remote server to this server"),
    ]
    CONNECTION_CHOICES = [
        ("direct", "Direct SSH"),
        ("cloudflare", "Cloudflare Access SSH"),
    ]
    AUTH_CHOICES = [
        ("key", "SSH key only"),
        ("password_file", "Password file"),
        ("password_value", "Saved password"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    backup_type = models.CharField(max_length=16, choices=BACKUP_TYPE_CHOICES, default="remote")
    source_path = models.CharField(max_length=500, help_text="Host path, for example /home/user/Documents")
    local_dest_path = models.CharField(max_length=500, blank=True, default="")
    verify_mounted_device = models.BooleanField(default=False)
    trigger_on_mount = models.BooleanField(default=False)
    last_mount_was_available = models.BooleanField(default=False)
    schedule_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(60 * 24 * 30)],
    )
    remote_host = models.CharField(max_length=255, blank=True, default="")
    remote_user = models.CharField(max_length=255, blank=True, default="")
    remote_dir = models.CharField(max_length=500, blank=True, default="")
    ssh_port = models.PositiveIntegerField(
        default=22,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    connection_mode = models.CharField(max_length=32, choices=CONNECTION_CHOICES, default="direct")
    cloudflare_auth_home = models.CharField(max_length=500, blank=True, default="")
    cloudflare_service_token_id = models.CharField(max_length=255, blank=True, default="")
    cloudflare_service_token_secret = models.CharField(max_length=255, blank=True, default="")
    http_remote_url = models.URLField(blank=True, default="", max_length=500)
    http_remote_token = models.CharField(blank=True, default="", max_length=255)
    http_remote_path = models.CharField(max_length=500, blank=True, default="")
    http_direction = models.CharField(max_length=16, choices=HTTP_DIRECTION_CHOICES, default="push")
    auth_mode = models.CharField(max_length=32, choices=AUTH_CHOICES, default="key")
    password_file_path = models.CharField(max_length=500, blank=True, default="")
    ssh_password = models.CharField(max_length=255, blank=True, default="")
    public_key_path = models.CharField(max_length=500, blank=True, default="")
    install_public_key = models.BooleanField(default=False)
    delete_enabled = models.BooleanField(default=True)
    max_size = models.CharField(max_length=32, blank=True, default="100m")
    run_timeout_seconds = models.PositiveIntegerField(
        default=7200,
        validators=[MinValueValidator(60), MaxValueValidator(60 * 60 * 24 * 7)],
    )
    idle_timeout_seconds = models.PositiveIntegerField(
        default=900,
        validators=[MinValueValidator(30), MaxValueValidator(60 * 60 * 24)],
    )
    exclude_patterns = models.TextField(blank=True, default="")
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("position", "id")

    def save(self, *args, **kwargs):
        if not self.enabled:
            self.next_run_at = None
        if self.enabled and self.next_run_at is None:
            self.next_run_at = timezone.now() + timezone.timedelta(minutes=max(self.schedule_minutes, 5))
        super().save(*args, **kwargs)

    @property
    def exclude_patterns_list(self):
        return [line.strip() for line in self.exclude_patterns.splitlines() if line.strip()]

    @property
    def is_local(self):
        return self.backup_type == "local"

    @property
    def is_http(self):
        return self.backup_type == "http"

    @property
    def destination_label(self):
        if self.is_local:
            return self.local_dest_path or "(local destination not set)"
        if self.is_http:
            base = (self.http_remote_url or "(HTTP server not set)").rstrip("/")
            remote_path = self.http_remote_path or "/"
            if self.http_direction == "pull":
                return self.local_dest_path or "(local destination not set)"
            return f"{base}:{remote_path}"
        host = self.remote_host or "(remote host not set)"
        remote_dir = self.remote_dir or "/"
        user = f"{self.remote_user}@" if self.remote_user else ""
        return f"{user}{host}:{remote_dir}"

    def __str__(self):
        return self.name


class BackupRun(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
        ("timed_out", "Timed out"),
    ]
    LAUNCH_CHOICES = [
        ("manual", "Manual"),
        ("scheduler", "Scheduler"),
    ]

    job = models.ForeignKey(BackupJob, related_name="runs", on_delete=models.CASCADE)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="success")
    exit_code = models.IntegerField(default=0)
    summary = models.CharField(max_length=255, blank=True, default="")
    log_output = models.TextField(blank=True, default="")
    created_remote_dir = models.BooleanField(default=False)
    launched_by = models.CharField(max_length=16, choices=LAUNCH_CHOICES, default="manual")
    process_pid = models.PositiveIntegerField(blank=True, null=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True)
    last_output_at = models.DateTimeField(blank=True, null=True)
    stop_requested_at = models.DateTimeField(blank=True, null=True)
    command_line = models.TextField(blank=True, default="")
    runner_label = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.job.name} @ {self.started_at:%Y-%m-%d %H:%M:%S}"
