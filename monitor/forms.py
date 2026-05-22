from django import forms

from .models import AlertRule, MonitoringSettings, ReportRule


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
        }

    def clean_notifications_default_channels(self):
        value = self.cleaned_data["notifications_default_channels"].strip()
        allowed = {"email", "telegram", "xmpp"}
        channels = [item.strip().lower() for item in value.replace(",", ";").split(";") if item.strip()]
        invalid = [item for item in channels if item not in allowed]
        if invalid:
            raise forms.ValidationError("Channels must be any combination of email, telegram, and xmpp.")
        return ";".join(channels)


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
