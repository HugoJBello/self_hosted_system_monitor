from collections import defaultdict
from datetime import timedelta
from math import ceil

from django.db.models import Avg, Max
from django.urls import reverse
from django.utils import timezone

from .models import MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, SystemSnapshot
from .notification_client import send_json_notification


REPORT_TARGET_POINTS = 72


def format_history_tick(dt_value, hours):
    if hours <= 24:
        return dt_value.strftime("%H:%M")
    if hours <= 72:
        return dt_value.strftime("%d %H:%M")
    return dt_value.strftime("%d %b")


def format_duration(seconds):
    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds and not hours:
        parts.append(f"{seconds}s")
    return " ".join(parts) or "0s"


def build_time_series_chart_data(snapshots, *, hours, sample_interval_seconds, window_start, window_end, target_points=REPORT_TARGET_POINTS):
    dataset_keys = {
        "cpu_percent": "cpu",
        "memory_percent": "memory",
        "swap_percent": "swap",
        "disk_percent": "disk",
        "load_avg_1": "load",
        "network_sent_rate_kbps": "net_sent",
        "network_recv_rate_kbps": "net_recv",
        "process_count_total": "proc_total",
        "process_count_running": "proc_running",
    }

    total_window_seconds = max(int((window_end - window_start).total_seconds()), 1)
    bucket_seconds = max(sample_interval_seconds, ceil(total_window_seconds / max(target_points, 1)))
    bucket_count = max(1, ceil(total_window_seconds / bucket_seconds))
    buckets = [[] for _ in range(bucket_count)]

    for row in snapshots:
        delta_seconds = int((row["captured_at"] - window_start).total_seconds())
        index = min(max(delta_seconds // bucket_seconds, 0), bucket_count - 1)
        buckets[index].append(row)

    chart_data = {
        "labels": [],
        "full_labels": [],
        "label_datetimes": [],
        "range_start_isos": [],
        "range_end_isos": [],
        "has_data": [],
        "missing_periods": [],
        "bucket_seconds": bucket_seconds,
        "sample_interval_seconds": sample_interval_seconds,
    }
    for key in dataset_keys.values():
        chart_data[key] = []

    missing_start = None
    for index, rows in enumerate(buckets):
        bucket_start = window_start + timedelta(seconds=index * bucket_seconds)
        bucket_end = min(window_end, bucket_start + timedelta(seconds=bucket_seconds))
        midpoint = bucket_start + (bucket_end - bucket_start) / 2
        chart_data["labels"].append(format_history_tick(midpoint, hours))
        chart_data["label_datetimes"].append(midpoint.isoformat())
        chart_data["range_start_isos"].append(bucket_start.isoformat())
        chart_data["range_end_isos"].append(bucket_end.isoformat())
        chart_data["full_labels"].append(
            f"{bucket_start.strftime('%Y-%m-%d %H:%M:%S')} UTC to {bucket_end.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        has_data = bool(rows)
        chart_data["has_data"].append(has_data)

        if has_data:
            if missing_start is not None:
                missing_end = bucket_start
                chart_data["missing_periods"].append(
                    {
                        "start": missing_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": missing_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "start_iso": missing_start.isoformat(),
                        "end_iso": missing_end.isoformat(),
                        "duration": format_duration((missing_end - missing_start).total_seconds()),
                    }
                )
                missing_start = None
            for metric_name, dataset_key in dataset_keys.items():
                values = [float(item[metric_name] or 0) for item in rows]
                chart_data[dataset_key].append(round(sum(values) / len(values), 2))
        else:
            if missing_start is None:
                missing_start = bucket_start
            for dataset_key in dataset_keys.values():
                chart_data[dataset_key].append(None)

    if missing_start is not None:
        chart_data["missing_periods"].append(
            {
                "start": missing_start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": window_end.strftime("%Y-%m-%d %H:%M:%S"),
                "start_iso": missing_start.isoformat(),
                "end_iso": window_end.isoformat(),
                "duration": format_duration((window_end - missing_start).total_seconds()),
            }
        )

    return chart_data


def build_period_process_summary(window_start, window_end, limit=8):
    grouped_rows = list(
        ProcessSnapshot.objects.filter(
            snapshot__captured_at__gte=window_start,
            snapshot__captured_at__lte=window_end,
        )
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
    for row in grouped_rows:
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

    return sorted(
        [
            {
                "name": entry["name"],
                "username": entry["username"],
                "samples": entry["samples"],
                "avg_cpu": round(entry["avg_cpu_sum"] / entry["samples"], 2),
                "peak_cpu": round(entry["peak_cpu"], 2),
                "avg_memory": round(entry["avg_memory_sum"] / entry["samples"], 2),
                "peak_memory": round(entry["peak_memory"], 2),
                "max_rss_mb": round(entry["max_rss_mb"], 2),
                "last_seen_at": entry["last_seen_at"].strftime("%Y-%m-%d %H:%M:%S") if entry["last_seen_at"] else "",
                "statuses": sorted(entry["statuses"]),
                "commands": entry["commands"],
            }
            for entry in grouped_processes.values()
        ],
        key=lambda item: (item["avg_cpu"], item["peak_memory"], item["max_rss_mb"]),
        reverse=True,
    )[:limit]


def build_report_data(rule, settings_obj, *, window_end=None):
    window_end = window_end or timezone.now()
    window_start = window_end - timedelta(hours=rule.period_hours)
    snapshots_qs = SystemSnapshot.objects.filter(
        captured_at__gte=window_start,
        captured_at__lte=window_end,
    ).order_by("captured_at")
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
    latest_snapshot = snapshots_qs.order_by("-captured_at").first()
    chart_data = build_time_series_chart_data(
        snapshots,
        hours=rule.period_hours,
        sample_interval_seconds=settings_obj.sample_interval_seconds,
        window_start=window_start,
        window_end=window_end,
        target_points=REPORT_TARGET_POINTS,
    )
    aggregates = snapshots_qs.aggregate(
        avg_cpu=Avg("cpu_percent"),
        avg_memory=Avg("memory_percent"),
        avg_disk=Avg("disk_percent"),
        avg_load=Avg("load_avg_1"),
        avg_process_total=Avg("process_count_total"),
        max_cpu=Max("cpu_percent"),
        max_memory=Max("memory_percent"),
        max_disk=Max("disk_percent"),
        max_load=Max("load_avg_1"),
    )
    top_processes = build_period_process_summary(window_start, window_end, limit=8)
    summary_lines = [
        f"CPU average {float(aggregates['avg_cpu'] or 0):.1f}% with peak {float(aggregates['max_cpu'] or 0):.1f}%.",
        f"Memory average {float(aggregates['avg_memory'] or 0):.1f}% with peak {float(aggregates['max_memory'] or 0):.1f}%.",
        f"Disk average {float(aggregates['avg_disk'] or 0):.1f}% with peak {float(aggregates['max_disk'] or 0):.1f}%.",
        f"Load average {float(aggregates['avg_load'] or 0):.2f} with peak {float(aggregates['max_load'] or 0):.2f}.",
    ]
    if chart_data["missing_periods"]:
        summary_lines.append(
            f"Detected {len(chart_data['missing_periods'])} period(s) without data in this report window."
        )
    if top_processes:
        hottest = top_processes[0]
        summary_lines.append(
            f"Highest recurring process pressure came from {hottest['name']} at {hottest['avg_cpu']:.1f}% avg CPU and {hottest['avg_memory']:.1f}% avg memory."
        )

    return {
        "window_start": window_start.strftime("%Y-%m-%d %H:%M:%S"),
        "window_end": window_end.strftime("%Y-%m-%d %H:%M:%S"),
        "period_hours": rule.period_hours,
        "snapshot_count": len(snapshots),
        "latest_snapshot_at": latest_snapshot.captured_at.strftime("%Y-%m-%d %H:%M:%S") if latest_snapshot else "",
        "chart_data": chart_data,
        "aggregates": {key: round(float(value or 0), 2) for key, value in aggregates.items()},
        "top_processes": top_processes,
        "summary_lines": summary_lines,
    }


def build_report_link(settings_obj, report_run):
    if not settings_obj.normalized_app_public_base_url:
        return ""
    return f"{settings_obj.normalized_app_public_base_url}{reverse('monitor:report-detail', args=[report_run.id])}"


def build_report_notification_payload(settings_obj, rule, report_run):
    report_data = report_run.report_data
    summary = "\n".join(f"- {line}" for line in report_data.get("summary_lines", []))
    link = build_report_link(settings_obj, report_run)
    link_line = f"\nReport link: {link}" if link else ""
    payload = {
        "origin": settings_obj.notifications_default_origin or "system-monitor",
        "status": "info",
        "priority": "normal",
        "action": settings_obj.notifications_default_action or "notify",
        "title": report_run.title,
        "message": (
            f"{report_run.message}\n\n"
            f"Window: {report_data.get('window_start')} UTC -> {report_data.get('window_end')} UTC\n"
            f"Snapshots: {report_run.sample_count}\n"
            f"{summary}{link_line}"
        ),
        "channels": rule.notification_channels_list or settings_obj.notifications_channels_list or ["email"],
    }
    tags = rule.notification_tags_list or settings_obj.notifications_tags_list
    if tags:
        payload["tags"] = tags
    if rule.notification_user or settings_obj.notifications_default_user:
        payload["user"] = rule.notification_user or settings_obj.notifications_default_user
    return payload


def notify_report_run(settings_obj, rule, report_run):
    result = send_json_notification(settings_obj, build_report_notification_payload(settings_obj, rule, report_run))
    report_run.notification_sent = result["ok"]
    report_run.notification_status_code = result["status_code"]
    report_run.notification_response = result["body"]
    report_run.save(update_fields=["notification_sent", "notification_status_code", "notification_response"])


def generate_report_for_rule(rule, settings_obj=None, *, window_end=None):
    settings_obj = settings_obj or MonitoringSettings.load()
    window_end = window_end or timezone.now()
    report_data = build_report_data(rule, settings_obj, window_end=window_end)
    report_run = ReportRun.objects.create(
        rule=rule,
        title=f"{rule.name} report",
        message=f"Periodic report for the last {rule.period_hours} hour(s).",
        window_start=window_end - timedelta(hours=rule.period_hours),
        window_end=window_end,
        generated_at=window_end,
        sample_count=report_data["snapshot_count"],
        report_data=report_data,
    )
    if settings_obj.notifications_enabled and rule.send_notifications:
        notify_report_run(settings_obj, rule, report_run)
    rule.last_run_at = window_end
    next_run_at = rule.next_run_at or window_end
    cadence = timedelta(hours=max(rule.cadence_hours, 1))
    while next_run_at <= window_end:
        next_run_at += cadence
    rule.next_run_at = next_run_at
    rule.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
    return report_run


def dispatch_scheduled_reports(snapshot, settings_obj=None):
    settings_obj = settings_obj or MonitoringSettings.load()
    due_rules = ReportRule.objects.filter(
        enabled=True,
        next_run_at__isnull=False,
        next_run_at__lte=snapshot.captured_at,
    ).order_by("position", "id")
    reports = []
    for rule in due_rules:
        reports.append(generate_report_for_rule(rule, settings_obj=settings_obj, window_end=snapshot.captured_at))
    return reports
