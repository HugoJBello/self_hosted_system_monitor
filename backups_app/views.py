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

from .http_services import http_backup_compare_view, http_backup_delete_view, http_backup_file_view, http_backup_list_view, http_backup_manifest_view, http_backup_prune_view, http_backup_stat_view

def backup_job_form_context(form, *, job=None, create=False):
    return {
        "form": form,
        "job": job,
        "page_title": "Create backup job" if create else f"Edit {job.name}",
        "page_eyebrow": "New backup job" if create else "Edit backup job",
        "submit_label": "Create backup job" if create else "Save config",
        "create_job": "1" if create else None,
        "save_name": None if create else "save_job",
        "save_value": None if create else job.id,
        "cancel_url": reverse("monitor:backups"),
        "browser_roots": list_browser_roots(),
        "backup_tree_url": reverse("monitor:backup-tree"),
        "settings_obj": MonitoringSettings.load(),
    }

def _best_effort_reconcile_backups():
    try:
        mark_stale_running_backups()
    except OperationalError:
        pass

@method_decorator(csrf_exempt, name="dispatch")
class BackupsView(LoginRequiredMixin, View):
    template_name = "monitor/backups.html"

    def get(self, request):
        _best_effort_reconcile_backups()
        return render(request, self.template_name, self._context(request))

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
            return render(request, "monitor/backup_job_form_page.html", backup_job_form_context(form, job=job))

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
            return render(request, "monitor/backup_job_form_page.html", backup_job_form_context(create_form, create=True))

        return render(request, self.template_name, self._context(request))

    def _context(self, request):
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
                "recent_runs": runs_by_job.get(job.id, []),
                "last_run": (runs_by_job.get(job.id, []) or [None])[0],
                "source_label": job.source_label,
                "destination_label": job.destination_label,
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
            "settings_obj": MonitoringSettings.load(),
        }


class BackupJobCreateView(LoginRequiredMixin, View):
    template_name = "monitor/backup_job_form_page.html"

    def get(self, request):
        return render(request, self.template_name, backup_job_form_context(BackupJobForm(prefix="new"), create=True))

    def post(self, request):
        form = BackupJobForm(request.POST, prefix="new")
        if form.is_valid():
            instance = form.save(commit=False)
            instance.save()
            messages.success(request, f"Backup job '{instance.name}' created.")
            return redirect("monitor:backups")
        return render(request, self.template_name, backup_job_form_context(form, create=True))


class BackupJobEditView(LoginRequiredMixin, View):
    template_name = "monitor/backup_job_form_page.html"

    def get(self, request, job_id):
        job = get_object_or_404(BackupJob, pk=job_id)
        return render(request, self.template_name, backup_job_form_context(BackupJobForm(instance=job, prefix=f"job-{job.id}"), job=job))

    def post(self, request, job_id):
        job = get_object_or_404(BackupJob, pk=job_id)
        form = BackupJobForm(request.POST, instance=job, prefix=f"job-{job.id}")
        if form.is_valid():
            instance = form.save(commit=False)
            instance.save()
            messages.success(request, f"Backup job '{instance.name}' updated.")
            return redirect("monitor:backups")
        return render(request, self.template_name, backup_job_form_context(form, job=job))

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

    def post(self, request):
        try:
            item = create_path_directory(request.POST.get("parent_path") or "/", request.POST.get("folder_name") or "")
        except ValueError as exc:
            return JsonResponse({"item": None, "error": str(exc)}, status=400)
        return JsonResponse({"item": item})

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

