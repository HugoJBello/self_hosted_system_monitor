from django import forms
from zoneinfo import available_timezones

from .models import AlertRule, BackupJob, MonitoringSettings, ReportRule


class MonitoringSettingsForm(forms.ModelForm):
    class Meta:
        model = MonitoringSettings
        fields = (
            "sample_interval_seconds",
            "top_process_limit",
            "history_retention_days",
            "notifications_enabled",
            "notifications_api_url",
            "notifications_api_token",
            "notifications_default_channels",
            "notifications_default_tags",
            "notifications_default_user",
            "notifications_default_origin",
            "notifications_default_status",
            "notifications_default_priority",
            "notifications_default_action",
            "notifications_timeout_seconds",
            "app_public_base_url",
            "http_backup_token",
            "display_time_mode",
            "display_timezone",
        )
        widgets = {
            "sample_interval_seconds": forms.NumberInput(attrs={"class": "form-control", "min": 10, "step": 5}),
            "top_process_limit": forms.NumberInput(attrs={"class": "form-control", "min": 3, "max": 30}),
            "history_retention_days": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 3650}),
            "notifications_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notifications_api_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "http://127.0.0.1:49231/notifications/api/receive/"}),
            "notifications_api_token": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Bearer token"}, render_value=True),
            "notifications_default_channels": forms.TextInput(attrs={"class": "form-control", "placeholder": "email;telegram;xmpp"}),
            "notifications_default_tags": forms.TextInput(attrs={"class": "form-control", "placeholder": "server;alert"}),
            "notifications_default_user": forms.TextInput(attrs={"class": "form-control", "placeholder": "alice"}),
            "notifications_default_origin": forms.TextInput(attrs={"class": "form-control", "placeholder": "system-monitor"}),
            "notifications_default_status": forms.TextInput(attrs={"class": "form-control", "placeholder": "warning"}),
            "notifications_default_priority": forms.TextInput(attrs={"class": "form-control", "placeholder": "high"}),
            "notifications_default_action": forms.TextInput(attrs={"class": "form-control", "placeholder": "notify"}),
            "notifications_timeout_seconds": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 300}),
            "app_public_base_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://monitor.example.com/system_monitor"}),
            "http_backup_token": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Bearer token"}, render_value=True),
            "display_time_mode": forms.Select(attrs={"class": "form-select js-display-time-mode"}),
            "display_timezone": forms.Select(attrs={"class": "form-select js-display-timezone"}),
        }

    COMMON_TIMEZONES = [
        "Europe/Madrid",
        "Atlantic/Canary",
        "Europe/London",
        "Europe/Berlin",
        "Europe/Paris",
        "Europe/Rome",
        "Europe/Lisbon",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Mexico_City",
        "America/Bogota",
        "America/Santiago",
        "America/Argentina/Buenos_Aires",
        "UTC",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        timezone_choices = []
        seen = set()
        for value in self.COMMON_TIMEZONES + sorted(available_timezones()):
            if value in seen:
                continue
            seen.add(value)
            timezone_choices.append((value, value.replace("_", " ")))
        self.fields["display_timezone"].choices = timezone_choices
        self.fields["display_time_mode"].label = "Date and time mode"
        self.fields["display_timezone"].label = "Fixed display timezone"
        self.fields["display_timezone"].required = False

    def clean_notifications_default_channels(self):
        value = self.cleaned_data["notifications_default_channels"].strip()
        allowed = {"email", "telegram", "xmpp"}
        channels = [item.strip().lower() for item in value.replace(",", ";").split(";") if item.strip()]
        invalid = [item for item in channels if item not in allowed]
        if invalid:
            raise forms.ValidationError("Channels must be any combination of email, telegram, and xmpp.")
        return ";".join(channels)

    def clean_display_timezone(self):
        value = (self.cleaned_data.get("display_timezone") or "").strip()
        if not value:
            return self.instance.display_timezone or "Europe/Madrid"
        if value not in available_timezones():
            raise forms.ValidationError("Choose a valid timezone.")
        return value

    def clean_http_backup_token(self):
        value = (self.cleaned_data.get("http_backup_token") or "").strip()
        if value:
            return value
        return self.instance.http_backup_token or "change_this_token"


class AlertRuleForm(forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = (
            "name",
            "description",
            "enabled",
            "severity",
            "metric",
            "evaluation_mode",
            "comparator",
            "threshold",
            "window_minutes",
            "min_occurrences",
            "cooldown_minutes",
            "notifications_enabled",
            "notification_channels",
            "notification_tags",
            "notification_user",
            "position",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "severity": forms.Select(attrs={"class": "form-select"}),
            "metric": forms.Select(attrs={"class": "form-select"}),
            "evaluation_mode": forms.Select(attrs={"class": "form-select"}),
            "comparator": forms.Select(attrs={"class": "form-select"}),
            "threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "window_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10080}),
            "min_occurrences": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10000}),
            "cooldown_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 10080}),
            "notifications_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notification_channels": forms.TextInput(attrs={"class": "form-control", "placeholder": "email;telegram;xmpp"}),
            "notification_tags": forms.TextInput(attrs={"class": "form-control", "placeholder": "server;alert"}),
            "notification_user": forms.TextInput(attrs={"class": "form-control", "placeholder": "alice"}),
            "position": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }

    def clean_notification_channels(self):
        value = self.cleaned_data["notification_channels"].strip()
        if not value:
            return value
        allowed = {"email", "telegram", "xmpp"}
        channels = [item.strip().lower() for item in value.replace(",", ";").split(";") if item.strip()]
        invalid = [item for item in channels if item not in allowed]
        if invalid:
            raise forms.ValidationError("Rule channels must use only email, telegram, and xmpp.")
        return ";".join(channels)


