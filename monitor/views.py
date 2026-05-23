from datetime import timedelta
from collections import defaultdict

from django.contrib import messages
from django.db import OperationalError
from django.http import JsonResponse
from django.forms import modelformset_factory
from django.db.models import Avg, Max
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .alerting import ensure_default_alert_rules, top_processes_for_alert_window
from .backups import get_runtime_state, list_browser_roots, list_directory_children, mark_stale_running_backups, request_backup_run_stop, start_background_backup
from .forms import AlertRuleForm, BackupJobForm, MonitoringSettingsForm, ReportRuleForm
from .models import AlertEvent, AlertRule, BackupJob, BackupRun, MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, SystemSnapshot
from .notification_client import build_test_payload, send_json_notification
from .reporting import build_time_series_chart_data


def _best_effort_reconcile_backups():
    try:
        mark_stale_running_backups()
    except OperationalError:
        pass


class RedirectHomeView(View):
    def get(self, request):
        return redirect("monitor:system-monitor")


@method_decorator(csrf_exempt, name="dispatch")
class SettingsView(View):
    template_name = "monitor/settings.html"

    def get(self, request):
        settings_obj = MonitoringSettings.load()
        form = MonitoringSettingsForm(instance=settings_obj)
        return render(request, self.template_name, {"form": form, "settings_obj": settings_obj})

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
        return render(request, self.template_name, {"form": form, "settings_obj": settings_obj})


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

class SystemMonitorView(View):
    template_name = "monitor/system_monitor.html"

    def get(self, request):
        latest_snapshot = (
            SystemSnapshot.objects.prefetch_related("processes")
            .order_by("-captured_at")
            .first()
        )
        context = {
            "latest_snapshot": latest_snapshot,
            "settings_obj": MonitoringSettings.load(),
        }
        return render(request, self.template_name, context)


class HistoryView(View):
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
                "statuses": set(),
                "commands": [],
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
            entry["last_seen_at"] = max(filter(None, [entry["last_seen_at"], row["snapshot__captured_at"]]))
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
                    "statuses": sorted(entry["statuses"]),
                    "commands": entry["commands"],
                }
                for entry in grouped_processes.values()
            ],
            key=lambda item: (item["avg_cpu"], item["peak_memory"], item["max_rss_mb"]),
            reverse=True,
        )[:8]
        expensive_processes_point = list(latest_snapshot.processes.all()[:8]) if latest_snapshot else []

        return render(
            request,
            self.template_name,
            {
                "hours": hours,
                "chart_data": chart_data,
                "snapshot_count": len(snapshots),
                "aggregates": aggregates,
                "latest_snapshot": latest_snapshot,
                "expensive_processes_period": expensive_processes_period,
                "expensive_processes_point": expensive_processes_point,
                "settings_obj": settings_obj,
            },
        )


@method_decorator(csrf_exempt, name="dispatch")
class AlertsView(View):
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
class ReportsView(View):
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


