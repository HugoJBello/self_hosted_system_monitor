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

ReportRuleFormSet = modelformset_factory(
    ReportRule,
    form=ReportRuleForm,
    extra=1,
    can_delete=True,
)

@method_decorator(csrf_exempt, name="dispatch")
class ReportsView(LoginRequiredMixin, View):
    template_name = "monitor/reports.html"

    def get(self, request):
        formset = ReportRuleFormSet(queryset=ReportRule.objects.all())
        return render(request, self.template_name, self._context(formset))

    def post(self, request):
        formset = ReportRuleFormSet(request.POST, queryset=ReportRule.objects.all())
        if formset.is_valid():
            instances = formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.delete()
            for instance in instances:
                if instance.enabled and instance.next_run_at is None:
                    instance.next_run_at = timezone.now() + timedelta(hours=max(instance.cadence_hours, 1))
                instance.save()
            messages.success(request, "Report schedules updated.")
            return redirect("monitor:reports")
        return render(request, self.template_name, self._context(formset))

    def _context(self, formset):
        latest_snapshot = SystemSnapshot.objects.order_by("-captured_at").first()
        recent_reports = ReportRun.objects.select_related("rule").order_by("-generated_at")[:20]
        rules = list(ReportRule.objects.all())
        settings_obj = MonitoringSettings.load()
        return {
            "formset": formset,
            "latest_snapshot": latest_snapshot,
            "recent_reports": recent_reports,
            "rules": rules,
            "rules_count": len(rules),
            "recent_reports_count": len(recent_reports),
            "settings_obj": settings_obj,
        }

class ReportDetailView(LoginRequiredMixin, View):
    template_name = "monitor/report_detail.html"

    def get(self, request, report_id):
        report = get_object_or_404(ReportRun.objects.select_related("rule"), pk=report_id)
        report_data = report.report_data or {}
        top_processes = [dict(process) for process in report_data.get("top_processes", [])]
        snapshot_ids = [process.get("latest_process_snapshot_id") for process in top_processes if process.get("latest_process_snapshot_id")]
        if not snapshot_ids and top_processes:
            latest_rows = (
                ProcessSnapshot.objects.filter(
                    snapshot__captured_at__gte=report.window_start,
                    snapshot__captured_at__lte=report.window_end,
                    name__in=[process.get("name", "") for process in top_processes],
                )
                .select_related("snapshot")
                .order_by("name", "username", "-snapshot__captured_at")
            )
            seen_keys = set()
            for process_snapshot in latest_rows:
                key = (process_snapshot.name, process_snapshot.username or "")
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                for process in top_processes:
                    if (process.get("name"), process.get("username") or "") == key:
                        process["latest_process_snapshot_id"] = process_snapshot.id
                        process["latest_pid"] = process_snapshot.pid
                        break
            snapshot_ids = [process.get("latest_process_snapshot_id") for process in top_processes if process.get("latest_process_snapshot_id")]

        snapshots_by_id = {
            process.id: process
            for process in _mark_historical_process_actions(
                list(ProcessSnapshot.objects.select_related("snapshot").filter(id__in=snapshot_ids))
            )
        }
        for process in top_processes:
            latest_process = snapshots_by_id.get(process.get("latest_process_snapshot_id"))
            if latest_process:
                process["control_available"] = latest_process.control_available
                process["control_unavailable_reason"] = latest_process.control_unavailable_reason
                process["container_id"] = latest_process.container_id
                process["container_name"] = latest_process.container_name
            else:
                process["control_available"] = False
                process["control_unavailable_reason"] = "Historical aggregate"
                process["container_id"] = ""
                process["container_name"] = ""
        report_data = {**report_data, "top_processes": top_processes}
        return render(
            request,
            self.template_name,
            {
                "report": report,
                "report_data": report_data,
                "chart_data": report_data.get("chart_data", {}),
                "settings_obj": MonitoringSettings.load(),
            },
        )

