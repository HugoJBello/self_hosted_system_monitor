from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from main_app.models import MonitoringSettings
from monitor_app.models import ProcessSnapshot, SystemSnapshot
from alerts_app.models import AlertEvent, AlertRule
from main_app.notification_client import send_json_notification


DEFAULT_ALERT_RULES = [
    {
        "position": 10,
        "name": "High CPU sustained",
        "description": "Triggers when CPU usage stays high for several snapshots.",
        "severity": "warning",
        "metric": "cpu_percent",
        "evaluation_mode": "avg",
        "comparator": "gte",
        "threshold": 85,
        "window_minutes": 5,
        "min_occurrences": 3,
        "cooldown_minutes": 30,
        "notification_tags": "server;cpu",
    },
    {
        "position": 20,
        "name": "Critical memory pressure",
        "description": "Triggers when RAM usage is critically high.",
        "severity": "critical",
        "metric": "memory_percent",
        "evaluation_mode": "current",
        "comparator": "gte",
        "threshold": 92,
        "window_minutes": 1,
        "min_occurrences": 1,
        "cooldown_minutes": 20,
        "notification_tags": "server;memory",
    },
    {
        "position": 30,
        "name": "Disk almost full",
        "description": "Triggers when the monitored root filesystem is near capacity.",
        "severity": "critical",
        "metric": "disk_percent",
        "evaluation_mode": "current",
        "comparator": "gte",
        "threshold": 90,
        "window_minutes": 1,
        "min_occurrences": 1,
        "cooldown_minutes": 60,
        "notification_tags": "server;disk",
    },
    {
        "position": 40,
        "name": "Zombie process detected",
        "description": "Triggers when zombie processes appear.",
        "severity": "warning",
        "metric": "process_count_zombie",
        "evaluation_mode": "current",
        "comparator": "gte",
        "threshold": 1,
        "window_minutes": 1,
        "min_occurrences": 1,
        "cooldown_minutes": 15,
        "notification_tags": "server;processes",
    },
]

PROCESS_CONTEXT_METRICS = {
    "cpu_percent": "cpu",
    "load_avg_1": "cpu",
    "load_avg_5": "cpu",
    "load_avg_15": "cpu",
    "memory_percent": "memory",
    "swap_percent": "memory",
}


@dataclass
class EvaluationResult:
    triggered: bool
    evaluated_value: float
    matching_count: int
    sample_count: int


def ensure_default_alert_rules():
    if AlertRule.objects.exists():
        return
    AlertRule.objects.bulk_create([AlertRule(**rule) for rule in DEFAULT_ALERT_RULES])


def _metric_value(snapshot, metric):
    value = getattr(snapshot, metric, 0)
    return float(value or 0)


def _compare(lhs, comparator, rhs):
    if comparator == "gt":
        return lhs > rhs
    if comparator == "gte":
        return lhs >= rhs
    if comparator == "lt":
        return lhs < rhs
    if comparator == "lte":
        return lhs <= rhs
    return False


def evaluate_rule(rule, snapshot):
    if rule.evaluation_mode == "current":
        current_value = _metric_value(snapshot, rule.metric)
        return EvaluationResult(
            triggered=_compare(current_value, rule.comparator, rule.threshold),
            evaluated_value=current_value,
            matching_count=1 if _compare(current_value, rule.comparator, rule.threshold) else 0,
            sample_count=1,
        )

    cutoff = timezone.now() - timezone.timedelta(minutes=max(rule.window_minutes, 1))
    snapshots = list(
        SystemSnapshot.objects.filter(captured_at__gte=cutoff, captured_at__lte=snapshot.captured_at).order_by("captured_at")
    )
    if not snapshots:
        snapshots = [snapshot]

    values = [_metric_value(item, rule.metric) for item in snapshots]
    matching_count = sum(1 for value in values if _compare(value, rule.comparator, rule.threshold))
    if rule.evaluation_mode == "avg":
        evaluated_value = sum(values) / len(values)
    elif rule.evaluation_mode == "max":
        evaluated_value = max(values)
    else:
        evaluated_value = min(values)

    triggered = _compare(evaluated_value, rule.comparator, rule.threshold) and matching_count >= rule.min_occurrences
    return EvaluationResult(
        triggered=triggered,
        evaluated_value=round(evaluated_value, 2),
        matching_count=matching_count,
        sample_count=len(values),
    )


