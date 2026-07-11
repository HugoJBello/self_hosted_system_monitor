from django.urls import path

from .http_backups import http_backup_compare_view, http_backup_delete_view, http_backup_file_view, http_backup_list_view, http_backup_manifest_view, http_backup_prune_view, http_backup_stat_view
from .views import AlertDetailView, AlertsView, BackupRunDetailView, BackupRunsView, BackupRunStatusView, BackupTreeView, BackupsView, HistoryView, LoginView, LogoutView, PasswordView, ProcessActionView, RedirectHomeView, ReportDetailView, ReportsView, ScriptJobRunDetailView, ScriptJobRunsView, ScriptJobRunStatusView, ScriptJobsView, SettingsView, SystemMonitorView, UsersView, healthz_view

app_name = "monitor"

urlpatterns = [
    path("healthz/", healthz_view, name="healthz"),
    path("", RedirectHomeView.as_view(), name="home"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("password/", PasswordView.as_view(), name="password"),
    path("users/", UsersView.as_view(), name="users"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("process-action/", ProcessActionView.as_view(), name="process-action"),
    path("monitor/", SystemMonitorView.as_view(), name="system-monitor"),
    path("history/", HistoryView.as_view(), name="history"),
    path("alerts/", AlertsView.as_view(), name="alerts"),
    path("alerts/<int:event_id>/", AlertDetailView.as_view(), name="alert-detail"),
    path("reports/", ReportsView.as_view(), name="reports"),
    path("reports/<int:report_id>/", ReportDetailView.as_view(), name="report-detail"),
    path("jobs/", ScriptJobsView.as_view(), name="script-jobs"),
    path("jobs/runs/", ScriptJobRunsView.as_view(), name="script-job-runs"),
    path("jobs/runs/<int:run_id>/status/", ScriptJobRunStatusView.as_view(), name="script-job-run-status"),
    path("jobs/runs/<int:run_id>/", ScriptJobRunDetailView.as_view(), name="script-job-run-detail"),
    path("backups/", BackupsView.as_view(), name="backups"),
    path("backups/runs/", BackupRunsView.as_view(), name="backup-runs"),
    path("backups/tree/", BackupTreeView.as_view(), name="backup-tree"),
    path("backups/http/manifest/", http_backup_manifest_view, name="backup-http-manifest"),
    path("backups/http/list/", http_backup_list_view, name="backup-http-list"),
    path("backups/http/stat/", http_backup_stat_view, name="backup-http-stat"),
    path("backups/http/compare/", http_backup_compare_view, name="backup-http-compare"),
    path("backups/http/prune/", http_backup_prune_view, name="backup-http-prune"),
    path("backups/http/file/", http_backup_file_view, name="backup-http-file"),
    path("backups/http/delete/", http_backup_delete_view, name="backup-http-delete"),
    path("backups/runs/<int:run_id>/status/", BackupRunStatusView.as_view(), name="backup-run-status"),
    path("backups/runs/<int:run_id>/", BackupRunDetailView.as_view(), name="backup-run-detail"),
]