class ReportRuleForm(forms.ModelForm):
    class Meta:
        model = ReportRule
        fields = (
            "name",
            "description",
            "enabled",
            "period_hours",
            "cadence_hours",
            "send_notifications",
            "notification_channels",
            "notification_tags",
            "notification_user",
            "position",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "period_hours": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 720}),
            "cadence_hours": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 720}),
            "send_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notification_channels": forms.TextInput(attrs={"class": "form-control", "placeholder": "email;telegram;xmpp"}),
            "notification_tags": forms.TextInput(attrs={"class": "form-control", "placeholder": "server;report"}),
            "notification_user": forms.TextInput(attrs={"class": "form-control", "placeholder": "alice"}),
            "position": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }

    def clean_notification_channels(self):
        value = self.cleaned_data["notification_channels"].strip()
        if not value:
            return value
        allowed = {"email", "telegram", "xmpp"}
        channels = [item.strip().lower() for item in value.replace(",", ";").split(";") if item.strip()]
        invalid = [item for item in channels if item not in allowed]
        if invalid:
            raise forms.ValidationError("Report channels must use only email, telegram, and xmpp.")
        return ";".join(channels)


class BackupJobForm(forms.ModelForm):
    class Meta:
        model = BackupJob
        fields = (
            "name",
            "description",
            "enabled",
            "backup_type",
            "source_path",
            "local_dest_path",
            "trigger_on_mount",
            "schedule_minutes",
            "remote_host",
            "remote_user",
            "remote_dir",
            "ssh_port",
            "connection_mode",
            "cloudflare_auth_home",
            "cloudflare_service_token_id",
            "cloudflare_service_token_secret",
            "http_remote_url",
            "http_remote_token",
            "http_remote_path",
            "http_direction",
            "auth_mode",
            "password_file_path",
            "ssh_password",
            "public_key_path",
            "install_public_key",
            "delete_enabled",
            "max_size",
            "run_timeout_seconds",
            "idle_timeout_seconds",
            "exclude_patterns",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "backup_type": forms.Select(attrs={"class": "form-select backup-type-select"}),
            "source_path": forms.TextInput(attrs={"class": "form-control backup-source-input", "placeholder": "/home/user/Documents"}),
            "local_dest_path": forms.TextInput(attrs={"class": "form-control backup-destination-input", "placeholder": "/media/usb/backups/laptop"}),
            "trigger_on_mount": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "schedule_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 5, "max": 43200, "step": 5, "list": "backup-schedule-presets"}),
            "remote_host": forms.TextInput(attrs={"class": "form-control", "placeholder": "backup-host.example.com"}),
            "remote_user": forms.TextInput(attrs={"class": "form-control", "placeholder": "backupuser"}),
            "remote_dir": forms.TextInput(attrs={"class": "form-control", "placeholder": "/backups/server-a"}),
            "ssh_port": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 65535}),
            "connection_mode": forms.Select(attrs={"class": "form-select"}),
            "cloudflare_auth_home": forms.TextInput(attrs={"class": "form-control", "placeholder": "/home/goku"}),
            "cloudflare_service_token_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Access service token ID"}),
            "cloudflare_service_token_secret": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Access service token secret"}, render_value=True),
            "http_remote_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://other-monitor.example.com/system_monitor"}),
            "http_remote_token": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Destination Bearer token"}, render_value=True),
            "http_remote_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/srv/data"}),
            "http_direction": forms.Select(attrs={"class": "form-select"}),
            "auth_mode": forms.Select(attrs={"class": "form-select"}),
            "password_file_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/home/user/.ssh/backup.pass"}),
            "ssh_password": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Optional saved password"}, render_value=True),
            "public_key_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/home/user/.ssh/id_ed25519.pub"}),
            "install_public_key": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "delete_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "max_size": forms.TextInput(attrs={"class": "form-control", "placeholder": "100m"}),
            "run_timeout_seconds": forms.NumberInput(attrs={"class": "form-control d-none backup-timeout-seconds", "min": 60, "max": 604800, "step": 60}),
            "idle_timeout_seconds": forms.NumberInput(attrs={"class": "form-control", "min": 30, "max": 86400, "step": 30}),
            "exclude_patterns": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "*.tmp\nnode_modules/"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["backup_type"].required = False
        self.fields["source_path"].required = False
        self.fields["http_direction"].required = False
        self.fields["source_path"].label = "Source folder"
        self.fields["local_dest_path"].label = "Destination folder"
        self.fields["remote_host"].label = "Hostname or IP"
        self.fields["remote_user"].label = "SSH user"
        self.fields["ssh_password"].label = "SSH password"
        self.fields["backup_type"].label = "Backup type"
        self.fields["connection_mode"].label = "Connection mode"
        self.fields["auth_mode"].label = "Authentication"
        self.fields["cloudflare_service_token_id"].label = "Cloudflare service token ID"
        self.fields["cloudflare_service_token_secret"].label = "Cloudflare service token secret"
        self.fields["cloudflare_auth_home"].label = "Cloudflare auth home on host"
        self.fields["http_remote_url"].label = "Remote server URL"
        self.fields["http_remote_token"].label = "Remote Bearer token"
        self.fields["http_remote_path"].label = "Remote folder"
        self.fields["http_direction"].label = "HTTP direction"
        self.fields["password_file_path"].label = "Password file on host"
        self.fields["public_key_path"].label = "Public key path on host"
        self.fields["run_timeout_seconds"].label = "Hard timeout (seconds)"
        self.fields["idle_timeout_seconds"].label = "Idle timeout (seconds)"
        self.fields["backup_type"].choices = [
            ("local", "Local memory backup"),
            ("remote", "SSH + rsync backup"),
            ("http", "HTTP server to server backup"),
        ]
        self.fields["connection_mode"].choices = [
            ("direct", "Standard SSH"),
            ("cloudflare", "This host needs Cloudflare SSH params"),
        ]
        self.fields["auth_mode"].choices = [
            ("password_value", "Use the SSH password below"),
            ("key", "Use SSH key only"),
            ("password_file", "Read password from host file"),
        ]

    def clean_source_path(self):
        value = (self.cleaned_data.get("source_path") or "").strip()
        if not value:
            return value
        if not value.startswith("/"):
            raise forms.ValidationError("Source path must be an absolute host path.")
        return value

    def clean_local_dest_path(self):
        value = (self.cleaned_data.get("local_dest_path") or "").strip()
        if value and not value.startswith("/"):
            raise forms.ValidationError("Destination path must be an absolute host path.")
        return value

    def clean_password_file_path(self):
        value = self.cleaned_data["password_file_path"].strip()
        if value and not value.startswith("/"):
            raise forms.ValidationError("Password file path must be absolute.")
        return value

    def clean_ssh_password(self):
        value = (self.cleaned_data.get("ssh_password") or "").strip()
        if value:
            return value
        if self.instance.pk:
            return self.instance.ssh_password
        return value

    def clean_public_key_path(self):
        value = self.cleaned_data["public_key_path"].strip()
        if value and not value.startswith("/"):
            raise forms.ValidationError("Public key path must be absolute.")
        return value

    def clean_cloudflare_auth_home(self):
        value = self.cleaned_data["cloudflare_auth_home"].strip()
        if value and not value.startswith("/"):
            raise forms.ValidationError("Cloudflare auth home must be an absolute host path.")
        return value

    def clean_cloudflare_service_token_secret(self):
        value = (self.cleaned_data.get("cloudflare_service_token_secret") or "").strip()
        if value:
            return value
        if self.instance.pk:
            return self.instance.cloudflare_service_token_secret
        return value

    def clean_http_remote_token(self):
        value = (self.cleaned_data.get("http_remote_token") or "").strip()
        if value:
            return value
        if self.instance.pk:
            return self.instance.http_remote_token
        return value

    def clean(self):
        cleaned_data = super().clean()
        backup_type = cleaned_data.get("backup_type") or "remote"
        cleaned_data["backup_type"] = backup_type
        auth_mode = cleaned_data.get("auth_mode")
        local_dest_path = (cleaned_data.get("local_dest_path") or "").strip()
        password_file_path = (cleaned_data.get("password_file_path") or "").strip()
        ssh_password = (cleaned_data.get("ssh_password") or "").strip()
        public_key_path = (cleaned_data.get("public_key_path") or "").strip()
        install_public_key = cleaned_data.get("install_public_key")
        connection_mode = cleaned_data.get("connection_mode")
        cloudflare_auth_home = (cleaned_data.get("cloudflare_auth_home") or "").strip()
        cloudflare_service_token_id = (cleaned_data.get("cloudflare_service_token_id") or "").strip()
        cloudflare_service_token_secret = (cleaned_data.get("cloudflare_service_token_secret") or "").strip()
        http_remote_url = (cleaned_data.get("http_remote_url") or "").strip()
        http_remote_token = (cleaned_data.get("http_remote_token") or "").strip()
        http_remote_path = (cleaned_data.get("http_remote_path") or "").strip()
        http_direction = cleaned_data.get("http_direction") or "push"
        source_path = (cleaned_data.get("source_path") or "").strip()

        if backup_type == "local":
            if not source_path:
                self.add_error("source_path", "Local backups need a source folder.")
            if not local_dest_path:
                self.add_error("local_dest_path", "Local backups need a destination folder on this machine.")
        elif backup_type == "http":
            if http_direction == "push" and not source_path:
                self.add_error("source_path", "HTTP push backups need a local source folder.")
            if not http_remote_url:
                self.add_error("http_remote_url", "HTTP backups need the remote server URL.")
            if not http_remote_token:
                self.add_error("http_remote_token", "HTTP backups need the remote server Bearer token.")
            if not http_remote_path.startswith("/"):
                self.add_error("http_remote_path", "Remote folder must be an absolute path.")
            if http_direction == "pull" and not local_dest_path:
                self.add_error("local_dest_path", "Pull backups need a local destination folder.")
        else:
            if not source_path:
                self.add_error("source_path", "SSH backups need a source folder.")
            remote_host = (cleaned_data.get("remote_host") or "").strip()
            remote_user = (cleaned_data.get("remote_user") or "").strip()
            remote_dir = (cleaned_data.get("remote_dir") or "").strip()
            if not remote_host:
                self.add_error("remote_host", "Remote backups need a hostname or IP.")
            if not remote_user:
                self.add_error("remote_user", "Remote backups need an SSH user.")
            if not remote_dir:
                self.add_error("remote_dir", "Remote backups need a remote directory.")
            if auth_mode == "password_file" and not password_file_path:
                self.add_error("password_file_path", "Password file auth needs an absolute file path.")
            if auth_mode == "password_value" and not ssh_password:
                self.add_error("ssh_password", "Saved password auth needs a password.")
            if install_public_key and not public_key_path:
                self.add_error("public_key_path", "Public key installation needs a public key path.")
            if connection_mode == "cloudflare":
                if bool(cloudflare_service_token_id) != bool(cloudflare_service_token_secret):
                    self.add_error(
                        "cloudflare_service_token_secret",
                        "If you use Cloudflare service tokens, fill both the ID and the secret.",
                    )
        run_timeout_seconds = cleaned_data.get("run_timeout_seconds") or 0
        idle_timeout_seconds = cleaned_data.get("idle_timeout_seconds") or 0
        if idle_timeout_seconds and run_timeout_seconds and idle_timeout_seconds >= run_timeout_seconds:
            self.add_error("idle_timeout_seconds", "Idle timeout must be lower than the hard timeout.")

        return cleaned_data
