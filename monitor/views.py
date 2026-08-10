from datetime import timedelta
from collections import defaultdict

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

from .alerting import ensure_default_alert_rules, top_processes_for_alert_window
from .backups import _normalize_stream_output, get_runtime_state, list_browser_roots, list_directory_children, mark_stale_running_backups, request_backup_run_stop, start_background_backup
from .forms import AlertRuleForm, BackupJobForm, MonitoringSettingsForm, ReportRuleForm, ScriptJobForm, StyledPasswordChangeForm, StyledSetPasswordForm, UserAdminCreateForm, UserAdminUpdateForm
from .models import AlertEvent, AlertRule, BackupJob, BackupRun, MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, ScriptJob, ScriptJobRun, SystemSnapshot, VolumeOperation
from .notification_client import build_test_payload, send_json_notification
from .path_browser import list_browser_roots as list_path_browser_roots, list_directory_children as list_path_directory_children
from .process_control import ProcessControlError, container_info_for_pid, docker_container_action, kill_process, reboot_host, restart_process, terminate_process, validate_process_identity
from .memory import build_memory_breakdown, build_snapshot_memory_breakdown
from .reporting import build_time_series_chart_data
from .script_jobs import get_runtime_state as get_script_runtime_state, mark_stale_running_script_jobs, request_script_run_stop, start_background_script_job
from .services import _process_rows
from .volumes import list_volumes, mount_volume, remember_mount_preference, start_background_volume_operation, unmount_volume


User = get_user_model()


def healthz_view(request):
    return JsonResponse({"ok": True})


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class LoginView(auth_views.LoginView):
    template_name = "monitor/login.html"
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


class PasswordView(LoginRequiredMixin, View):
    template_name = "monitor/password.html"

    def get(self, request):
        return render(request, self.template_name, {"form": StyledPasswordChangeForm(request.user), "settings_obj": MonitoringSettings.load()})

    def post(self, request):
        form = StyledPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Password updated. Sign in again with the new password.")
            return redirect("monitor:login")
        return render(request, self.template_name, {"form": form, "settings_obj": MonitoringSettings.load()})


class UsersView(AdminRequiredMixin, View):
    template_name = "monitor/users.html"

    def get(self, request):
        return render(request, self.template_name, self._context())

    def post(self, request):
        if "create_user" in request.POST:
            form = UserAdminCreateForm(request.POST, prefix="new")
            if form.is_valid():
                user = form.save(commit=False)
                if user.is_staff:
                    user.is_superuser = True
                user.save()
                messages.success(request, f"User '{user.username}' created.")
                return redirect("monitor:users")
            return render(request, self.template_name, self._context(create_form=form))

        user = get_object_or_404(User, pk=request.POST.get("user_id"))
        if "save_user" in request.POST:
            form = UserAdminUpdateForm(request.POST, instance=user, prefix=f"user-{user.id}")
            if form.is_valid():
                updated = form.save(commit=False)
                updated.is_superuser = bool(updated.is_staff)
                updated.save()
                messages.success(request, f"User '{updated.username}' updated.")
                return redirect("monitor:users")
            return render(request, self.template_name, self._context(form_overrides={user.id: form}))
        if "set_password" in request.POST:
            form = StyledSetPasswordForm(user, request.POST, prefix=f"pass-{user.id}")
            if form.is_valid():
                form.save()
                messages.success(request, f"Password updated for '{user.username}'.")
                return redirect("monitor:users")
            return render(request, self.template_name, self._context(password_form_overrides={user.id: form}))
        return redirect("monitor:users")

    def _context(self, create_form=None, form_overrides=None, password_form_overrides=None):
        form_overrides = form_overrides or {}
        password_form_overrides = password_form_overrides or {}
        users = list(User.objects.order_by("username"))
        user_rows = [
            {
                "user": user,
                "form": form_overrides.get(user.id) or UserAdminUpdateForm(instance=user, prefix=f"user-{user.id}"),
                "password_form": password_form_overrides.get(user.id) or StyledSetPasswordForm(user, prefix=f"pass-{user.id}"),
            }
            for user in users
        ]
        return {
            "users": users,
            "user_rows": user_rows,
            "create_form": create_form or UserAdminCreateForm(prefix="new"),
            "settings_obj": MonitoringSettings.load(),
        }


