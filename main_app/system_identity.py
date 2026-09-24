import os
import socket
from pathlib import Path


MAX_SYSTEM_NAME_LENGTH = 255


def _clean_name(value):
    """Return a safe, single-line system name or an empty string."""
    if not value:
        return ""
    return " ".join(str(value).split())[:MAX_SYSTEM_NAME_LENGTH]


def detected_hostname():
    """Resolve the monitored host name, including when running in Docker."""
    configured_hostname = _clean_name(os.getenv("SYSTEM_MONITOR_HOSTNAME"))
    if configured_hostname:
        return configured_hostname

    monitor_root = Path(os.getenv("MONITOR_ROOT_PATH", "/"))
    if monitor_root != Path("/"):
        for relative_path in ("etc/hostname", "proc/sys/kernel/hostname"):
            try:
                hostname = _clean_name((monitor_root / relative_path).read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if hostname:
                return hostname

    return _clean_name(socket.gethostname()) or "unknown-host"


def system_display_name(configured_name=""):
    """Return the administrator label, falling back to the monitored hostname."""
    return _clean_name(configured_name) or detected_hostname()
