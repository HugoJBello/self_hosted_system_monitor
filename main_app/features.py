from django.urls import reverse


FEATURES = (
    {"key": "monitor", "label": "System monitor", "description": "Live system health, processes, CPU and memory.", "icon": "bi-speedometer2", "url_name": "monitor:system-monitor"},
    {"key": "history", "label": "History", "description": "Historical metrics and process snapshots.", "icon": "bi-clock-history", "url_name": "monitor:history"},
    {"key": "alerts", "label": "Alerts", "description": "View alert events and their details.", "icon": "bi-bell", "url_name": "monitor:alerts"},
    {"key": "reports", "label": "Reports", "description": "Generated monitoring reports and charts.", "icon": "bi-graph-up-arrow", "url_name": "monitor:reports"},
    {"key": "docker", "label": "Docker", "description": "Container overview and logs. Mutating actions remain admin-only.", "icon": "bi-boxes", "url_name": "monitor:docker-overview"},
    {"key": "files", "label": "Files", "description": "File manager, searches and content shared with the user.", "icon": "bi-folder2-open", "url_name": "monitor:file-manager"},
    {"key": "volumes", "label": "Volumes", "description": "Storage volumes and volume operations.", "icon": "bi-device-hdd", "url_name": "monitor:volumes"},
    {"key": "jobs", "label": "Jobs", "description": "Script jobs, runs and execution details.", "icon": "bi-terminal", "url_name": "monitor:script-jobs"},
    {"key": "backups", "label": "Backups", "description": "Backup jobs, runs and file trees.", "icon": "bi-hdd-network", "url_name": "monitor:backups"},
)
FEATURE_KEYS = frozenset(item["key"] for item in FEATURES)

URL_FEATURES = {
    "system-monitor": "monitor", "process-action": "monitor",
    "history": "history",
    "alerts": "alerts", "alert-detail": "alerts",
    "reports": "reports", "report-detail": "reports",
    "docker-overview": "docker", "docker-action": "docker", "docker-logs": "docker",
    "file-manager": "files", "file-shares": "files", "file-share-create": "files", "file-share-detail": "files",
    "file-manager-list": "files", "file-manager-information": "files", "file-manager-embedded-thumbnail": "files",
    "file-manager-preview": "files", "file-manager-search": "files", "file-manager-operations": "files",
    "file-manager-operation-download": "files", "file-manager-operation-status": "files", "file-manager-operation-detail": "files",
    "volumes": "volumes", "volume-tree": "volumes", "volume-operations": "volumes", "volume-operation-status": "volumes", "volume-operation-detail": "volumes",
    "script-jobs": "jobs", "script-job-create": "jobs", "script-job-edit": "jobs", "script-job-runs": "jobs", "script-job-run-status": "jobs", "script-job-run-detail": "jobs",
    "backups": "backups", "backup-job-create": "backups", "backup-job-edit": "backups", "backup-runs": "backups", "backup-tree": "backups", "backup-run-status": "backups", "backup-run-detail": "backups",
    "backup-http-manifest": "backups", "backup-http-list": "backups", "backup-http-stat": "backups", "backup-http-compare": "backups", "backup-http-prune": "backups", "backup-http-file": "backups", "backup-http-delete": "backups",
}


def feature_keys_for_user(user):
    if not user.is_authenticated:
        return frozenset()
    if user.is_staff or user.is_superuser:
        return FEATURE_KEYS
    return frozenset(user.feature_accesses.filter(feature__in=FEATURE_KEYS).values_list("feature", flat=True))


def feature_catalog_for_user(user):
    allowed = feature_keys_for_user(user)
    return [{**item, "url": reverse(item["url_name"]), "allowed": item["key"] in allowed} for item in FEATURES]


def user_has_feature(user, feature):
    return feature in feature_keys_for_user(user)