def _best_effort_reconcile_backups():
    try:
        mark_stale_running_backups()
    except OperationalError:
        pass


def _best_effort_reconcile_script_jobs():
    try:
        mark_stale_running_script_jobs()
    except OperationalError:
        pass


class RedirectHomeView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect("monitor:system-monitor")


def _safe_next_url(request):
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("monitor:system-monitor")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse("monitor:system-monitor")


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


@method_decorator(csrf_exempt, name="dispatch")
class SettingsView(AdminRequiredMixin, View):
    template_name = "monitor/settings.html"

    def get(self, request):
        settings_obj = MonitoringSettings.load()
        form = MonitoringSettingsForm(instance=settings_obj)
        return render(request, self.template_name, self._context(form, settings_obj))

    def post(self, request):
        settings_obj = MonitoringSettings.load()
        form = MonitoringSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            settings_obj = form.save()
            if "send_test_notification" in request.POST:
                if not settings_obj.notifications_enabled:
                    messages.warning(request, "Notifications are disabled. Enable them before sending a test.")
                elif not settings_obj.notifications_api_url or not settings_obj.notifications_api_token:
                    messages.error(request, "Notifications API URL and API token are required to send a test.")
                else:
                    latest_snapshot = SystemSnapshot.objects.order_by("-captured_at").first()
                    payload = build_test_payload(settings_obj, latest_snapshot)
                    result = send_json_notification(settings_obj, payload)
                    if result["ok"]:
                        messages.success(
                            request,
                            f"Test notification delivered with HTTP {result['status_code']}.",
                        )
                    else:
                        messages.error(
                            request,
                            f"Test notification failed ({result['status_code'] or 'connection error'}): {result['body']}",
                        )
            else:
                messages.success(request, "Monitoring settings updated.")
            return redirect("monitor:settings")
        return render(request, self.template_name, self._context(form, settings_obj))

    def _context(self, form, settings_obj):
        return {
            "form": form,
            "settings_obj": settings_obj,
            "settings_users": list(User.objects.order_by("username")),
        }


AlertRuleFormSet = modelformset_factory(
    AlertRule,
    form=AlertRuleForm,
    extra=1,
    can_delete=True,
)

ReportRuleFormSet = modelformset_factory(
    ReportRule,
    form=ReportRuleForm,
    extra=1,
    can_delete=True,
)

class SystemMonitorView(LoginRequiredMixin, View):
    template_name = "monitor/system_monitor.html"

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


