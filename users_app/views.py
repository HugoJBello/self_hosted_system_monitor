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

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class LoginView(auth_views.LoginView):
    template_name = "monitor/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        url = super().get_success_url()
        return _with_app_subpath(url)


class LogoutView(auth_views.LogoutView):
    pass


def _with_app_subpath(url):
    app_subpath = getattr(settings, "APP_SUBPATH", "")
    if not app_subpath or not url.startswith("/") or url.startswith("//"):
        return url
    if url == app_subpath or url.startswith(f"{app_subpath}/"):
        return url
    return f"{app_subpath}{url}"


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
