import os
import platform
import socket
import time
import logging
from collections import Counter
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import psutil
from django.db import transaction
from django.db import OperationalError
from django.utils import timezone

from alerts_app.services import evaluate_alerts
from .memory import build_memory_breakdown
from main_app.models import MonitoringSettings, ProcessSnapshot, SystemSnapshot
from reports_app.services import dispatch_scheduled_reports


_LAST_NETWORK_SAMPLE = None
_PROCESS_CPU_PRIMED = False
logger = logging.getLogger(__name__)

HOST_ROOT_PATH = os.getenv("MONITOR_ROOT_PATH", "/")
HOST_PROCFS_PATH = os.getenv("MONITOR_PROCFS_PATH")
if HOST_PROCFS_PATH:
    psutil.PROCFS_PATH = HOST_PROCFS_PATH


def _mb(value):
    return round(value / 1024 / 1024, 2)


def _gb(value):
    return round(value / 1024 / 1024 / 1024, 2)


def _safe_load_avg():
    try:
        return os.getloadavg()
    except (AttributeError, OSError):
        return (0.0, 0.0, 0.0)


def _host_os_release():
    os_release_path = os.path.join(HOST_ROOT_PATH, "etc", "os-release")
    data = {}
    try:
        with open(os_release_path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or "=" not in line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                data[key] = value.strip().strip('"')
    except OSError:
        return {}
    return data


def _platform_label():
    system_name = platform.system()
    release = platform.release()
    if system_name != "Linux":
        return f"{system_name} {release}".strip()
    info = _host_os_release()
    distro_name = (info.get("PRETTY_NAME") or info.get("NAME") or "").strip().strip('"')
    if distro_name:
        return distro_name
    return f"Linux {release}".strip()


def _network_stats():
    global _LAST_NETWORK_SAMPLE

    current = psutil.net_io_counters()
    now = time.time()
    sent_rate = 0.0
    recv_rate = 0.0

    if _LAST_NETWORK_SAMPLE:
        elapsed = max(now - _LAST_NETWORK_SAMPLE["timestamp"], 1)
        sent_rate = ((current.bytes_sent - _LAST_NETWORK_SAMPLE["bytes_sent"]) * 8) / elapsed / 1024
        recv_rate = ((current.bytes_recv - _LAST_NETWORK_SAMPLE["bytes_recv"]) * 8) / elapsed / 1024

    _LAST_NETWORK_SAMPLE = {
        "timestamp": now,
        "bytes_sent": current.bytes_sent,
        "bytes_recv": current.bytes_recv,
    }

    return {
        "sent_mb": _mb(current.bytes_sent),
        "recv_mb": _mb(current.bytes_recv),
        "sent_rate_kbps": round(max(sent_rate, 0), 2),
        "recv_rate_kbps": round(max(recv_rate, 0), 2),
    }


def _disk_devices():
    devices_by_mount = {}
    for partition in psutil.disk_partitions(all=False):
        mountpoint = partition.mountpoint or ""
        if not mountpoint.startswith(HOST_ROOT_PATH):
            continue
        if not os.path.isdir(mountpoint):
            continue
        host_mountpoint = os.path.normpath("/" + os.path.relpath(mountpoint, HOST_ROOT_PATH).lstrip("./"))
        if host_mountpoint == "/.":
            host_mountpoint = "/"
        try:
            usage = psutil.disk_usage(mountpoint)
        except PermissionError:
            continue
        current = devices_by_mount.get(host_mountpoint)
        candidate = {
            "device": partition.device,
            "mountpoint": host_mountpoint,
            "fstype": partition.fstype,
            "total_gb": _gb(usage.total),
            "used_gb": _gb(usage.used),
            "free_gb": _gb(usage.free),
            "percent": round(usage.percent, 2),
            "free_percent": round(max(100 - usage.percent, 0), 2),
            "is_mounted": True,
            "status_label": "Mounted",
        }
        if current is None or (current.get("fstype") == "autofs" and partition.fstype != "autofs"):
            devices_by_mount[host_mountpoint] = candidate

    for entry in _fstab_automount_entries():
        devices_by_mount.setdefault(entry["mountpoint"], entry)

    devices = list(devices_by_mount.values())
    devices.sort(key=lambda item: (item["mountpoint"] != "/", item["mountpoint"]))
    return devices


def disk_devices():
    return _disk_devices()


def _fstab_automount_entries():
    fstab_path = os.path.join(HOST_ROOT_PATH, "etc", "fstab")
    entries = []
    try:
        with open(fstab_path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                source, mountpoint, fstype, options = parts[:4]
                if not mountpoint.startswith("/"):
                    continue
                if fstype in {"swap", "proc", "sysfs", "tmpfs", "devtmpfs", "cgroup2", "overlay"}:
                    continue
                option_set = {item.strip() for item in options.split(",") if item.strip()}
                if "x-systemd.automount" not in option_set:
                    continue
                entries.append(
                    {
                        "device": _resolve_fstab_source(source),
                        "mountpoint": mountpoint,
                        "fstype": fstype,
                        "total_gb": _fstab_entry_total_gb(source),
                        "used_gb": None,
                        "free_gb": None,
                        "percent": None,
                        "free_percent": None,
                        "is_mounted": False,
                        "status_label": "Idle automount",
                    }
                )
    except OSError:
        return []
    return entries


def _resolve_fstab_source(source):
    if source.startswith("UUID="):
        uuid_value = source.split("=", 1)[1]
        resolved = Path(HOST_ROOT_PATH) / "dev" / "disk" / "by-uuid" / uuid_value
        try:
            target = resolved.resolve(strict=True)
        except OSError:
            return source
        target_text = str(target)
        if target_text.startswith(HOST_ROOT_PATH):
            return target_text[len(HOST_ROOT_PATH):] or "/"
        return target_text
    return source


def _fstab_entry_total_gb(source):
    block_name = _source_block_name(source)
    if not block_name:
        return None
    size_path = Path(HOST_ROOT_PATH) / "sys" / "class" / "block" / block_name / "size"
    try:
        sectors = int(size_path.read_text(encoding="utf-8").strip() or "0")
    except OSError:
        return None
    return _gb(sectors * 512)


def _source_block_name(source):
    resolved = _resolve_fstab_source(source)
    if resolved.startswith("/dev/"):
        return os.path.basename(resolved)
    return ""


def _process_rows(limit):
    global _PROCESS_CPU_PRIMED

    if not _PROCESS_CPU_PRIMED:
        for process in psutil.process_iter():
            try:
                process.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        _PROCESS_CPU_PRIMED = True

    rows = []
    status_counts = Counter()
    total = 0
    running = 0
    sleeping = 0
    stopped = 0
    zombie = 0

    for process in psutil.process_iter(
        [
            "pid",
            "name",
            "username",
            "status",
            "cpu_percent",
            "memory_percent",
            "memory_info",
            "num_threads",
            "cmdline",
        ]
    ):
        total += 1
        try:
            info = process.info
            status = info.get("status") or "unknown"
            status_counts[status] += 1
            if status == psutil.STATUS_RUNNING:
                running += 1
            elif status in {psutil.STATUS_SLEEPING, getattr(psutil, "STATUS_IDLE", "idle")}:
                sleeping += 1
            elif status == psutil.STATUS_STOPPED:
                stopped += 1
            elif status == psutil.STATUS_ZOMBIE:
                zombie += 1

            memory_info = info.get("memory_info")
            command = " ".join(info.get("cmdline") or [])
            rows.append(
                {
                    "pid": info.get("pid") or 0,
                    "name": info.get("name") or "unknown",
                    "username": info.get("username") or "",
                    "status": status,
                    "cpu_percent": round(info.get("cpu_percent") or 0, 2),
                    "memory_percent": round(info.get("memory_percent") or 0, 2),
                    "memory_rss_mb": _mb(memory_info.rss) if memory_info else 0,
                    "threads": info.get("num_threads") or 0,
                    "command": command,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    rows.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)
    return {
        "rows": rows[:limit],
        "total": total,
        "running": running,
        "sleeping": sleeping,
        "stopped": stopped,
        "zombie": zombie,
        "status_counts": dict(status_counts),
    }


def collect_snapshot():
    settings_obj = MonitoringSettings.load()
    hostname = socket.gethostname()
    platform_label = _platform_label()

    boot_dt = datetime.fromtimestamp(psutil.boot_time(), tz=dt_timezone.utc)
    uptime = int(time.time() - psutil.boot_time())

    cpu_percent = round(psutil.cpu_percent(interval=1), 2)
    per_cpu = [round(value, 2) for value in psutil.cpu_percent(interval=None, percpu=True)]
    memory = psutil.virtual_memory()
    memory_breakdown = build_memory_breakdown(
        used_mb=_mb(memory.used),
        available_mb=_mb(memory.available),
        cached_mb=_mb(getattr(memory, "cached", 0)),
        buffers_mb=_mb(getattr(memory, "buffers", 0)),
        slab_mb=_mb(getattr(memory, "slab", 0)),
    )
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(HOST_ROOT_PATH)
    load_avg = _safe_load_avg()
    network = _network_stats()
    disks = disk_devices()
    process_data = _process_rows(settings_obj.top_process_limit)

    with transaction.atomic():
        snapshot = SystemSnapshot.objects.create(
            hostname=hostname,
            platform_label=platform_label,
            boot_time=boot_dt,
            uptime_seconds=uptime,
            cpu_percent=cpu_percent,
            cpu_count_logical=psutil.cpu_count() or 0,
            cpu_count_physical=psutil.cpu_count(logical=False) or 0,
            load_avg_1=round(load_avg[0], 2),
            load_avg_5=round(load_avg[1], 2),
            load_avg_15=round(load_avg[2], 2),
            per_cpu_percent=per_cpu,
            memory_total_mb=_mb(memory.total),
            memory_used_mb=memory_breakdown["used_mb"],
            memory_available_mb=memory_breakdown["available_mb"],
            memory_cached_mb=memory_breakdown["cached_mb"],
            memory_buffers_mb=memory_breakdown["buffers_mb"],
            memory_slab_mb=memory_breakdown["slab_mb"],
            memory_percent=round(memory.percent, 2),
            swap_total_mb=_mb(swap.total),
            swap_used_mb=_mb(swap.used),
            swap_percent=round(swap.percent, 2),
            disk_total_gb=_gb(disk.total),
            disk_used_gb=_gb(disk.used),
            disk_free_gb=_gb(disk.free),
            disk_percent=round(disk.percent, 2),
            network_sent_mb=network["sent_mb"],
            network_recv_mb=network["recv_mb"],
            network_sent_rate_kbps=network["sent_rate_kbps"],
            network_recv_rate_kbps=network["recv_rate_kbps"],
            process_count_total=process_data["total"],
            process_count_running=process_data["running"],
            process_count_sleeping=process_data["sleeping"],
            process_count_stopped=process_data["stopped"],
            process_count_zombie=process_data["zombie"],
            process_status_counts=process_data["status_counts"],
            disk_devices=disks,
        )

        ProcessSnapshot.objects.bulk_create(
            [ProcessSnapshot(snapshot=snapshot, **row) for row in process_data["rows"]]
        )

    for action, label in [
        (lambda: evaluate_alerts(snapshot, settings_obj=settings_obj), "evaluate alerts"),
        (lambda: dispatch_scheduled_reports(snapshot, settings_obj=settings_obj), "dispatch reports"),
        (lambda: prune_old_snapshots(settings_obj.history_retention_days), "prune old snapshots"),
    ]:
        try:
            action()
        except OperationalError as exc:
            logger.warning("Skipping %s because the database is busy: %s", label, exc)
    return snapshot


def prune_old_snapshots(retention_days):
    cutoff = timezone.now() - timezone.timedelta(days=retention_days)
    SystemSnapshot.objects.filter(captured_at__lt=cutoff).delete()