@method_decorator(csrf_exempt, name="dispatch")
class ScriptJobsView(LoginRequiredMixin, View):
    template_name = "monitor/script_jobs.html"

    def get(self, request):
        _best_effort_reconcile_script_jobs()
        return render(request, self.template_name, self._context(request, edit_job_id=request.GET.get("edit_job")))

    def post(self, request):
        _best_effort_reconcile_script_jobs()
        if "stop_run" in request.POST:
            script_run = get_object_or_404(ScriptJobRun.objects.select_related("job"), pk=request.POST.get("stop_run"))
            if request_script_run_stop(script_run):
                messages.warning(request, f"Stop requested for script job '{script_run.job.name}'.")
            else:
                messages.info(request, f"Script job '{script_run.job.name}' is no longer running.")
            return redirect("monitor:script-jobs")

        if "rerun_run" in request.POST:
            script_run = get_object_or_404(ScriptJobRun.objects.select_related("job"), pk=request.POST.get("rerun_run"))
            if not script_run.job.enabled:
                messages.warning(request, f"Script job '{script_run.job.name}' is disabled. Activate it before running it again.")
                return redirect("monitor:script-jobs")
            running_run = ScriptJobRun.objects.filter(job=script_run.job, status="running").order_by("-started_at").first()
            if running_run:
                messages.warning(request, f"Script job '{script_run.job.name}' is already running.")
                return redirect("monitor:script-jobs")
            try:
                start_background_script_job(script_run.job, launched_by="manual")
            except OSError as exc:
                messages.error(request, f"Script job '{script_run.job.name}' could not start: {exc}")
                return redirect("monitor:script-jobs")
            messages.success(request, f"Script job '{script_run.job.name}' started again.")
            return redirect("monitor:script-jobs")

        if "run_now" in request.POST:
            job = get_object_or_404(ScriptJob, pk=request.POST.get("run_now"))
            if not job.enabled:
                messages.warning(request, f"Script job '{job.name}' is disabled. Activate it before running it.")
                return redirect("monitor:script-jobs")
            running_run = ScriptJobRun.objects.filter(job=job, status="running").order_by("-started_at").first()
            if running_run:
                messages.warning(request, f"Script job '{job.name}' is already running.")
                return redirect("monitor:script-jobs")
            try:
                start_background_script_job(job, launched_by="manual")
            except OSError as exc:
                messages.error(request, f"Script job '{job.name}' could not start: {exc}")
                return redirect("monitor:script-jobs")
            messages.success(request, f"Script job '{job.name}' started in background.")
            return redirect("monitor:script-jobs")

        if "toggle_job" in request.POST:
            job = get_object_or_404(ScriptJob, pk=request.POST.get("toggle_job"))
            job.enabled = not job.enabled
            job.save()
            state = "activated" if job.enabled else "disabled"
            messages.success(request, f"Script job '{job.name}' {state}.")
            return redirect("monitor:script-jobs")

        if "save_job" in request.POST:
            job = get_object_or_404(ScriptJob, pk=request.POST.get("save_job"))
            form = ScriptJobForm(request.POST, instance=job, prefix=f"job-{job.id}")
            if form.is_valid():
                instance = form.save(commit=False)
                instance.save()
                messages.success(request, f"Script job '{instance.name}' updated.")
                return redirect("monitor:script-jobs")
            return render(request, self.template_name, self._context(request, job_form_overrides={job.id: form}, show_create=False, edit_job_id=job.id))

        if "delete_job" in request.POST:
            job = get_object_or_404(ScriptJob, pk=request.POST.get("delete_job"))
            job_name = job.name
            job.delete()
            messages.success(request, f"Script job '{job_name}' deleted.")
            return redirect("monitor:script-jobs")

        if "create_job" in request.POST:
            create_form = ScriptJobForm(request.POST, prefix="new")
            if create_form.is_valid():
                instance = create_form.save(commit=False)
                instance.save()
                messages.success(request, f"Script job '{instance.name}' created.")
                return redirect("monitor:script-jobs")
            return render(request, self.template_name, self._context(request, create_form=create_form, show_create=True))

        return render(request, self.template_name, self._context(request))

    def _context(self, request, job_form_overrides=None, create_form=None, show_create=False, edit_job_id=None):
        job_form_overrides = job_form_overrides or {}
        query = (request.GET.get("q") or "").strip()
        state = request.GET.get("state") or "all"
        schedule = request.GET.get("schedule") or "all"
        view_mode = request.GET.get("view") if request.GET.get("view") in {"cards", "compact"} else "cards"
        running_runs = list(ScriptJobRun.objects.select_related("job").filter(status="running").order_by("-started_at")[:20])
        jobs_qs = ScriptJob.objects.all()
        if query:
            jobs_qs = jobs_qs.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(working_directory__icontains=query)
                | Q(script_body__icontains=query)
            )
        if state == "enabled":
            jobs_qs = jobs_qs.filter(enabled=True)
        elif state == "disabled":
            jobs_qs = jobs_qs.filter(enabled=False)
        if schedule in {"manual", "interval", "one_off"}:
            jobs_qs = jobs_qs.filter(schedule_mode=schedule)
        total_jobs_count = ScriptJob.objects.count()
        filtered_jobs_count = jobs_qs.count()
        paginator = Paginator(jobs_qs, 12)
        page_obj = paginator.get_page(request.GET.get("page"))
        jobs = list(page_obj.object_list)
        runs_by_job = {
            job.id: list(ScriptJobRun.objects.filter(job=job).order_by("-started_at")[:3])
            for job in jobs
        }
        job_forms = [
            {
                "job": job,
                "form": job_form_overrides.get(job.id) or ScriptJobForm(instance=job, prefix=f"job-{job.id}"),
                "recent_runs": runs_by_job.get(job.id, []),
                "last_run": (runs_by_job.get(job.id, []) or [None])[0],
            }
            for job in jobs
        ]
        compact_params = request.GET.copy()
        compact_params["view"] = "compact"
        compact_params.pop("page", None)
        card_params = request.GET.copy()
        card_params["view"] = "cards"
        card_params.pop("page", None)
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        return {
            "running_runs": running_runs,
            "running_runs_count": len(running_runs),
            "job_forms": job_forms,
            "jobs": jobs,
            "jobs_count": total_jobs_count,
            "filtered_jobs_count": filtered_jobs_count,
            "page_obj": page_obj,
            "query": query,
            "state_filter": state,
            "schedule_filter": schedule,
            "view_mode": view_mode,
            "compact_view_url": f"?{compact_params.urlencode()}",
            "card_view_url": f"?{card_params.urlencode()}",
            "pagination_query": pagination_params.urlencode(),
            "create_form": create_form or ScriptJobForm(prefix="new"),
            "show_create": show_create,
            "edit_job_id": edit_job_id,
            "settings_obj": MonitoringSettings.load(),
        }


