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
from main_app.models import MonitoringSettings
from monitor_app.models import ProcessSnapshot, SystemSnapshot
from alerts_app.models import AlertEvent, AlertRule
from reports_app.models import ReportRule, ReportRun
from jobs_app.models import ScriptJob, ScriptJobRun
from backups_app.models import BackupJob, BackupRun
from volumes_app.models import VolumeOperation
from main_app.notification_client import build_test_payload, send_json_notification
from volumes_app.path_browser import create_directory as create_path_directory, list_browser_roots as list_path_browser_roots, list_directory_children as list_path_directory_children
from monitor_app.process_control import ProcessControlError, container_info_for_pid, docker_container_action, kill_process, reboot_host, restart_process, terminate_process, validate_process_identity
from monitor_app.memory import build_memory_breakdown, build_snapshot_memory_breakdown
from reports_app.services import build_time_series_chart_data
from jobs_app.services import get_runtime_state as get_script_runtime_state, mark_stale_running_script_jobs, request_script_run_stop, start_background_script_job
from monitor_app.services import _process_rows
from volumes_app.services import list_volumes, mount_volume, remember_mount_preference, start_background_volume_operation, unmount_volume


User = get_user_model()

def healthz_view(request):
    return JsonResponse({"ok": True})

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

class RedirectHomeView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect("monitor:system-monitor")


def _safe_next_url(request):
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("monitor:system-monitor")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return _with_app_subpath(next_url)
    return reverse("monitor:system-monitor")


def _with_app_subpath(url):
    app_subpath = getattr(settings, "APP_SUBPATH", "")
    if not app_subpath or not url.startswith("/") or url.startswith("//"):
        return url
    if url == app_subpath or url.startswith(f"{app_subpath}/"):
        return url
    return f"{app_subpath}{url}"


def _process_action_context_from_snapshot(process_snapshot):
    return {
        "pid": process_snapshot.pid,
        "name": process_snapshot.name,
        "username": process_snapshot.username,
        "command": process_snapshot.command,
        "observed_at": process_snapshot.snapshot.captured_at,
    }


def _apply_process_container_metadata(process):
    pid = process["pid"] if isinstance(process, dict) else process.pid
    container_id, container_name = container_info_for_pid(pid)
    if isinstance(process, dict):
        process["container_id"] = container_id
        process["container_name"] = container_name
    else:
        process.container_id = container_id
        process.container_name = container_name
    return process


def _apply_process_container_metadata_many(processes):
    for process in processes:
        _apply_process_container_metadata(process)
    return processes


def _mark_historical_process_actions(processes):
    for process in processes:
        process.control_available = False
        process.control_unavailable_reason = "Historical only"
        process.container_id = ""
        process.container_name = ""

        try:
            current = validate_process_identity(
                process.pid,
                expected_name=process.name,
                expected_username=process.username,
                expected_command=process.command,
                observed_at=process.snapshot.captured_at,
            )
        except ProcessControlError as exc:
            process.control_unavailable_reason = str(exc)
        else:
            process.control_available = True
            process.control_unavailable_reason = ""
            process.container_id = current.container_id or ""
            process.container_name = current.container_name or ""

    return processes


