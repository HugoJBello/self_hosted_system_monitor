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

from monitor_app.views import _mark_historical_process_actions

class HistoryView(LoginRequiredMixin, View):
    template_name = "monitor/history.html"

    def get(self, request):
        hours = request.GET.get("hours", "24")
        try:
            hours = max(1, min(int(hours), 24 * 30))
        except ValueError:
            hours = 24

        settings_obj = MonitoringSettings.load()
        window_end = timezone.now()
        cutoff = window_end - timedelta(hours=hours)
        snapshots_qs = SystemSnapshot.objects.filter(captured_at__gte=cutoff).order_by("captured_at")
        snapshots = list(
            snapshots_qs.values(
                "captured_at",
                "cpu_percent",
                "memory_percent",
                "memory_used_mb",
                "memory_available_mb",
                "memory_cached_mb",
                "memory_buffers_mb",
                "memory_slab_mb",
                "swap_percent",
                "disk_percent",
                "load_avg_1",
                "network_sent_rate_kbps",
                "network_recv_rate_kbps",
                "process_count_total",
                "process_count_running",
            )
        )
        latest_snapshot = snapshots_qs.order_by("-captured_at").prefetch_related("processes").first()
        chart_data = build_time_series_chart_data(
            snapshots,
            hours=hours,
            sample_interval_seconds=settings_obj.sample_interval_seconds,
            window_start=cutoff,
            window_end=window_end,
            target_points=96,
        )

        aggregates = snapshots_qs.aggregate(
            avg_cpu=Avg("cpu_percent"),
            avg_memory=Avg("memory_percent"),
            avg_memory_used_mb=Avg("memory_used_mb"),
            avg_memory_available_mb=Avg("memory_available_mb"),
            avg_memory_cached_mb=Avg("memory_cached_mb"),
            avg_memory_buffers_mb=Avg("memory_buffers_mb"),
            avg_memory_slab_mb=Avg("memory_slab_mb"),
            avg_disk=Avg("disk_percent"),
            max_cpu=Max("cpu_percent"),
            max_memory=Max("memory_percent"),
            avg_process_total=Avg("process_count_total"),
            avg_process_running=Avg("process_count_running"),
        )

        grouped_process_rows = list(
            ProcessSnapshot.objects.filter(snapshot__captured_at__gte=cutoff)
            .select_related("snapshot")
            .values(
                "id",
                "pid",
                "name",
                "username",
                "status",
                "command",
                "cpu_percent",
                "memory_percent",
                "memory_rss_mb",
                "snapshot__captured_at",
            )
            .order_by("name", "username", "-snapshot__captured_at")
        )
        grouped_processes = defaultdict(
            lambda: {
                "name": "",
                "username": "",
                "samples": 0,
                "avg_cpu_sum": 0.0,
                "avg_memory_sum": 0.0,
                "peak_cpu": 0.0,
                "peak_memory": 0.0,
                "max_rss_mb": 0.0,
                "last_seen_at": None,
                "latest_process_snapshot_id": None,
                "latest_pid": None,
                "statuses": set(),
                "commands": [],
                "control_available": False,
                "control_unavailable_reason": "Historical aggregate",
            }
        )
        for row in grouped_process_rows:
            key = (row["name"], row["username"] or "")
            entry = grouped_processes[key]
            entry["name"] = row["name"]
            entry["username"] = row["username"] or ""
            entry["samples"] += 1
            entry["avg_cpu_sum"] += float(row["cpu_percent"] or 0)
            entry["avg_memory_sum"] += float(row["memory_percent"] or 0)
            entry["peak_cpu"] = max(entry["peak_cpu"], float(row["cpu_percent"] or 0))
            entry["peak_memory"] = max(entry["peak_memory"], float(row["memory_percent"] or 0))
            entry["max_rss_mb"] = max(entry["max_rss_mb"], float(row["memory_rss_mb"] or 0))
            if entry["last_seen_at"] is None or row["snapshot__captured_at"] > entry["last_seen_at"]:
                entry["last_seen_at"] = row["snapshot__captured_at"]
                entry["latest_process_snapshot_id"] = row["id"]
                entry["latest_pid"] = row["pid"]
            if row["status"]:
                entry["statuses"].add(row["status"])
            command = (row["command"] or "").strip()
            if command and command not in entry["commands"] and len(entry["commands"]) < 3:
                entry["commands"].append(command)

        expensive_processes_period = sorted(
            [
                {
                    "name": entry["name"],
                    "username": entry["username"],
                    "samples": entry["samples"],
                    "avg_cpu": entry["avg_cpu_sum"] / entry["samples"],
                    "peak_cpu": entry["peak_cpu"],
                    "avg_memory": entry["avg_memory_sum"] / entry["samples"],
                    "peak_memory": entry["peak_memory"],
                    "max_rss_mb": entry["max_rss_mb"],
                    "last_seen_at": entry["last_seen_at"],
                    "latest_process_snapshot_id": entry["latest_process_snapshot_id"],
                    "latest_pid": entry["latest_pid"],
                    "control_available": entry["control_available"],
                    "control_unavailable_reason": entry["control_unavailable_reason"],
                    "statuses": sorted(entry["statuses"]),
                    "commands": entry["commands"],
                }
                for entry in grouped_processes.values()
            ],
            key=lambda item: (item["avg_cpu"], item["peak_memory"], item["max_rss_mb"]),
            reverse=True,
        )[:8]
        latest_snapshot_ids = [
            process["latest_process_snapshot_id"]
            for process in expensive_processes_period
            if process["latest_process_snapshot_id"]
        ]
        snapshots_by_id = {
            process.id: process
            for process in _mark_historical_process_actions(
                list(ProcessSnapshot.objects.select_related("snapshot").filter(id__in=latest_snapshot_ids))
            )
        }
        for process in expensive_processes_period:
            latest_process = snapshots_by_id.get(process["latest_process_snapshot_id"])
            if latest_process:
                process["control_available"] = latest_process.control_available
                process["control_unavailable_reason"] = latest_process.control_unavailable_reason
                process["container_id"] = latest_process.container_id
                process["container_name"] = latest_process.container_name
        expensive_processes_point = _mark_historical_process_actions(list(latest_snapshot.processes.all()[:8])) if latest_snapshot else []

        return render(
            request,
            self.template_name,
            {
                "hours": hours,
                "chart_data": chart_data,
                "snapshot_count": len(snapshots),
                "aggregates": aggregates,
                "latest_snapshot": latest_snapshot,
                "latest_memory_breakdown": build_snapshot_memory_breakdown(latest_snapshot),
                "average_memory_breakdown": build_memory_breakdown(
                    used_mb=aggregates["avg_memory_used_mb"],
                    available_mb=aggregates["avg_memory_available_mb"],
                    cached_mb=aggregates["avg_memory_cached_mb"],
                    buffers_mb=aggregates["avg_memory_buffers_mb"],
                    slab_mb=aggregates["avg_memory_slab_mb"],
                ),
                "expensive_processes_period": expensive_processes_period,
                "expensive_processes_point": expensive_processes_point,
                "settings_obj": settings_obj,
            },
        )