class ScriptJobRunsView(LoginRequiredMixin, View):
    template_name = "monitor/script_job_runs.html"

    def get(self, request):
        _best_effort_reconcile_script_jobs()
        query = (request.GET.get("q") or "").strip()
        status = request.GET.get("status") or "all"
        launched_by = request.GET.get("launched_by") or "all"
        job_id = request.GET.get("job") or ""
        runs_qs = ScriptJobRun.objects.select_related("job").order_by("-started_at")
        if query:
            runs_qs = runs_qs.filter(Q(job__name__icontains=query) | Q(summary__icontains=query) | Q(command_line__icontains=query))
        if status in {choice[0] for choice in ScriptJobRun.STATUS_CHOICES}:
            runs_qs = runs_qs.filter(status=status)
        if launched_by in {choice[0] for choice in ScriptJobRun.LAUNCH_CHOICES}:
            runs_qs = runs_qs.filter(launched_by=launched_by)
        if job_id.isdigit():
            runs_qs = runs_qs.filter(job_id=job_id)
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        paginator = Paginator(runs_qs, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "page_obj": page_obj,
                "query": query,
                "status_filter": status,
                "launched_by_filter": launched_by,
                "job_filter": job_id,
                "status_choices": ScriptJobRun.STATUS_CHOICES,
                "launch_choices": ScriptJobRun.LAUNCH_CHOICES,
                "job_choices": ScriptJob.objects.order_by("name", "id"),
                "pagination_query": pagination_params.urlencode(),
                "settings_obj": MonitoringSettings.load(),
            },
        )


class ScriptJobRunStatusView(LoginRequiredMixin, View):
    def get(self, request, run_id):
        script_run = get_object_or_404(ScriptJobRun.objects.select_related("job"), pk=run_id)
        runtime_state = get_script_runtime_state(run_id) if script_run.status == "running" else None
        return JsonResponse(
            {
                "id": script_run.id,
                "job_name": script_run.job.name,
                "status": (runtime_state or {}).get("status") or script_run.status,
                "status_label": (runtime_state or {}).get("status_label") or script_run.get_status_display(),
                "summary": (runtime_state or {}).get("summary") or script_run.summary,
                "exit_code": (runtime_state or {}).get("exit_code", script_run.exit_code),
                "log_output": (runtime_state or {}).get("log_output") or script_run.log_output or "",
                "process_pid": (runtime_state or {}).get("process_pid") or script_run.process_pid,
                "runner_label": (runtime_state or {}).get("runner_label") or script_run.runner_label,
                "launched_by": script_run.get_launched_by_display(),
                "heartbeat_at": (runtime_state or {}).get("heartbeat_at") or (script_run.heartbeat_at.isoformat() if script_run.heartbeat_at else None),
                "last_output_at": (runtime_state or {}).get("last_output_at") or (script_run.last_output_at.isoformat() if script_run.last_output_at else None),
                "finished_at": (runtime_state or {}).get("finished_at") or (script_run.finished_at.isoformat() if script_run.finished_at else None),
                "command_line": (runtime_state or {}).get("command_line") or script_run.command_line or "",
            }
        )


