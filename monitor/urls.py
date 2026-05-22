from django.urls import path

from .views import AlertDetailView, AlertsView, BackupRunDetailView, BackupRunsView, BackupRunStatusView, BackupTreeView, BackupsView, HistoryView, RedirectHomeView, ReportDetailView, ReportsView, SettingsView, SystemMonitorView

app_name = "monitor"

urlpatterns = [
    path("", RedirectHomeView.as_view(), name="home"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("monitor/", SystemMonitorView.as_view(), name="system-monitor"),
    path("history/", HistoryView.as_view(), name="history"),
    path("alerts/", AlertsView.as_view(), name="alerts"),
    path("alerts/<int:event_id>/", AlertDetailView.as_view(), name="alert-detail"),
    path("reports/", ReportsView.as_view(), name="reports"),
    path("reports/<int:report_id>/", ReportDetailView.as_view(), name="report-detail"),
    path("backups/", BackupsView.as_view(), name="backups"),
    path("backups/runs/", BackupRunsView.as_view(), name="backup-runs"),
    path("backups/tree/", BackupTreeView.as_view(), name="backup-tree"),
    path("backups/runs/<int:run_id>/status/", BackupRunStatusView.as_view(), name="backup-run-status"),
    path("backups/runs/<int:run_id>/", BackupRunDetailView.as_view(), name="backup-run-detail"),
]