def _event_title(rule):
    return f"{rule.severity.title()} alert: {rule.name}"


def top_processes_for_alert_window(rule, snapshot, limit=5):
    metric_family = PROCESS_CONTEXT_METRICS.get(rule.metric)
    if not metric_family:
        return []

    cutoff = snapshot.captured_at - timezone.timedelta(minutes=max(rule.window_minutes, 1))
    rows = list(
        ProcessSnapshot.objects.filter(
            snapshot__captured_at__gte=cutoff,
            snapshot__captured_at__lte=snapshot.captured_at,
        )
        .values(
            "name",
            "username",
            "cpu_percent",
            "memory_percent",
            "memory_rss_mb",
        )
    )
    if not rows:
        return []

    grouped = {}
    for row in rows:
        key = (row["name"], row["username"] or "")
        if key not in grouped:
            grouped[key] = {
                "name": row["name"],
                "username": row["username"] or "",
                "samples": 0,
                "avg_cpu_sum": 0.0,
                "peak_cpu": 0.0,
                "avg_memory_sum": 0.0,
                "peak_memory": 0.0,
                "max_rss_mb": 0.0,
            }
        entry = grouped[key]
        cpu_value = float(row["cpu_percent"] or 0)
        memory_value = float(row["memory_percent"] or 0)
        rss_value = float(row["memory_rss_mb"] or 0)
        entry["samples"] += 1
        entry["avg_cpu_sum"] += cpu_value
        entry["peak_cpu"] = max(entry["peak_cpu"], cpu_value)
        entry["avg_memory_sum"] += memory_value
        entry["peak_memory"] = max(entry["peak_memory"], memory_value)
        entry["max_rss_mb"] = max(entry["max_rss_mb"], rss_value)

    aggregated = []
    for entry in grouped.values():
        aggregated.append(
            {
                "name": entry["name"],
                "username": entry["username"],
                "samples": entry["samples"],
                "avg_cpu": entry["avg_cpu_sum"] / entry["samples"],
                "peak_cpu": entry["peak_cpu"],
                "avg_memory": entry["avg_memory_sum"] / entry["samples"],
                "peak_memory": entry["peak_memory"],
                "max_rss_mb": entry["max_rss_mb"],
            }
        )

    if metric_family == "cpu":
        aggregated.sort(key=lambda item: (item["avg_cpu"], item["peak_cpu"], item["avg_memory"]), reverse=True)
    else:
        aggregated.sort(
            key=lambda item: (item["avg_memory"], item["peak_memory"], item["max_rss_mb"], item["avg_cpu"]),
            reverse=True,
        )
    return aggregated[:limit]


def _format_process_context(rule, snapshot, limit=3):
    processes = top_processes_for_alert_window(rule, snapshot, limit=limit)
    if not processes:
        return "", []

    metric_family = PROCESS_CONTEXT_METRICS.get(rule.metric)
    summary_parts = []
    for process in processes:
        identity = process["name"]
        if metric_family == "cpu":
            summary_parts.append(f"{identity} ({process['avg_cpu']:.1f}% avg CPU, peak {process['peak_cpu']:.1f}%)")
        else:
            summary_parts.append(
                f"{identity} ({process['avg_memory']:.1f}% avg MEM, peak {process['peak_memory']:.1f}%, RSS {process['max_rss_mb']:.1f} MB)"
            )
    return f" Top processes in the evaluation window: {', '.join(summary_parts)}.", processes