class ScriptJobRunDetailView(LoginRequiredMixin, View):
    template_name = "monitor/script_job_run_detail.html"

    def get(self, request, run_id):
        _best_effort_reconcile_script_jobs()
        script_run = get_object_or_404(ScriptJobRun.objects.select_related("job"), pk=run_id)
        return render(
            request,
            self.template_name,
            {
                "script_run": script_run,
                "settings_obj": MonitoringSettings.load(),
            },
        )

    def post(self, request, run_id):
        _best_effort_reconcile_script_jobs()
        script_run = get_object_or_404(ScriptJobRun.objects.select_related("job"), pk=run_id)
        if "stop_run" in request.POST:
            if request_script_run_stop(script_run):
                messages.warning(request, f"Stop requested for script job '{script_run.job.name}'.")
            else:
                messages.info(request, f"Script job '{script_run.job.name}' is no longer running.")
            return redirect("monitor:script-job-run-detail", run_id=script_run.id)
        if "rerun_run" in request.POST:
            if not script_run.job.enabled:
                messages.warning(request, f"Script job '{script_run.job.name}' is disabled. Activate it before running it again.")
                return redirect("monitor:script-job-run-detail", run_id=script_run.id)
            running_run = ScriptJobRun.objects.filter(job=script_run.job, status="running").order_by("-started_at").first()
            if running_run:
                messages.warning(request, f"Script job '{script_run.job.name}' is already running.")
                return redirect("monitor:script-job-run-detail", run_id=script_run.id)
            try:
                started_run = start_background_script_job(script_run.job, launched_by="manual")
            except OSError as exc:
                messages.error(request, f"Script job '{script_run.job.name}' could not start: {exc}")
                return redirect("monitor:script-job-run-detail", run_id=script_run.id)
            messages.success(request, f"Script job '{script_run.job.name}' started again.")
            return redirect("monitor:script-job-run-detail", run_id=started_run.id)
        return redirect("monitor:script-job-run-detail", run_id=script_run.id)