class ProcessActionView(AdminRequiredMixin, View):
    def post(self, request):
        next_url = _safe_next_url(request)
        action = request.POST.get("action", "")
        confirmed = request.POST.get("confirmed") == "yes"

        if not confirmed:
            messages.error(request, "Action was not confirmed.")
            return redirect(next_url)

        if action == "reboot":
            try:
                reboot_host()
            except ProcessControlError as exc:
                messages.error(request, str(exc))
            else:
                messages.warning(request, "Host reboot requested.")
            return redirect(next_url)

        try:
            pid = int(request.POST.get("pid", "0"))
        except ValueError:
            messages.error(request, "Invalid PID.")
            return redirect(next_url)

        process_snapshot_id = request.POST.get("process_snapshot_id")
        if process_snapshot_id:
            process_snapshot = get_object_or_404(
                ProcessSnapshot.objects.select_related("snapshot"),
                pk=process_snapshot_id,
            )
            identity = _process_action_context_from_snapshot(process_snapshot)
            if process_snapshot.pid != pid:
                messages.error(request, "PID does not match the selected historical process.")
                return redirect(next_url)
        else:
            identity = {
                "pid": pid,
                "name": request.POST.get("expected_name", ""),
                "username": request.POST.get("expected_username", ""),
                "command": request.POST.get("expected_command", ""),
                "observed_at": None,
            }

        try:
            current = validate_process_identity(
                pid,
                expected_name=identity["name"],
                expected_username=identity["username"],
                expected_command=identity["command"],
                observed_at=identity["observed_at"],
            )
            if current.container_id:
                container_label = current.container_name or current.container_id[:12]
                if action == "terminate":
                    docker_container_action(current.container_id, "stop")
                    messages.warning(request, f"Docker container '{container_label}' stop requested.")
                elif action == "kill":
                    docker_container_action(current.container_id, "kill")
                    messages.warning(request, f"Docker container '{container_label}' killed.")
                elif action == "restart":
                    docker_container_action(current.container_id, "restart")
                    messages.warning(request, f"Docker container '{container_label}' restarted.")
                else:
                    messages.error(request, "Unknown process action.")
            elif action == "terminate":
                terminate_process(pid)
                messages.warning(request, f"SIGTERM sent to {current.name} ({pid}).")
            elif action == "kill":
                kill_process(pid)
                messages.warning(request, f"SIGKILL sent to {current.name} ({pid}).")
            elif action == "restart":
                restart_process(current)
                messages.warning(request, f"Restart requested for {current.name} ({pid}).")
            else:
                messages.error(request, "Unknown process action.")
        except ProcessControlError as exc:
            messages.error(request, str(exc))
        return redirect(next_url)

class SystemMonitorView(LoginRequiredMixin, View):
    template_name = "monitor_app/system_monitor.html"

    def get(self, request):
        latest_snapshot = (
            SystemSnapshot.objects.prefetch_related("processes")
            .order_by("-captured_at")
            .first()
        )
        sort = request.GET.get("sort", "cpu_percent")
        direction = request.GET.get("dir", "desc")
        try:
            process_page_number = max(int(request.GET.get("process_page", "1")), 1)
        except ValueError:
            process_page_number = 1
        try:
            process_per_page = min(max(int(request.GET.get("per_page", "25")), 10), 200)
        except ValueError:
            process_per_page = 25
        try:
            auto_refresh_seconds = max(int(request.GET.get("auto_refresh", "0")), 0)
        except ValueError:
            auto_refresh_seconds = 0

        live_process_page = None
        process_sort_fields = {
            "pid": "pid",
            "name": "name",
            "status": "status",
            "cpu_percent": "cpu_percent",
            "memory_percent": "memory_percent",
            "memory_rss_mb": "memory_rss_mb",
            "threads": "threads",
            "username": "username",
        }
        sort = sort if sort in process_sort_fields else "cpu_percent"
        direction = "asc" if direction == "asc" else "desc"
        if latest_snapshot:
            live_process_rows = _process_rows(None)["rows"]

            def process_sort_key(item):
                value = item.get(process_sort_fields[sort])
                if isinstance(value, str):
                    return value.lower()
                return value if value is not None else 0

            live_process_rows.sort(key=process_sort_key, reverse=(direction == "desc"))
            live_process_page = Paginator(live_process_rows, process_per_page).get_page(process_page_number)
            _apply_process_container_metadata_many(live_process_page.object_list)

        context = {
            "latest_snapshot": latest_snapshot,
            "memory_breakdown": build_snapshot_memory_breakdown(latest_snapshot),
            "settings_obj": MonitoringSettings.load(),
            "live_process_page": live_process_page,
            "process_sort": sort,
            "process_dir": direction,
            "process_per_page": process_per_page,
            "auto_refresh_seconds": auto_refresh_seconds,
        }
        return render(request, self.template_name, context)

