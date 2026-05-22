from django.contrib import admin

from .models import AlertEvent, AlertRule, BackupJob, BackupRun, MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, SystemSnapshot


@admin.register(MonitoringSettings)
class MonitoringSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "sample_interval_seconds",
        "top_process_limit",
        "history_retention_days",
        "notifications_enabled",
        "notifications_api_url",
        "updated_at",
    )


class ProcessSnapshotInline(admin.TabularInline):
    model = ProcessSnapshot
    extra = 0
    can_delete = False
    fields = (
        "pid",
        "name",
        "status",
        "username",
        "cpu_percent",
        "memory_percent",
        "memory_rss_mb",
        "threads",
    )
    readonly_fields = fields


@admin.register(SystemSnapshot)
class SystemSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "captured_at",
        "hostname",
        "cpu_percent",
        "memory_percent",
        "swap_percent",
        "disk_percent",
        "network_sent_mb",
        "network_recv_mb",
        "process_count_total",
    )
    list_filter = ("hostname",)
    search_fields = ("hostname", "platform_label")
    inlines = [ProcessSnapshotInline]


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = (
        "position",
        "name",
        "enabled",
        "severity",
        "metric",
        "evaluation_mode",
        "comparator",
        "threshold",
        "window_minutes",
        "cooldown_minutes",
    )
    list_display_links = ("name",)
    list_editable = ("position", "enabled")


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = (
        "triggered_at",
        "title",
        "severity",
        "is_active",
        "evaluated_value",
        "threshold",
        "notification_sent",
    )
    list_filter = ("severity", "is_active", "notification_sent")
    search_fields = ("title", "message", "rule__name")


@admin.register(ReportRule)
class ReportRuleAdmin(admin.ModelAdmin):
    list_display = (
        "position",
        "name",
        "enabled",
        "period_hours",
        "cadence_hours",
        "send_notifications",
        "last_run_at",
        "next_run_at",
    )
    list_display_links = ("name",)
    list_editable = ("position", "enabled", "send_notifications")


@admin.register(ReportRun)
class ReportRunAdmin(admin.ModelAdmin):
    list_display = (
        "generated_at",
        "title",
        "rule",
        "sample_count",
        "notification_sent",
        "notification_status_code",
    )
    list_filter = ("notification_sent", "rule")
    search_fields = ("title", "message", "rule__name")


@admin.register(BackupJob)
class BackupJobAdmin(admin.ModelAdmin):
    list_display = (
        "position",
        "name",
        "enabled",
        "source_path",
        "remote_host",
        "remote_dir",
        "schedule_minutes",
        "run_timeout_seconds",
        "idle_timeout_seconds",
        "last_run_at",
        "next_run_at",
    )
    list_display_links = ("name",)
    list_editable = ("position", "enabled")


@admin.register(BackupRun)
class BackupRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "job",
        "status",
        "exit_code",
        "summary",
        "launched_by",
        "runner_label",
        "created_remote_dir",
    )
    list_filter = ("status", "launched_by", "created_remote_dir", "job")
    search_fields = ("job__name", "summary", "log_output")