@method_decorator(csrf_exempt, name="dispatch")
class BackupsView(LoginRequiredMixin, View):
    template_name = "monitor/backups.html"

    def get(self, request):
        _best_effort_reconcile_backups()
        return render(request, self.template_name, self._context(request, edit_job_id=request.GET.get("edit_job")))

    def post(self, request):
        _best_effort_reconcile_backups()
        if "stop_run" in request.POST:
            backup_run = get_object_or_404(BackupRun.objects.select_related("job"), pk=request.POST.get("stop_run"))
            if request_backup_run_stop(backup_run):
                messages.warning(request, f"Stop requested for backup '{backup_run.job.name}'.")
            else:
                messages.info(request, f"Backup '{backup_run.job.name}' is no longer running.")
            return redirect("monitor:backups")

        if "rerun_run" in request.POST:
            backup_run = get_object_or_404(BackupRun.objects.select_related("job"), pk=request.POST.get("rerun_run"))
            if not backup_run.job.enabled:
                messages.warning(request, f"Backup job '{backup_run.job.name}' is disabled. Activate it before running it again.")
                return redirect("monitor:backups")
            running_run = BackupRun.objects.filter(job=backup_run.job, status="running").order_by("-started_at").first()
            if running_run:
                messages.warning(request, f"Backup '{backup_run.job.name}' is already running.")
                return redirect("monitor:backups")
            try:
                start_background_backup(backup_run.job, launched_by="manual")
            except OSError as exc:
                messages.error(request, f"Backup '{backup_run.job.name}' could not start: {exc}")
                return redirect("monitor:backups")
            messages.success(request, f"Backup '{backup_run.job.name}' started again.")
            return redirect("monitor:backups")

        if "run_now" in request.POST:
            job = get_object_or_404(BackupJob, pk=request.POST.get("run_now"))
            if not job.enabled:
                messages.warning(request, f"Backup job '{job.name}' is disabled. Activate it before running it.")
                return redirect("monitor:backups")
            running_run = BackupRun.objects.filter(job=job, status="running").order_by("-started_at").first()
            if running_run:
                messages.warning(request, f"Backup '{job.name}' is already running.")
                return redirect("monitor:backups")

            try:
                start_background_backup(job, launched_by="manual")
            except OSError as exc:
                messages.error(request, f"Backup '{job.name}' could not start: {exc}")
                return redirect("monitor:backups")
            messages.success(request, f"Backup '{job.name}' started in background.")
            return redirect("monitor:backups")

        if "toggle_job" in request.POST:
            job = get_object_or_404(BackupJob, pk=request.POST.get("toggle_job"))
            job.enabled = not job.enabled
            job.save()
            state = "activated" if job.enabled else "disabled"
            messages.success(request, f"Backup job '{job.name}' {state}.")
            return redirect("monitor:backups")

        if "save_job" in request.POST:
            job = get_object_or_404(BackupJob, pk=request.POST.get("save_job"))
            form = BackupJobForm(request.POST, instance=job, prefix=f"job-{job.id}")
            if form.is_valid():
                instance = form.save(commit=False)
                instance.save()
                messages.success(request, f"Backup job '{instance.name}' updated.")
                return redirect("monitor:backups")
            return render(request, self.template_name, self._context(request, job_form_overrides={job.id: form}, show_create=False, edit_job_id=job.id))

        if "delete_job" in request.POST:
            job = get_object_or_404(BackupJob, pk=request.POST.get("delete_job"))
            job_name = job.name
            job.delete()
            messages.success(request, f"Backup job '{job_name}' deleted.")
            return redirect("monitor:backups")

        if "create_job" in request.POST:
            create_form = BackupJobForm(request.POST, prefix="new")
            if create_form.is_valid():
                instance = create_form.save(commit=False)
                instance.save()
                messages.success(request, f"Backup job '{instance.name}' created.")
                return redirect("monitor:backups")
            return render(request, self.template_name, self._context(request, create_form=create_form, show_create=True))

        return render(request, self.template_name, self._context(request))

    def _context(self, request, job_form_overrides=None, create_form=None, show_create=False, edit_job_id=None):
        job_form_overrides = job_form_overrides or {}
        query = (request.GET.get("q") or "").strip()
        state = request.GET.get("state") or "all"
        backup_type = request.GET.get("type") or "all"
        direction = request.GET.get("direction") or "all"
        view_mode = request.GET.get("view") if request.GET.get("view") in {"cards", "compact"} else "cards"
        latest_snapshot = SystemSnapshot.objects.order_by("-captured_at").first()
        running_runs = list(BackupRun.objects.select_related("job").filter(status="running").order_by("-started_at")[:20])
        for run in running_runs:
            runtime_state = get_runtime_state(run.id)
            if runtime_state:
                run.log_output = _normalize_stream_output(runtime_state.get("log_output") or run.log_output or "")
        jobs_qs = BackupJob.objects.all()
        if query:
            jobs_qs = jobs_qs.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(source_path__icontains=query)
                | Q(local_dest_path__icontains=query)
                | Q(remote_host__icontains=query)
                | Q(remote_dir__icontains=query)
                | Q(http_remote_url__icontains=query)
                | Q(http_remote_path__icontains=query)
            )
        if state == "enabled":
            jobs_qs = jobs_qs.filter(enabled=True)
        elif state == "disabled":
            jobs_qs = jobs_qs.filter(enabled=False)
        if backup_type in {"local", "remote", "http"}:
            jobs_qs = jobs_qs.filter(backup_type=backup_type)
        if direction == "push":
            jobs_qs = jobs_qs.filter(Q(backup_type="remote", remote_direction="push") | Q(backup_type="http", http_direction="push"))
        elif direction == "pull":
            jobs_qs = jobs_qs.filter(Q(backup_type="remote", remote_direction="pull") | Q(backup_type="http", http_direction="pull"))
        total_jobs_count = BackupJob.objects.count()
        filtered_jobs_count = jobs_qs.count()
        paginator = Paginator(jobs_qs, 12)
        page_obj = paginator.get_page(request.GET.get("page"))
        jobs = list(page_obj.object_list)
        runs_by_job = {
            job.id: list(BackupRun.objects.filter(job=job).order_by("-started_at")[:3])
            for job in jobs
        }
        job_forms = [
            {
                "job": job,
                "form": job_form_overrides.get(job.id) or BackupJobForm(instance=job, prefix=f"job-{job.id}"),
                "recent_runs": runs_by_job.get(job.id, []),
                "last_run": (runs_by_job.get(job.id, []) or [None])[0],
                "source_label": job.source_label,
                "destination_label": job.destination_label,
            }
            for job in jobs
        ]
        create_form = create_form or BackupJobForm(prefix="new")
        compact_params = request.GET.copy()
        compact_params["view"] = "compact"
        compact_params.pop("page", None)
        card_params = request.GET.copy()
        card_params["view"] = "cards"
        card_params.pop("page", None)
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        return {
            "latest_snapshot": latest_snapshot,
            "running_runs": running_runs,
            "running_runs_count": len(running_runs),
            "job_forms": job_forms,
            "jobs": jobs,
            "jobs_count": total_jobs_count,
            "filtered_jobs_count": filtered_jobs_count,
            "page_obj": page_obj,
            "query": query,
            "state_filter": state,
            "type_filter": backup_type,
            "direction_filter": direction,
            "view_mode": view_mode,
            "compact_view_url": f"?{compact_params.urlencode()}",
            "card_view_url": f"?{card_params.urlencode()}",
            "pagination_query": pagination_params.urlencode(),
            "browser_roots": list_browser_roots(),
            "backup_tree_url": reverse("monitor:backup-tree"),
            "create_form": create_form,
            "show_create": show_create,
            "edit_job_id": edit_job_id,
            "settings_obj": MonitoringSettings.load(),
        }

