from django.urls import path

from .views import (
    BackupJobCreateView,
    BackupJobEditView,
    BackupRunDetailView,
    BackupRunsView,
    BackupRunStatusView,
    BackupTreeView,
    BackupsView,
    http_backup_compare_view,
    http_backup_delete_view,
    http_backup_file_view,
    http_backup_list_view,
    http_backup_manifest_view,
    http_backup_prune_view,
    http_backup_stat_view,
)


urlpatterns = [
    path("backups/new/", BackupJobCreateView.as_view(), name="backup-job-create"),
    path("backups/<int:job_id>/edit/", BackupJobEditView.as_view(), name="backup-job-edit"),
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
