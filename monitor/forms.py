import json
import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm, UserCreationForm
from django.utils import timezone
from zoneinfo import available_timezones

from .models import AlertRule, BackupJob, MonitoringSettings, ReportRule, ScriptJob


User = get_user_model()


class UserAdminCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "is_staff", "is_active")
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "is_staff": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({"class": "form-control"})
        self.fields["password2"].widget.attrs.update({"class": "form-control"})
        self.fields["is_staff"].label = "Admin user"
        self.fields["is_active"].initial = True


class UserAdminUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "is_staff", "is_active")
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "is_staff": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_is_staff(self):
        value = self.cleaned_data.get("is_staff")
        if self.instance.pk and self.instance.is_superuser and not value:
            raise forms.ValidationError("The bootstrap superuser must stay admin.")
        return value


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})


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
            "verify_mounted_device",
            "trigger_on_mount",
            "schedule_mode",
            "schedule_minutes",
            "remote_host",
            "remote_user",
            "remote_dir",
            "remote_direction",
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
            "verify_mounted_device": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "trigger_on_mount": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "schedule_mode": forms.Select(attrs={"class": "form-select backup-schedule-mode-select"}),
            "schedule_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 5, "max": 43200, "step": 5, "list": "backup-schedule-presets"}),
            "remote_host": forms.TextInput(attrs={"class": "form-control", "placeholder": "backup-host.example.com"}),
            "remote_user": forms.TextInput(attrs={"class": "form-control", "placeholder": "backupuser"}),
            "remote_dir": forms.TextInput(attrs={"class": "form-control", "placeholder": "/backups/server-a"}),
            "remote_direction": forms.Select(attrs={"class": "form-select"}),
            "ssh_port": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 65535}),
            "connection_mode": forms.Select(attrs={"class": "form-select backup-connection-mode-select"}),
            "cloudflare_auth_home": forms.TextInput(attrs={"class": "form-control", "placeholder": "/home/goku"}),
            "cloudflare_service_token_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Access service token ID"}),
            "cloudflare_service_token_secret": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Access service token secret"}, render_value=True),
            "http_remote_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://other-monitor.example.com/system_monitor"}),
            "http_remote_token": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Destination Bearer token"}, render_value=True),
            "http_remote_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/srv/data"}),
            "http_direction": forms.Select(attrs={"class": "form-select backup-http-direction-select"}),
            "auth_mode": forms.Select(attrs={"class": "form-select"}),
            "password_file_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/home/user/.ssh/backup.pass"}),
            "ssh_password": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Optional saved password"}, render_value=True),
            "public_key_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/home/user/.ssh/id_ed25519.pub"}),
            "install_public_key": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "delete_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "max_size": forms.TextInput(attrs={"class": "form-control", "placeholder": "100m"}),
            "run_timeout_seconds": forms.NumberInput(attrs={"class": "form-control d-none backup-timeout-seconds", "min": 60, "max": 604800, "step": 60}),
            "idle_timeout_seconds": forms.NumberInput(attrs={"class": "form-control d-none backup-timeout-seconds", "min": 30, "max": 86400, "step": 30}),
            "exclude_patterns": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "*.tmp\nnode_modules/"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["backup_type"].required = False
        self.fields["source_path"].required = False
        self.fields["remote_direction"].required = False
        self.fields["http_direction"].required = False
        self.fields["schedule_mode"].required = False
        self.fields["schedule_minutes"].required = False
        self.fields["source_path"].label = "Source folder"
        self.fields["local_dest_path"].label = "Destination folder"
        self.fields["remote_host"].label = "Hostname or IP"
        self.fields["remote_user"].label = "SSH user"
        self.fields["remote_direction"].label = "SSH copy direction"
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
        self.fields["schedule_mode"].label = "Schedule mode"
        self.fields["password_file_path"].label = "Password file on host"
        self.fields["public_key_path"].label = "Public key path on host"
        self.fields["run_timeout_seconds"].label = "Hard timeout (seconds)"
        self.fields["idle_timeout_seconds"].label = "Idle timeout (seconds)"
        self.fields["backup_type"].choices = [
            ("local", "Local memory backup"),
            ("remote", "SSH + rsync backup"),
            ("http", "HTTP server to server backup"),
        ]
        self.fields["schedule_mode"].choices = [
            ("interval", "Recurring schedule"),
            ("manual", "Run only when clicking Run now"),
        ]
        self.fields["connection_mode"].choices = [
            ("direct", "Standard SSH"),
            ("cloudflare", "This host needs Cloudflare SSH params"),
        ]
        self.fields["remote_direction"].choices = [
            ("push", "Local folder -> remote SSH directory"),
            ("pull", "Remote SSH directory -> local folder"),
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
        verify_mounted_device = bool(cleaned_data.get("verify_mounted_device"))
        trigger_on_mount = bool(cleaned_data.get("trigger_on_mount"))
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
        remote_direction = cleaned_data.get("remote_direction") or "push"
        cleaned_data["remote_direction"] = remote_direction
        schedule_mode = cleaned_data.get("schedule_mode") or "interval"
        schedule_minutes = cleaned_data.get("schedule_minutes") or 60
        cleaned_data["schedule_mode"] = schedule_mode
        cleaned_data["schedule_minutes"] = schedule_minutes

        if backup_type == "local":
            if not source_path:
                self.add_error("source_path", "Local backups need a source folder.")
            if not local_dest_path:
                self.add_error("local_dest_path", "Local backups need a destination folder on this machine.")
            if (
                local_dest_path
                and (verify_mounted_device or trigger_on_mount)
                and not local_dest_path.startswith(("/media/", "/mnt/", "/run/media/"))
                and local_dest_path not in {"/media", "/mnt", "/run/media"}
            ):
                self.add_error(
                    "local_dest_path",
                    "Mount-aware local backups must use a destination under /media, /mnt, or /run/media.",
                )
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
                message = (
                    "SSH pull backups need the local destination folder."
                    if remote_direction == "pull"
                    else "SSH backups need a local source folder."
                )
                self.add_error("source_path", message)
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


class ScriptJobForm(forms.ModelForm):
    script_arguments = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"data-script-arguments-input": "1"}))

    class Meta:
        model = ScriptJob
        fields = (
            "name",
            "description",
            "enabled",
            "schedule_mode",
            "schedule_minutes",
            "schedule_unit",
            "scheduled_for",
            "working_directory",
            "script_body",
            "script_arguments",
            "run_as_sudo",
            "sudo_password",
            "run_timeout_seconds",
            "idle_timeout_seconds",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "schedule_mode": forms.Select(attrs={"class": "form-select script-schedule-mode-select"}),
            "schedule_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 43200, "step": 1, "list": "script-schedule-presets"}),
            "schedule_unit": forms.Select(attrs={"class": "form-select"}),
            "scheduled_for": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "working_directory": forms.TextInput(attrs={"class": "form-control", "placeholder": "/root"}),
            "script_body": forms.Textarea(
                attrs={
                    "class": "form-control script-editor-textarea",
                    "rows": 16,
                    "placeholder": "#!/usr/bin/env bash\nset -euo pipefail\necho 'hello'",
                }
            ),
            "run_as_sudo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "sudo_password": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Optional sudo password"}, render_value=True),
            "run_timeout_seconds": forms.NumberInput(attrs={"class": "form-control d-none backup-timeout-seconds", "min": 30, "max": 604800, "step": 30}),
            "idle_timeout_seconds": forms.NumberInput(attrs={"class": "form-control d-none backup-timeout-seconds", "min": 30, "max": 86400, "step": 30}),
        }

    ARGUMENT_FLAG_RE = re.compile(r"^-{1,2}[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    MAX_ARGUMENTS_PER_GROUP = 40
    MAX_ARGUMENT_LENGTH = 500

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_for"].required = False
        self.fields["script_body"].required = False
        self.fields["schedule_minutes"].required = False
        self.fields["schedule_unit"].required = False
        self.fields["schedule_mode"].label = "Schedule mode"
        self.fields["schedule_mode"].choices = [
            ("manual", "Run only when clicking Run now"),
            ("interval", "Recurring schedule"),
            ("one_off", "Run once at a specific date and time"),
        ]
        self.fields["schedule_unit"].label = "Repeat unit"
        self.fields["schedule_unit"].choices = [
            ("minutes", "Minutes"),
            ("days", "Days"),
            ("weeks", "Weeks"),
        ]
        if not self.is_bound:
            if self.instance.pk:
                self.initial["script_arguments"] = json.dumps(self.instance.normalized_script_arguments, ensure_ascii=True)
            else:
                self.initial["script_arguments"] = json.dumps({"positionals": [], "flags": []}, ensure_ascii=True)
        if self.instance.pk and self.instance.scheduled_for:
            local_value = timezone.localtime(self.instance.scheduled_for)
            self.initial.setdefault("scheduled_for", local_value.strftime("%Y-%m-%dT%H:%M"))

    def clean_working_directory(self):
        value = (self.cleaned_data.get("working_directory") or "").strip()
        if value and not value.startswith("/"):
            raise forms.ValidationError("Working directory must be an absolute host path.")
        return value

    def clean_script_body(self):
        value = (self.cleaned_data.get("script_body") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not value:
            raise forms.ValidationError("Script content is required.")
        return value

    def clean_sudo_password(self):
        value = (self.cleaned_data.get("sudo_password") or "").strip()
        if value:
            return value
        if self.instance.pk:
            return self.instance.sudo_password
        return value

    def clean_script_arguments(self):
        raw_value = (self.cleaned_data.get("script_arguments") or "").strip()
        if not raw_value:
            return {"positionals": [], "flags": []}
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Script parameters must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise forms.ValidationError("Script parameters must use the expected object format.")

        normalized = {"positionals": [], "flags": []}
        for group_name in ("positionals", "flags"):
            items = payload.get(group_name, [])
            if not isinstance(items, list):
                raise forms.ValidationError("Script parameters must use valid positional and flag lists.")
            if len(items) > self.MAX_ARGUMENTS_PER_GROUP:
                raise forms.ValidationError("Too many script parameters.")

        for index, item in enumerate(payload.get("positionals", []), start=1):
            if not isinstance(item, dict):
                raise forms.ValidationError("Every positional parameter must be an object.")
            value = str(item.get("value", "")).strip()
            if not value:
                continue
            if "\x00" in value or len(value) > self.MAX_ARGUMENT_LENGTH:
                raise forms.ValidationError(f"Positional parameter {index} has an invalid value.")
            normalized["positionals"].append({"value": value})

        for index, item in enumerate(payload.get("flags", []), start=1):
            if not isinstance(item, dict):
                raise forms.ValidationError("Every flag parameter must be an object.")
            flag = str(item.get("flag", "")).strip()
            value = str(item.get("value", "")).strip()
            if not flag and not value:
                continue
            if not self.ARGUMENT_FLAG_RE.match(flag):
                raise forms.ValidationError(f"Flag parameter {index} must start with - or -- and use a single flag token.")
            if "\x00" in value or len(value) > self.MAX_ARGUMENT_LENGTH:
                raise forms.ValidationError(f"Flag parameter {index} has an invalid value.")
            normalized["flags"].append({"flag": flag, "value": value})
        return normalized

    def clean_scheduled_for(self):
        value = self.cleaned_data.get("scheduled_for")
        if value and timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value

    def clean(self):
        cleaned_data = super().clean()
        schedule_mode = cleaned_data.get("schedule_mode") or "manual"
        scheduled_for = cleaned_data.get("scheduled_for")
        schedule_value = cleaned_data.get("schedule_minutes") or 1
        schedule_unit = cleaned_data.get("schedule_unit") or "minutes"
        cleaned_data["schedule_unit"] = schedule_unit
        cleaned_data["schedule_minutes"] = schedule_value
        run_timeout_seconds = cleaned_data.get("run_timeout_seconds") or 0
        idle_timeout_seconds = cleaned_data.get("idle_timeout_seconds") or 0

        if schedule_mode == "manual":
            cleaned_data["scheduled_for"] = None
        elif schedule_mode == "one_off":
            if not scheduled_for:
                self.add_error("scheduled_for", "One-off jobs need an execution date and time.")
        else:
            cleaned_data["scheduled_for"] = None
            minimum = 5 if schedule_unit == "minutes" else 1
            if schedule_value < minimum:
                self.add_error("schedule_minutes", f"Recurring jobs need at least {minimum} {schedule_unit.rstrip('s')}.")

        if idle_timeout_seconds and run_timeout_seconds and idle_timeout_seconds >= run_timeout_seconds:
            self.add_error("idle_timeout_seconds", "Idle timeout must be lower than the hard timeout.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.script_arguments = self.cleaned_data.get("script_arguments") or {"positionals": [], "flags": []}
        if commit:
            instance.save()
            self.save_m2m()
        return instance
