from django.db import models
from django.utils import timezone
from django.conf import settings
import secrets


class FileOperation(models.Model):
    COMPRESSION_METHOD_CHOICES = [
        ("deflated", "ZIP deflated"),
        ("stored", "Store only"),
        ("bzip2", "ZIP BZIP2"),
        ("lzma", "ZIP LZMA"),
        ("tar", "TAR"),
        ("tar_gz", "TAR gzip"),
        ("tar_bz2", "TAR BZIP2"),
        ("tar_xz", "TAR XZ"),
    ]
    TRANSFER_METHOD_CHOICES = [
        ("standard", "Standard"),
        ("rsync", "Rsync differential"),
    ]
    CONFLICT_POLICY_CHOICES = [
        ("overwrite", "Overwrite"),
        ("skip", "Skip"),
        ("rename", "Rename"),
    ]
    FOLDER_CONFLICT_POLICY_CHOICES = [
        ("merge", "Merge"),
        ("skip", "Skip"),
        ("rename", "Rename"),
    ]
    ACTION_CHOICES = [
        ("copy", "Copy"),
        ("move", "Move"),
        ("delete", "Delete"),
        ("upload", "Upload"),
        ("download", "Download"),
        ("compress", "Compress"),
        ("uncompress", "Uncompress"),
        ("search", "Search"),
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
    transfer_method = models.CharField(max_length=16, choices=TRANSFER_METHOD_CHOICES, default="standard")
    rsync_delete = models.BooleanField(default=False)
    conflict_policy = models.CharField(max_length=16, choices=CONFLICT_POLICY_CHOICES, default="overwrite")
    folder_conflict_policy = models.CharField(max_length=16, choices=FOLDER_CONFLICT_POLICY_CHOICES, default="merge")
    compression_method = models.CharField(max_length=16, choices=COMPRESSION_METHOD_CHOICES, default="deflated")
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
    file_share = models.ForeignKey("FileShare", on_delete=models.CASCADE, related_name="download_operations", blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="file_operations", blank=True, null=True)

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


class FileSearch(models.Model):
    operation = models.OneToOneField(FileOperation, on_delete=models.CASCADE, related_name="search")
    root_path = models.CharField(max_length=500)
    query = models.CharField(max_length=500)
    recursive = models.BooleanField(default=True)
    case_sensitive = models.BooleanField(default=False)
    use_regex = models.BooleanField(default=False)
    timeout_seconds = models.PositiveIntegerField(blank=True, null=True)
    result_paths = models.JSONField(default=list, blank=True)
    result_count = models.PositiveIntegerField(default=0)
    truncated = models.BooleanField(default=False)
    timed_out = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "monitor"
        ordering = ("-created_at",)

    @property
    def timeout_label(self):
        return f"{self.timeout_seconds}s" if self.timeout_seconds else "No timeout"


def _share_token():
    return secrets.token_urlsafe(32)


class FileShare(models.Model):
    token = models.CharField(max_length=64, unique=True, db_index=True, default=_share_token, editable=False)
    name = models.CharField(max_length=160, blank=True, default="")
    paths = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_file_shares")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_file_shares", blank=True, null=True)
    public_link = models.BooleanField(default=True)
    expires_at = models.DateTimeField(blank=True, null=True, db_index=True)
    revoked_at = models.DateTimeField(blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "monitor"
        ordering = ("-created_at",)

    @property
    def is_active(self):
        return not self.revoked_at and (not self.expires_at or self.expires_at > timezone.now())

    def __str__(self):
        return self.name or f"Shared files {self.pk}"


class UserFileAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="file_accesses")
    path = models.CharField(max_length=500)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="granted_file_accesses", blank=True, null=True)
    source_share = models.ForeignKey(FileShare, on_delete=models.CASCADE, related_name="access_grants", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "monitor"
        ordering = ("path",)
        constraints = [models.UniqueConstraint(fields=("user", "path", "source_share"), name="unique_user_file_share_access")]
