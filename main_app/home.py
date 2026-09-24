import logging

from django.db.models import Count, Q

from alerts_app.models import AlertEvent
from backups_app.models import BackupJob, BackupRun
from docker_runtime_app.runtime import get_docker_overview
from file_manager_app.access import access_roots, has_full_file_access
from jobs_app.models import ScriptJob, ScriptJobRun
from monitor_app.models import SystemSnapshot
from reports_app.models import ReportRule, ReportRun
from volumes_app.models import VolumeMountPreference, VolumeOperation

from .features import feature_catalog_for_user


logger = logging.getLogger(__name__)


def _metric(value, label):
    return {"value": value, "label": label}


def _monitor_summary(_user):
    snapshot = SystemSnapshot.objects.only("captured_at", "cpu_percent", "memory_percent").first()
    if not snapshot:
        return {"message": "Waiting for the first system sample.", "metrics": []}
    return {
        "message": "Latest system sample",
        "timestamp": snapshot.captured_at,
        "metrics": [_metric(f"{snapshot.cpu_percent:.0f}%", "CPU"), _metric(f"{snapshot.memory_percent:.0f}%", "Memory")],
    }


def _history_summary(_user):
    snapshot = SystemSnapshot.objects.only("captured_at").first()
    return {
        "message": "Stored monitoring samples",
        "timestamp": snapshot.captured_at if snapshot else None,
        "metrics": [_metric(SystemSnapshot.objects.count(), "Samples")],
    }


def _alerts_summary(_user):
    totals = AlertEvent.objects.aggregate(total=Count("id"), active=Count("id", filter=Q(is_active=True)))
    latest = AlertEvent.objects.only("triggered_at").first()
    return {
        "message": "Alert events and current activity",
        "timestamp": latest.triggered_at if latest else None,
        "metrics": [_metric(totals["active"], "Active"), _metric(totals["total"], "Total")],
    }


def _reports_summary(_user):
    latest = ReportRun.objects.only("generated_at").first()
    return {
        "message": "Scheduled and generated reports",
        "timestamp": latest.generated_at if latest else None,
        "metrics": [_metric(ReportRule.objects.filter(enabled=True).count(), "Enabled"), _metric(ReportRun.objects.count(), "Generated")],
    }


def _docker_summary(_user):
    overview = get_docker_overview()
    return {
        "message": "Current container runtime",
        "metrics": [
            _metric(overview["running_containers_count"], "Running"),
            _metric(overview["stopped_containers_count"], "Stopped"),
        ],
    }


def _files_summary(user):
    roots = access_roots(user)
    full_access = has_full_file_access(user)
    return {
        "message": "All server paths are available" if full_access else "Access is limited to assigned locations",
        "metrics": [_metric("All" if full_access else len(roots), "Accessible paths")],
    }


def _volumes_summary(_user):
    return {
        "message": "Storage devices and recent operations",
        "metrics": [
            _metric(VolumeMountPreference.objects.count(), "Remembered"),
            _metric(VolumeOperation.objects.filter(status="running").count(), "In progress"),
        ],
    }


def _jobs_summary(_user):
    latest = ScriptJobRun.objects.only("started_at", "status").first()
    return {
        "message": f"Latest run: {latest.get_status_display()}" if latest else "No script runs yet",
        "timestamp": latest.started_at if latest else None,
        "metrics": [_metric(ScriptJob.objects.filter(enabled=True).count(), "Enabled"), _metric(ScriptJobRun.objects.filter(status="running").count(), "Running")],
    }


def _backups_summary(_user):
    latest = BackupRun.objects.only("started_at", "status").first()
    return {
        "message": f"Latest run: {latest.get_status_display()}" if latest else "No backup runs yet",
        "timestamp": latest.started_at if latest else None,
        "metrics": [_metric(BackupJob.objects.filter(enabled=True).count(), "Enabled"), _metric(BackupRun.objects.filter(status="running").count(), "Running")],
    }


SUMMARY_PROVIDERS = {
    "monitor": _monitor_summary,
    "history": _history_summary,
    "alerts": _alerts_summary,
    "reports": _reports_summary,
    "docker": _docker_summary,
    "files": _files_summary,
    "volumes": _volumes_summary,
    "jobs": _jobs_summary,
    "backups": _backups_summary,
}


def home_features_for_user(user):
    """Return launchable, permitted features enriched by their owning app's summary."""
    features = [feature for feature in feature_catalog_for_user(user) if feature["allowed"] and feature["url"]]
    for feature in features:
        provider = SUMMARY_PROVIDERS.get(feature["key"])
        if not provider:
            continue
        try:
            feature["summary"] = provider(user)
        except Exception:
            logger.exception("Unable to build the %s home summary", feature["key"])
            feature["summary"] = {"message": "Summary temporarily unavailable", "metrics": []}
    return features
