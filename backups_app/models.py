from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class BackupJob(models.Model):
    SCHEDULE_MODE_CHOICES = [
        ("interval", "Recurring schedule"),
        ("manual", "Run only when clicking Run now"),
    ]
    BACKUP_TYPE_CHOICES = [
        ("local", "Local memory backup"),
        ("remote", "SSH + rsync backup"),
        ("http", "HTTP server to server backup"),
    ]
    HTTP_DIRECTION_CHOICES = [
        ("push", "Copy from this server to remote server"),
        ("pull", "Copy from remote server to this server"),
    ]
    REMOTE_DIRECTION_CHOICES = [
        ("push", "Local folder to remote SSH directory"),
        ("pull", "Remote SSH directory to local folder"),
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
    schedule_mode = models.CharField(max_length=16, choices=SCHEDULE_MODE_CHOICES, default="interval")
    schedule_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(60 * 24 * 30)],
    )
    remote_host = models.CharField(max_length=255, blank=True, default="")
    remote_user = models.CharField(max_length=255, blank=True, default="")
    remote_dir = models.CharField(max_length=500, blank=True, default="")
    remote_direction = models.CharField(max_length=16, choices=REMOTE_DIRECTION_CHOICES, default="push")
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
    max_size = models.CharField(max_length=32, blank=True, default="")
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
        app_label = "monitor"
        ordering = ("position", "id")

    def save(self, *args, **kwargs):
        if not self.enabled:
            self.next_run_at = None
        elif self.is_manual:
            self.next_run_at = None
        elif self.next_run_at is None:
            self.next_run_at = timezone.now() + timezone.timedelta(minutes=max(self.schedule_minutes, 5))
        super().save(*args, **kwargs)

    @property
    def is_manual(self):
        return self.schedule_mode == "manual"

    @property
    def schedule_label(self):
        if self.is_manual:
            return "Run only on demand"
        return f"Every {self.schedule_minutes}m"

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
    def is_remote_pull(self):
        return self.backup_type == "remote" and self.remote_direction == "pull"

    @property
    def remote_label(self):
        host = self.remote_host or "(remote host not set)"
        remote_dir = self.remote_dir or "/"
        user = f"{self.remote_user}@" if self.remote_user else ""
        return f"{user}{host}:{remote_dir}"

    @property
    def source_label(self):
        if self.is_http and self.http_direction == "pull":
            return self.http_remote_path or "(remote folder not set)"
        if self.is_remote_pull:
            return self.remote_label
        return self.source_path or "(source not set)"

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
        if self.is_remote_pull:
            return self.source_path or "(local destination not set)"
        return self.remote_label

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

    job = models.ForeignKey("monitor.BackupJob", related_name="runs", on_delete=models.CASCADE)
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
        app_label = "monitor"
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.job.name} @ {self.started_at:%Y-%m-%d %H:%M:%S}"
