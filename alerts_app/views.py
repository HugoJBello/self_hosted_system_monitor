from datetime import timedelta
from collections import defaultdict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.http import JsonResponse
from django.forms import modelformset_factory
from django.db.models import Avg, Max, Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from alerts_app.services import ensure_default_alert_rules, top_processes_for_alert_window
from backups_app.services import _normalize_stream_output, get_runtime_state, list_browser_roots, list_directory_children, mark_stale_running_backups, request_backup_run_stop, start_background_backup
from main_app.forms import AlertRuleForm, BackupJobForm, MonitoringSettingsForm, ReportRuleForm, ScriptJobForm, StyledPasswordChangeForm, StyledSetPasswordForm, UserAdminCreateForm, UserAdminUpdateForm
from main_app.models import AlertEvent, AlertRule, BackupJob, BackupRun, MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, ScriptJob, ScriptJobRun, SystemSnapshot, VolumeOperation
from main_app.notification_client import build_test_payload, send_json_notification
from volumes_app.path_browser import create_directory as create_path_directory, list_browser_roots as list_path_browser_roots, list_directory_children as list_path_directory_children
from monitor_app.process_control import ProcessControlError, container_info_for_pid, docker_container_action, kill_process, reboot_host, restart_process, terminate_process, validate_process_identity
from monitor_app.memory import build_memory_breakdown, build_snapshot_memory_breakdown
from reports_app.services import build_time_series_chart_data
from jobs_app.services import get_runtime_state as get_script_runtime_state, mark_stale_running_script_jobs, request_script_run_stop, start_background_script_job
from monitor_app.services import _process_rows
from volumes_app.services import list_volumes, mount_volume, remember_mount_preference, start_background_volume_operation, unmount_volume


User = get_user_model()

from monitor_app.views import _mark_historical_process_actions

AlertRuleFormSet = modelformset_factory(
    AlertRule,
    form=AlertRuleForm,
    extra=1,
    can_delete=True,
)

@method_decorator(csrf_exempt, name="dispatch")
class AlertsView(LoginRequiredMixin, View):
    template_name = "monitor/alerts.html"

    def get(self, request):
        ensure_default_alert_rules()
        formset = AlertRuleFormSet(queryset=AlertRule.objects.all())
        return render(request, self.template_name, self._context(formset))

    def post(self, request):
        ensure_default_alert_rules()
        formset = AlertRuleFormSet(request.POST, queryset=AlertRule.objects.all())
        if formset.is_valid():
            instances = formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.delete()
            for instance in instances:
                instance.save()
            messages.success(request, "Alert rules updated.")
            return redirect("monitor:alerts")
        return render(request, self.template_name, self._context(formset))

    def _context(self, formset):
        latest_snapshot = SystemSnapshot.objects.order_by("-captured_at").first()
        recent_events = AlertEvent.objects.select_related("rule").order_by("-triggered_at")[:20]
        rules = list(AlertRule.objects.all())
        return {
            "formset": formset,
            "latest_snapshot": latest_snapshot,
            "recent_events": recent_events,
            "active_events_count": AlertEvent.objects.filter(is_active=True).count(),
            "rules_count": len(rules),
            "rules": rules,
            "settings_obj": MonitoringSettings.load(),
            "alert_metrics": dict(AlertRule.METRIC_CHOICES),
            "alert_modes": dict(AlertRule.EVALUATION_CHOICES),
            "alert_comparators": dict(AlertRule.COMPARATOR_CHOICES),
            "severity_icons": {
                "info": "bi-info-circle",
                "warning": "bi-exclamation-triangle",
                "critical": "bi-radioactive",
            },
            "metric_icons": {
                "cpu_percent": "bi-cpu",
                "memory_percent": "bi-memory",
                "swap_percent": "bi-arrow-left-right",
                "disk_percent": "bi-device-hdd",
                "load_avg_1": "bi-speedometer2",
                "load_avg_5": "bi-speedometer2",
                "load_avg_15": "bi-speedometer2",
                "network_sent_rate_kbps": "bi-upload",
                "network_recv_rate_kbps": "bi-download",
                "process_count_total": "bi-diagram-3",
                "process_count_running": "bi-play-circle",
                "process_count_zombie": "bi-bug",
            },
            "active_events": [event for event in recent_events if event.is_active],
        }

class AlertDetailView(LoginRequiredMixin, View):
    template_name = "monitor/alert_detail.html"

    def get(self, request, event_id):
        event = get_object_or_404(
            AlertEvent.objects.select_related("rule", "snapshot").prefetch_related("snapshot__processes"),
            pk=event_id,
        )
        trigger_snapshot = event.snapshot
        window_minutes = max(event.window_minutes, 1)
        context_cutoff_start = trigger_snapshot.captured_at - timedelta(minutes=window_minutes)
        context_cutoff_end = trigger_snapshot.captured_at + timedelta(minutes=window_minutes)
        context_snapshots = list(
            SystemSnapshot.objects.filter(
                captured_at__gte=context_cutoff_start,
                captured_at__lte=context_cutoff_end,
            )
            .order_by("captured_at")[:20]
        )
        chart_data = {
            "labels": [item.captured_at.strftime("%H:%M:%S") for item in context_snapshots],
            "label_datetimes": [item.captured_at.isoformat() for item in context_snapshots],
            "metric_values": [getattr(item, event.metric, 0) for item in context_snapshots],
            "threshold": [event.threshold for _ in context_snapshots],
        }
        alert_window_processes = top_processes_for_alert_window(event.rule, trigger_snapshot, limit=8)
        trigger_processes = _mark_historical_process_actions(list(trigger_snapshot.processes.all()))
        return render(
            request,
            self.template_name,
            {
                "event": event,
                "trigger_snapshot": trigger_snapshot,
                "trigger_processes": trigger_processes,
                "context_snapshots": context_snapshots,
                "chart_data": chart_data,
                "alert_window_processes": alert_window_processes,
                "settings_obj": MonitoringSettings.load(),
                "alert_metrics": dict(AlertRule.METRIC_CHOICES),
                "alert_modes": dict(AlertRule.EVALUATION_CHOICES),
                "alert_comparators": dict(AlertRule.COMPARATOR_CHOICES),
                "severity_icons": {
                    "info": "bi-info-circle",
                    "warning": "bi-exclamation-triangle",
                    "critical": "bi-radioactive",
                },
            },
        )