class AlertDetailView(View):
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
            "metric_values": [getattr(item, event.metric, 0) for item in context_snapshots],
            "threshold": [event.threshold for _ in context_snapshots],
        }
        alert_window_processes = top_processes_for_alert_window(event.rule, trigger_snapshot, limit=8)
        return render(
            request,
            self.template_name,
            {
                "event": event,
                "trigger_snapshot": trigger_snapshot,
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


class ReportDetailView(View):
    template_name = "monitor/report_detail.html"

    def get(self, request, report_id):
        report = get_object_or_404(ReportRun.objects.select_related("rule"), pk=report_id)
        report_data = report.report_data or {}
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
class BackupsView(View):
    template_name = "monitor/backups.html"

    def get(self, request):
        _best_effort_reconcile_backups()
        return render(request, self.template_name, self._context())

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

        if "save_job" in request.POST:
            job = get_object_or_404(BackupJob, pk=request.POST.get("save_job"))
            form = BackupJobForm(request.POST, instance=job, prefix=f"job-{job.id}")
            if form.is_valid():
                instance = form.save(commit=False)
                if instance.enabled and instance.next_run_at is None:
                    instance.next_run_at = timezone.now() + timedelta(minutes=max(instance.schedule_minutes, 5))
                instance.save()
                messages.success(request, f"Backup job '{instance.name}' updated.")
                return redirect("monitor:backups")
            return render(request, self.template_name, self._context(job_form_overrides={job.id: form}, show_create=False))

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
                if instance.enabled and instance.next_run_at is None:
                    instance.next_run_at = timezone.now() + timedelta(minutes=max(instance.schedule_minutes, 5))
                instance.save()
                messages.success(request, f"Backup job '{instance.name}' created.")
                return redirect("monitor:backups")
            return render(request, self.template_name, self._context(create_form=create_form, show_create=True))

        return render(request, self.template_name, self._context())

    def _context(self, job_form_overrides=None, create_form=None, show_create=False):
        job_form_overrides = job_form_overrides or {}
        latest_snapshot = SystemSnapshot.objects.order_by("-captured_at").first()
        running_runs = list(BackupRun.objects.select_related("job").filter(status="running").order_by("-started_at")[:20])
        recent_runs = list(BackupRun.objects.select_related("job").exclude(status="running").order_by("-started_at")[:8])
        jobs = list(BackupJob.objects.all())
        job_forms = [
            {
                "job": job,
                "form": job_form_overrides.get(job.id) or BackupJobForm(instance=job, prefix=f"job-{job.id}"),
            }
            for job in jobs
        ]
        create_form = create_form or BackupJobForm(prefix="new")
        return {
            "latest_snapshot": latest_snapshot,
            "running_runs": running_runs,
            "running_runs_count": len(running_runs),
            "recent_runs": recent_runs,
            "job_forms": job_forms,
            "jobs": jobs,
            "jobs_count": len(jobs),
            "recent_runs_count": len(recent_runs),
            "browser_roots": list_browser_roots(),
            "create_form": create_form,
            "show_create": show_create,
            "settings_obj": MonitoringSettings.load(),
        }


class BackupRunsView(View):
    template_name = "monitor/backup_runs.html"

    def get(self, request):
        _best_effort_reconcile_backups()
        query = (request.GET.get("q") or "").strip()
        runs_qs = BackupRun.objects.select_related("job").order_by("-started_at")
        if query:
            runs_qs = runs_qs.filter(job__name__icontains=query)
        paginator = Paginator(runs_qs, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "page_obj": page_obj,
                "query": query,
                "settings_obj": MonitoringSettings.load(),
            },
        )


class BackupTreeView(View):
    def get(self, request):
        host_path = request.GET.get("path", "/")
        return JsonResponse({"items": list_directory_children(host_path)})


class BackupRunStatusView(View):
    def get(self, request, run_id):
        backup_run = get_object_or_404(BackupRun.objects.select_related("job"), pk=run_id)
        runtime_state = get_runtime_state(run_id) if backup_run.status == "running" else None
        return JsonResponse(
            {
                "id": backup_run.id,
                "job_name": backup_run.job.name,
                "status": (runtime_state or {}).get("status") or backup_run.status,
                "status_label": (runtime_state or {}).get("status_label") or backup_run.get_status_display(),
                "summary": (runtime_state or {}).get("summary") or backup_run.summary,
                "exit_code": (runtime_state or {}).get("exit_code", backup_run.exit_code),
                "log_output": (runtime_state or {}).get("log_output") or backup_run.log_output or "",
                "process_pid": (runtime_state or {}).get("process_pid") or backup_run.process_pid,
                "runner_label": (runtime_state or {}).get("runner_label") or backup_run.runner_label,
                "launched_by": backup_run.get_launched_by_display(),
                "heartbeat_at": (runtime_state or {}).get("heartbeat_at") or (backup_run.heartbeat_at.isoformat() if backup_run.heartbeat_at else None),
                "last_output_at": (runtime_state or {}).get("last_output_at") or (backup_run.last_output_at.isoformat() if backup_run.last_output_at else None),
                "finished_at": (runtime_state or {}).get("finished_at") or (backup_run.finished_at.isoformat() if backup_run.finished_at else None),
                "command_line": (runtime_state or {}).get("command_line") or backup_run.command_line or "",
            }
        )


class BackupRunDetailView(View):
    template_name = "monitor/backup_run_detail.html"

    def get(self, request, run_id):
        _best_effort_reconcile_backups()
        backup_run = get_object_or_404(BackupRun.objects.select_related("job"), pk=run_id)
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
