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

class VolumeTreeView(LoginRequiredMixin, View):
    def get(self, request):
        host_path = request.GET.get("path", "/")
        try:
            items = list_path_directory_children(host_path)
        except ValueError as exc:
            return JsonResponse({"items": [], "error": str(exc)}, status=400)
        return JsonResponse({"items": items})

    def post(self, request):
        try:
            item = create_path_directory(request.POST.get("parent_path") or "/", request.POST.get("folder_name") or "")
        except ValueError as exc:
            return JsonResponse({"item": None, "error": str(exc)}, status=400)
        return JsonResponse({"item": item})


class VolumesView(LoginRequiredMixin, View):
    template_name = "monitor/volumes.html"

    def get(self, request):
        return render(request, self.template_name, self._context())

    def post(self, request):
        action = request.POST.get("volume_action")
        sudo_password = request.POST.get("sudo_password") or ""
        try:
            if action == "mount":
                result = mount_volume(
                    request.POST.get("device"),
                    request.POST.get("mountpoint"),
                    fstype=request.POST.get("fstype") or "",
                    options=request.POST.get("options") or "",
                    sudo_password=sudo_password,
                )
                remember_mount_preference(
                    device=request.POST.get("device") or "",
                    uuid=request.POST.get("uuid") or "",
                    label=request.POST.get("label") or "",
                    model=request.POST.get("model") or "",
                    serial=request.POST.get("serial") or "",
                    mountpoint=request.POST.get("mountpoint") or "",
                )
            elif action == "unmount":
                result = unmount_volume(
                    request.POST.get("target"),
                    device=request.POST.get("device") or "",
                    sudo_password=sudo_password,
                    force=request.POST.get("force_unmount") == "on",
                )
            elif action == "label":
                operation = start_background_volume_operation(
                    action="label",
                    device=request.POST.get("device"),
                    fstype=request.POST.get("fstype") or "",
                    label=request.POST.get("label") or "",
                    sudo_password=sudo_password,
                )
                messages.info(request, f"Volume label operation started for {operation.device}.")
                return redirect("monitor:volume-operation-detail", operation_id=operation.id)
            elif action == "format":
                operation = start_background_volume_operation(
                    action="format",
                    device=request.POST.get("device"),
                    fstype=request.POST.get("format_fstype") or "",
                    label=request.POST.get("format_label") or "",
                    confirm_text=request.POST.get("confirm_text") or "",
                    confirm_device=request.POST.get("confirm_device") or "",
                    sudo_password=sudo_password,
                )
                messages.warning(request, f"Format operation started for {operation.device}.")
                return redirect("monitor:volume-operation-detail", operation_id=operation.id)
            else:
                messages.error(request, "Unknown volume action.")
                return redirect("monitor:volumes")
        except ProcessControlError as exc:
            messages.error(request, str(exc))
            return redirect("monitor:volumes")
        messages.success(request, result.message)
        return redirect("monitor:volumes")

    def _context(self):
        volumes = list_volumes()
        return {
            **volumes,
            "running_volume_operations": VolumeOperation.objects.filter(status="running").order_by("-started_at")[:8],
            "browser_roots": list_path_browser_roots(),
            "volume_tree_url": reverse("monitor:volume-tree"),
            "settings_obj": MonitoringSettings.load(),
        }


class VolumeOperationDetailView(LoginRequiredMixin, View):
    template_name = "monitor/volume_operation_detail.html"

    def get(self, request, operation_id):
        operation = get_object_or_404(VolumeOperation, pk=operation_id)
        return render(request, self.template_name, {"operation": operation, "settings_obj": MonitoringSettings.load()})


class VolumeOperationsView(LoginRequiredMixin, View):
    template_name = "monitor/volume_operations.html"

    def get(self, request):
        query = (request.GET.get("q") or "").strip()
        status = request.GET.get("status") or "all"
        action = request.GET.get("action") or "all"
        operations_qs = VolumeOperation.objects.order_by("-started_at")
        if query:
            operations_qs = operations_qs.filter(
                Q(device__icontains=query)
                | Q(summary__icontains=query)
                | Q(label__icontains=query)
                | Q(fstype__icontains=query)
                | Q(command_line__icontains=query)
            )
        if status in {choice[0] for choice in VolumeOperation.STATUS_CHOICES}:
            operations_qs = operations_qs.filter(status=status)
        if action in {choice[0] for choice in VolumeOperation.ACTION_CHOICES}:
            operations_qs = operations_qs.filter(action=action)
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        paginator = Paginator(operations_qs, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "page_obj": page_obj,
                "query": query,
                "status_filter": status,
                "action_filter": action,
                "status_choices": VolumeOperation.STATUS_CHOICES,
                "action_choices": VolumeOperation.ACTION_CHOICES,
                "pagination_query": pagination_params.urlencode(),
                "settings_obj": MonitoringSettings.load(),
            },
        )


class VolumeOperationStatusView(LoginRequiredMixin, View):
    def get(self, request, operation_id):
        operation = get_object_or_404(VolumeOperation, pk=operation_id)
        return JsonResponse(
            {
                "id": operation.id,
                "action": operation.action,
                "action_label": operation.get_action_display(),
                "device": operation.device,
                "fstype": operation.fstype,
                "label": operation.label,
                "status": operation.status,
                "status_label": operation.get_status_display(),
                "summary": operation.summary,
                "log_output": operation.log_output,
                "command_line": operation.command_line,
                "process_pid": operation.process_pid,
                "runner_label": operation.runner_label,
                "started_at": operation.started_at.isoformat() if operation.started_at else None,
                "finished_at": operation.finished_at.isoformat() if operation.finished_at else None,
            }
        )