def _event_message(rule, result, snapshot):
    metric_label = dict(AlertRule.METRIC_CHOICES).get(rule.metric, rule.metric)
    eval_label = dict(AlertRule.EVALUATION_CHOICES).get(rule.evaluation_mode, rule.evaluation_mode)
    comparator_label = dict(AlertRule.COMPARATOR_CHOICES).get(rule.comparator, rule.comparator)
    base_message = (
        f"{metric_label} is {result.evaluated_value:.2f} "
        f"({eval_label.lower()} {comparator_label} {rule.threshold:.2f}) "
        f"with {result.matching_count}/{result.sample_count} matching samples in the last {max(rule.window_minutes, 1)} minute(s)."
    )
    process_context, _ = _format_process_context(rule, snapshot)
    return base_message + process_context


def _build_alert_payload(settings_obj, rule, event):
    status_map = {
        "info": "warning",
        "warning": "warning",
        "critical": "critical",
    }
    priority_map = {
        "info": "low",
        "warning": "normal",
        "critical": "high",
    }
    payload = {
        "origin": settings_obj.notifications_default_origin or "system-monitor",
        "status": status_map.get(rule.severity, settings_obj.notifications_default_status or "warning"),
        "priority": priority_map.get(rule.severity, settings_obj.notifications_default_priority or "high"),
        "action": settings_obj.notifications_default_action or "notify",
        "title": event.title,
        "message": event.message,
        "channels": rule.notification_channels_list or settings_obj.notifications_channels_list or ["email"],
    }
    tags = rule.notification_tags_list or settings_obj.notifications_tags_list
    if tags:
        payload["tags"] = tags
    if rule.notification_user or settings_obj.notifications_default_user:
        payload["user"] = rule.notification_user or settings_obj.notifications_default_user
    return payload


def _notify_event(settings_obj, rule, event):
    payload = _build_alert_payload(settings_obj, rule, event)
    result = send_json_notification(settings_obj, payload)
    event.notification_sent = result["ok"]
    event.notification_status_code = result["status_code"]
    event.notification_response = result["body"]
    event.save(update_fields=["notification_sent", "notification_status_code", "notification_response"])


@transaction.atomic
def evaluate_alerts(snapshot, settings_obj=None):
    ensure_default_alert_rules()
    settings_obj = settings_obj or MonitoringSettings.load()
    now = timezone.now()

    for rule in AlertRule.objects.all():
        active_event = AlertEvent.objects.filter(rule=rule, is_active=True).order_by("-triggered_at").first()

        if not rule.enabled:
            if active_event:
                active_event.is_active = False
                active_event.resolved_at = now
                active_event.last_seen_at = now
                active_event.save(update_fields=["is_active", "resolved_at", "last_seen_at"])
            continue

        result = evaluate_rule(rule, snapshot)
        if result.triggered:
            if active_event:
                active_event.evaluated_value = result.evaluated_value
                active_event.matching_count = result.matching_count
                active_event.sample_count = result.sample_count
                active_event.message = _event_message(rule, result, snapshot)
                active_event.last_seen_at = now
                active_event.save(
                    update_fields=[
                        "evaluated_value",
                        "matching_count",
                        "sample_count",
                        "message",
                        "last_seen_at",
                    ]
                )
                continue

            last_event = AlertEvent.objects.filter(rule=rule).order_by("-triggered_at").first()
            if last_event and last_event.resolved_at:
                cooldown_until = last_event.resolved_at + timezone.timedelta(minutes=rule.cooldown_minutes)
                if now < cooldown_until:
                    continue

            event = AlertEvent.objects.create(
                rule=rule,
                snapshot=snapshot,
                title=_event_title(rule),
                message=_event_message(rule, result, snapshot),
                severity=rule.severity,
                metric=rule.metric,
                comparator=rule.comparator,
                threshold=rule.threshold,
                evaluated_value=result.evaluated_value,
                matching_count=result.matching_count,
                sample_count=result.sample_count,
                window_minutes=rule.window_minutes,
                is_active=True,
                triggered_at=now,
                last_seen_at=now,
            )
            if settings_obj.notifications_enabled and rule.notifications_enabled:
                _notify_event(settings_obj, rule, event)
        elif active_event:
            active_event.is_active = False
            active_event.resolved_at = now
            active_event.last_seen_at = now
            active_event.save(update_fields=["is_active", "resolved_at", "last_seen_at"])