class BackupRunsView(LoginRequiredMixin, View):
    template_name = "monitor/backup_runs.html"

    def get(self, request):
        _best_effort_reconcile_backups()
        query = (request.GET.get("q") or "").strip()
        status = request.GET.get("status") or "all"
        backup_type = request.GET.get("type") or "all"
        direction = request.GET.get("direction") or "all"
        launched_by = request.GET.get("launched_by") or "all"
        job_id = request.GET.get("job") or ""
        runs_qs = BackupRun.objects.select_related("job").order_by("-started_at")
        if query:
            runs_qs = runs_qs.filter(
                Q(job__name__icontains=query)
                | Q(summary__icontains=query)
                | Q(command_line__icontains=query)
                | Q(job__source_path__icontains=query)
                | Q(job__local_dest_path__icontains=query)
                | Q(job__remote_host__icontains=query)
                | Q(job__remote_dir__icontains=query)
                | Q(job__http_remote_url__icontains=query)
                | Q(job__http_remote_path__icontains=query)
            )
        if status in {choice[0] for choice in BackupRun.STATUS_CHOICES}:
            runs_qs = runs_qs.filter(status=status)
        if backup_type in {"local", "remote", "http"}:
            runs_qs = runs_qs.filter(job__backup_type=backup_type)
        if direction == "push":
            runs_qs = runs_qs.filter(Q(job__backup_type="remote", job__remote_direction="push") | Q(job__backup_type="http", job__http_direction="push"))
        elif direction == "pull":
            runs_qs = runs_qs.filter(Q(job__backup_type="remote", job__remote_direction="pull") | Q(job__backup_type="http", job__http_direction="pull"))
        if launched_by in {choice[0] for choice in BackupRun.LAUNCH_CHOICES}:
            runs_qs = runs_qs.filter(launched_by=launched_by)
        if job_id.isdigit():
            runs_qs = runs_qs.filter(job_id=job_id)
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        paginator = Paginator(runs_qs, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "page_obj": page_obj,
                "query": query,
                "status_filter": status,
                "type_filter": backup_type,
                "direction_filter": direction,
                "launched_by_filter": launched_by,
                "job_filter": job_id,
                "status_choices": BackupRun.STATUS_CHOICES,
                "launch_choices": BackupRun.LAUNCH_CHOICES,
                "job_choices": BackupJob.objects.order_by("name", "id"),
                "pagination_query": pagination_params.urlencode(),
                "settings_obj": MonitoringSettings.load(),
            },
        )


