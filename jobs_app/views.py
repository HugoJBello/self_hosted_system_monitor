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

def script_job_form_context(form, *, job=None, create=False):
    return {
        "form": form,
        "job": job,
        "page_title": "Create script job" if create else f"Edit {job.name}",
        "page_eyebrow": "New job" if create else "Edit job",
        "submit_label": "Create job" if create else "Save config",
        "create_job": "1" if create else None,
        "save_name": None if create else "save_job",
        "save_value": None if create else job.id,
        "cancel_url": reverse("monitor:script-jobs"),
        "settings_obj": MonitoringSettings.load(),
    }

def _best_effort_reconcile_script_jobs():
    try:
        mark_stale_running_script_jobs()
    except OperationalError:
        pass

@method_decorator(csrf_exempt, name="dispatch")
class ScriptJobsView(LoginRequiredMixin, View):
    template_name = "jobs_app/script_jobs.html"

    def get(self, request):
        _best_effort_reconcile_script_jobs()
        return render(request, self.template_name, self._context(request))

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
            return render(request, "jobs_app/script_job_form_page.html", script_job_form_context(form, job=job))

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
            return render(request, "jobs_app/script_job_form_page.html", script_job_form_context(create_form, create=True))

        return render(request, self.template_name, self._context(request))

    def _context(self, request):
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
            "settings_obj": MonitoringSettings.load(),
        }


class ScriptJobCreateView(LoginRequiredMixin, View):
    template_name = "jobs_app/script_job_form_page.html"

    def get(self, request):
        return render(request, self.template_name, script_job_form_context(ScriptJobForm(prefix="new"), create=True))

    def post(self, request):
        form = ScriptJobForm(request.POST, prefix="new")
        if form.is_valid():
            instance = form.save(commit=False)
            instance.save()
            messages.success(request, f"Script job '{instance.name}' created.")
            return redirect("monitor:script-jobs")
        return render(request, self.template_name, script_job_form_context(form, create=True))


class ScriptJobEditView(LoginRequiredMixin, View):
    template_name = "jobs_app/script_job_form_page.html"

    def get(self, request, job_id):
        job = get_object_or_404(ScriptJob, pk=job_id)
        return render(request, self.template_name, script_job_form_context(ScriptJobForm(instance=job, prefix=f"job-{job.id}"), job=job))

    def post(self, request, job_id):
        job = get_object_or_404(ScriptJob, pk=job_id)
        form = ScriptJobForm(request.POST, instance=job, prefix=f"job-{job.id}")
        if form.is_valid():
            instance = form.save(commit=False)
            instance.save()
            messages.success(request, f"Script job '{instance.name}' updated.")
            return redirect("monitor:script-jobs")
        return render(request, self.template_name, script_job_form_context(form, job=job))


class ScriptJobRunsView(LoginRequiredMixin, View):
    template_name = "jobs_app/script_job_runs.html"

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
    template_name = "jobs_app/script_job_run_detail.html"

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