class BackupTreeView(LoginRequiredMixin, View):
    def get(self, request):
        host_path = request.GET.get("path", "/")
        try:
            items = list_directory_children(host_path)
        except ValueError as exc:
            return JsonResponse({"items": [], "error": str(exc)}, status=400)
        return JsonResponse({"items": items})


class VolumeTreeView(LoginRequiredMixin, View):
    def get(self, request):
        host_path = request.GET.get("path", "/")
        try:
            items = list_path_directory_children(host_path)
        except ValueError as exc:
            return JsonResponse({"items": [], "error": str(exc)}, status=400)
        return JsonResponse({"items": items})


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


class BackupRunStatusView(LoginRequiredMixin, View):
    def get(self, request, run_id):
        backup_run = get_object_or_404(BackupRun.objects.select_related("job"), pk=run_id)
        runtime_state = get_runtime_state(run_id) if backup_run.status == "running" else None
        runtime_log_output = _normalize_stream_output((runtime_state or {}).get("log_output") or "")
        return JsonResponse(
            {
                "id": backup_run.id,
                "job_name": backup_run.job.name,
                "status": (runtime_state or {}).get("status") or backup_run.status,
                "status_label": (runtime_state or {}).get("status_label") or backup_run.get_status_display(),
                "summary": (runtime_state or {}).get("summary") or backup_run.summary,
                "exit_code": (runtime_state or {}).get("exit_code", backup_run.exit_code),
                "log_output": runtime_log_output or backup_run.log_output or "",
                "process_pid": (runtime_state or {}).get("process_pid") or backup_run.process_pid,
                "runner_label": (runtime_state or {}).get("runner_label") or backup_run.runner_label,
                "launched_by": backup_run.get_launched_by_display(),
                "heartbeat_at": (runtime_state or {}).get("heartbeat_at") or (backup_run.heartbeat_at.isoformat() if backup_run.heartbeat_at else None),
                "last_output_at": (runtime_state or {}).get("last_output_at") or (backup_run.last_output_at.isoformat() if backup_run.last_output_at else None),
                "finished_at": (runtime_state or {}).get("finished_at") or (backup_run.finished_at.isoformat() if backup_run.finished_at else None),
                "command_line": (runtime_state or {}).get("command_line") or backup_run.command_line or "",
            }
        )


class BackupRunDetailView(LoginRequiredMixin, View):
    template_name = "monitor/backup_run_detail.html"

    def get(self, request, run_id):
        _best_effort_reconcile_backups()
        backup_run = get_object_or_404(BackupRun.objects.select_related("job"), pk=run_id)
        if backup_run.status == "running":
            runtime_state = get_runtime_state(run_id)
            if runtime_state:
                backup_run.log_output = _normalize_stream_output(runtime_state.get("log_output") or backup_run.log_output or "")
        return render(
            request,
            self.template_name,
            {
                "backup_run": backup_run,
                "settings_obj": MonitoringSettings.load(),
            },
        )

    def post(self, request, run_id):
        _best_effort_reconcile_backups()
        backup_run = get_object_or_404(BackupRun.objects.select_related("job"), pk=run_id)
        if "stop_run" in request.POST:
            if request_backup_run_stop(backup_run):
                messages.warning(request, f"Stop requested for backup '{backup_run.job.name}'.")
            else:
                messages.info(request, f"Backup '{backup_run.job.name}' is no longer running.")
            return redirect("monitor:backup-run-detail", run_id=backup_run.id)
        if "rerun_run" in request.POST:
            running_run = BackupRun.objects.filter(job=backup_run.job, status="running").order_by("-started_at").first()
            if running_run:
                messages.warning(request, f"Backup '{backup_run.job.name}' is already running.")
                return redirect("monitor:backup-run-detail", run_id=backup_run.id)
            try:
                new_run = start_background_backup(backup_run.job, launched_by="manual")
            except OSError as exc:
                messages.error(request, f"Backup '{backup_run.job.name}' could not start: {exc}")
                return redirect("monitor:backup-run-detail", run_id=backup_run.id)
            messages.success(request, f"Backup '{backup_run.job.name}' started again.")
            return redirect("monitor:backup-run-detail", run_id=new_run.id)
        return redirect("monitor:backup-run-detail", run_id=backup_run.id)
