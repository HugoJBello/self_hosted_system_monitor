import json
import os
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil
from django.utils import timezone

from volumes_app.models import VolumeMountPreference, VolumeOperation
from .path_browser import hostfs_path, normalize_host_path
from monitor_app.process_control import ProcessControlError, host_namespace_prefix
from monitor_app.services import disk_devices, _gb


SYSTEM_DEVICE_PREFIXES = ("/dev/loop", "/dev/ram", "/dev/zram")
PSEUDO_FS_TYPES = {"swap", "squashfs", "iso9660"}
MOUNT_TIMEOUT_SECONDS = 30
FORMAT_TIMEOUT_SECONDS = 120
SUPPORTED_FORMATS = {
    "ext4": {"label_flag": "-L", "command": "mkfs.ext4", "force_args": ["-F"]},
    "ext3": {"label_flag": "-L", "command": "mkfs.ext3", "force_args": ["-F"]},
    "ext2": {"label_flag": "-L", "command": "mkfs.ext2", "force_args": ["-F"]},
    "xfs": {"label_flag": "-L", "command": "mkfs.xfs", "force_args": ["-f"]},
    "btrfs": {"label_flag": "-L", "command": "mkfs.btrfs", "force_args": ["-f"]},
    "vfat": {"label_flag": "-n", "command": "mkfs.vfat", "force_args": []},
    "exfat": {"label_flag": "-n", "command": "mkfs.exfat", "force_args": []},
    "ntfs": {"label_flag": "-L", "command": "mkfs.ntfs", "force_args": ["--fast", "--force"]},
}
FILESYSTEM_LABEL_LIMITS = {
    "ext2": 16,
    "ext3": 16,
    "ext4": 16,
    "xfs": 12,
    "vfat": 11,
    "fat": 11,
    "msdos": 11,
    "exfat": 15,
    "ntfs": 32,
}
LABEL_COMMANDS = {
    "ext2": ["e2label"],
    "ext3": ["e2label"],
    "ext4": ["e2label"],
    "vfat": ["fatlabel"],
    "fat": ["fatlabel"],
    "msdos": ["fatlabel"],
    "exfat": ["exfatlabel"],
    "ntfs": ["ntfslabel"],
    "btrfs": ["btrfs", "filesystem", "label"],
    "xfs": ["xfs_admin", "-L"],
}


@dataclass
class VolumeActionResult:
    ok: bool
    message: str


def _run_host_command(command, *, sudo_password="", check=True, timeout_seconds=MOUNT_TIMEOUT_SECONDS):
    command_parts = [*host_namespace_prefix(), *command]
    input_text = None
    if sudo_password:
        command_parts = [*host_namespace_prefix(), "sudo", "-S", "-p", "", *command]
        input_text = f"{sudo_password}\n"
    try:
        return subprocess.run(
            command_parts,
            check=check,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise ProcessControlError("Cannot enter the host namespace because nsenter is not installed.") from exc
    except PermissionError as exc:
        raise ProcessControlError("Permission denied while entering the host namespace.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessControlError(f"Host command timed out: {' '.join(command)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ProcessControlError(detail or f"Host command failed: {' '.join(command)}") from exc


def _command_error_text(error):
    return str(error or "").strip()


def _format_command(command_parts):
    return " ".join(shlex.quote(str(part)) for part in command_parts)


def _runner_label():
    return socket.gethostname()


def _needs_sudo(error):
    detail = _command_error_text(error).lower()
    return any(
        needle in detail
        for needle in [
            "permission denied",
            "not permitted",
            "must be superuser",
            "only root",
            "operation not permitted",
            "requires superuser",
            "requires root",
        ]
    )


def _sudo_auth_failed(error):
    detail = _command_error_text(error).lower()
    return any(
        needle in detail
        for needle in [
            "sorry, try again",
            "incorrect password",
            "authentication failure",
            "password is required",
            "no password was provided",
            "a terminal is required",
        ]
    )


def _format_action_error(action, error, *, sudo_password=""):
    detail = _command_error_text(error)
    if sudo_password and _sudo_auth_failed(error):
        return f"{action} failed because sudo authentication failed. Check the sudo password and try again."
    if not sudo_password and (_needs_sudo(error) or _sudo_auth_failed(error)):
        return f"{action} needs sudo permissions. Open advanced options, enter the sudo password, and try again."
    return f"{action} failed: {detail}" if detail else f"{action} failed."


def _clean_volume_label(label):
    label = (label or "").strip()
    if len(label) > 64:
        raise ProcessControlError("Volume label must be 64 characters or less.")
    if any(char in label for char in ["/", "\0", "\n", "\r"]):
        raise ProcessControlError("Volume label cannot contain slashes or line breaks.")
    return label


def _validate_label_for_fstype(label, fstype):
    label = _clean_volume_label(label)
    if not label:
        return ""
    fstype = _normalize_fstype(fstype)
    limit = FILESYSTEM_LABEL_LIMITS.get(fstype)
    if limit and len(label) > limit:
        raise ProcessControlError(f"Volume label is too long for {fstype}. Use {limit} characters or fewer.")
    return label


def _normalize_fstype(fstype):
    return (fstype or "").strip().lower()


def _json_host_command(command):
    try:
        result = _run_host_command(command, check=True, timeout_seconds=12)
    except ProcessControlError:
        return None
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _percent_or_none(value):
    if value is None:
        return None
    try:
        return round(float(str(value).strip().rstrip("%")), 2)
    except (TypeError, ValueError):
        return None


def _device_is_candidate(item):
    path = item.get("path") or item.get("name") or ""
    fstype = (item.get("fstype") or "").lower()
    device_type = item.get("type") or ""
    if not path.startswith("/dev/"):
        return False
    if path.startswith(SYSTEM_DEVICE_PREFIXES):
        return False
    if fstype in PSEUDO_FS_TYPES:
        return False
    return device_type in {"disk", "part", "crypt", "lvm", "raid0", "raid1", "raid5", "raid6", "raid10"}


def _flatten_lsblk(items, parent=None):
    rows = []
    for item in items or []:
        row = dict(item)
        row["parent"] = parent
        rows.append(row)
        rows.extend(_flatten_lsblk(item.get("children") or [], parent=row.get("path") or row.get("name")))
    return rows


def _usage_for_mountpoint(mountpoint):
    try:
        usage = psutil.disk_usage(hostfs_path(mountpoint))
    except (OSError, PermissionError, ValueError):
        return {"total_gb": None, "used_gb": None, "free_gb": None, "percent": None, "free_percent": None}
    return {
        "total_gb": _gb(usage.total),
        "used_gb": _gb(usage.used),
        "free_gb": _gb(usage.free),
        "percent": round(usage.percent, 2),
        "free_percent": round(max(100 - usage.percent, 0), 2),
    }


def _disk_device_entries():
    return list(disk_devices())


def _lsblk_rows():
    base_columns = "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS,MODEL,SERIAL,RM,RO,HOTPLUG,TRAN,VENDOR,STATE"
    extended_columns = f"{base_columns},FSUSED,FSAVAIL,FSUSE%"
    for columns in (extended_columns, base_columns):
        payload = _json_host_command(
            [
                "lsblk",
                "--json",
                "--paths",
                "--bytes",
                "--output",
                columns,
            ]
        )
        if payload:
            return _flatten_lsblk(payload.get("blockdevices") or [])
    return []


def _row_for_device(device):
    device = (device or "").strip()
    for row in _lsblk_rows():
        row_device = row.get("path") or row.get("name") or ""
        if row_device == device:
            return row
    return None


def _device_host_mountpoints(device):
    mountpoints = []
    try:
        result = _run_host_command(["findmnt", "--noheadings", "--source", device, "--output", "TARGET"], check=False, timeout_seconds=8)
    except ProcessControlError:
        result = None
    if result and result.returncode == 0 and (result.stdout or "").strip():
        mountpoints.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
        return list(dict.fromkeys(os.path.normpath(item) for item in mountpoints))
    row = _row_for_device(device)
    if row:
        mountpoints.extend(item for item in _as_list(row.get("mountpoints")) if item and not item.startswith("["))
    return list(dict.fromkeys(os.path.normpath(item) for item in mountpoints))


def _device_is_mounted(device):
    if _device_host_mountpoints(device):
        return True
    return bool(_namespace_mount_references(device))


def _read_proc_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _device_mount_ids(device):
    try:
        result = _run_host_command(["stat", "-c", "%t:%T", device], check=False, timeout_seconds=8)
    except ProcessControlError:
        return set()
    if not result or result.returncode != 0:
        return set()
    mount_ids = set()
    for raw_value in (result.stdout or "").splitlines():
        raw_value = raw_value.strip()
        if ":" not in raw_value:
            continue
        major_hex, minor_hex = raw_value.split(":", 1)
        try:
            mount_ids.add(f"{int(major_hex, 16)}:{int(minor_hex, 16)}")
        except ValueError:
            continue
    return mount_ids


def _namespace_mount_references(device, *, proc_root="/proc", limit=5, mount_ids=None):
    device = (device or "").strip()
    if not device:
        return []
    if mount_ids is None:
        mount_ids = _device_mount_ids(device)
    mount_ids = set(mount_ids or [])
    references = []
    proc_path = Path(proc_root)
    if not proc_path.exists():
        return references
    for pid_dir in proc_path.iterdir():
        if not pid_dir.name.isdigit():
            continue
        mountinfo_path = pid_dir / "mountinfo"
        try:
            lines = mountinfo_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            left, separator, right = line.partition(" - ")
            if not separator:
                continue
            left_parts = left.split()
            right_parts = right.split()
            if len(left_parts) < 5 or len(right_parts) < 2:
                continue
            source = right_parts[1]
            if source != device and left_parts[2] not in mount_ids:
                continue
            references.append(
                {
                    "pid": pid_dir.name,
                    "command": _read_proc_text(pid_dir / "comm") or "process",
                    "mountpoint": left_parts[4].replace("\\040", " "),
                    "fstype": right_parts[0],
                }
            )
            if len(references) >= limit:
                return references
    return references


def _mounted_device_error(device, *, host_mountpoints=None, references=None):
    if host_mountpoints is None:
        host_mountpoints = _device_host_mountpoints(device)
    if host_mountpoints:
        locations = ", ".join(host_mountpoints)
        return f"{device} is mounted at {locations}. Unmount it before formatting."
    if references is None:
        references = _namespace_mount_references(device)
    if references:
        details = ", ".join(
            f"{item['command']} pid {item['pid']} at {item['mountpoint']}"
            for item in references
        )
        return f"{device} is mounted in another process namespace ({details}). Close that app or container, or enable the advanced format option to lazy unmount stuck namespaces first."
    return f"{device} is mounted. Unmount it before formatting."


def _prepare_format_target(device, *, sudo_password="", force_namespace_unmount=False):
    host_mountpoints = _device_host_mountpoints(device)
    if host_mountpoints:
        raise ProcessControlError(_mounted_device_error(device, host_mountpoints=host_mountpoints, references=[]))
    references = _namespace_mount_references(device)
    if not references:
        return
    if not force_namespace_unmount:
        raise ProcessControlError(_mounted_device_error(device, host_mountpoints=[], references=references))
    _unmount_namespace_references(device, sudo_password=sudo_password, lazy=True)
    references = _namespace_mount_references(device)
    if references:
        raise ProcessControlError(_mounted_device_error(device, host_mountpoints=[], references=references))


def _unmount_namespace_references(device, *, sudo_password="", lazy=False):
    references = _namespace_mount_references(device)
    errors = []
    for item in references:
        command = ["nsenter", "--target", item["pid"], "--mount", "umount"]
        if lazy:
            command.append("-l")
        command.append(item["mountpoint"])
        try:
            _run_host_command(command, sudo_password=sudo_password)
        except ProcessControlError as exc:
            refreshed = _namespace_mount_references(device)
            if not any(ref["pid"] == item["pid"] and ref["mountpoint"] == item["mountpoint"] for ref in refreshed):
                continue
            errors.append(f"{item['command']} pid {item['pid']} at {item['mountpoint']}: {_command_error_text(exc)}")
    if errors:
        raise ProcessControlError("Could not unmount every namespace reference. " + " ".join(errors))
    return len(references)


def _volume_key_from_parts(*, uuid="", label="", serial="", model="", device=""):
    uuid = (uuid or "").strip()
    label = (label or "").strip()
    serial = (serial or "").strip()
    model = (model or "").strip()
    device = (device or "").strip()
    if uuid:
        return f"uuid:{uuid}"
    if serial:
        return f"serial:{serial}"
    if label and model:
        return f"label-model:{label}:{model}"
    if label:
        return f"label:{label}"
    return f"device:{device}"


def _volume_key(item):
    return _volume_key_from_parts(
        uuid=item.get("uuid") or "",
        label=item.get("label") or "",
        serial=item.get("serial") or "",
        model=item.get("model") or "",
        device=item.get("device") or "",
    )


def _identity_label(item):
    return item.get("model") or item.get("label") or item.get("device") or item.get("name") or "Block volume"


def _preference_map():
    return {preference.volume_key: preference for preference in VolumeMountPreference.objects.all()}


def _attach_mount_preferences(items, preferences):
    for item in items:
        item["volume_key"] = _volume_key(item)
        item["identity_label"] = _identity_label(item)
        preference = preferences.get(item["volume_key"])
        item["suggested_mountpoint"] = preference.mountpoint if preference else ""
    return items


def _attach_namespace_references(items):
    for item in items:
        device = item.get("device") or ""
        item["namespace_mounts"] = _namespace_mount_references(device, limit=3) if device.startswith("/dev/") else []
        item["has_namespace_mounts"] = bool(item["namespace_mounts"])
        if item["has_namespace_mounts"]:
            item["status_label"] = "Held by app"
    return items


def _unmounted_score(item):
    return sum(
        [
            bool(item.get("uuid")) * 8,
            bool(item.get("serial")) * 6,
            bool(item.get("model")) * 4,
            bool(item.get("fstype")) * 3,
            bool(item.get("label")) * 2,
            item.get("size_gb") is not None,
            item.get("fs_percent") is not None,
            not bool(item.get("mountpoint")),
        ]
    )


def _dedupe_unmounted_items(items):
    deduped = {}
    for item in items:
        key = _volume_key(item)
        existing = deduped.get(key)
        if not existing or _unmounted_score(item) > _unmounted_score(existing):
            deduped[key] = item
    return list(deduped.values())


def _mounted_score(item):
    return sum(
        [
            bool(item.get("uuid")) * 8,
            bool(item.get("model")) * 4,
            bool(item.get("fstype")) * 3,
            bool(item.get("label")) * 2,
            item.get("percent") is not None,
            item.get("size_gb") is not None,
        ]
    )


def _dedupe_mounted_items(items):
    deduped = {}
    for item in items:
        key = (item.get("device") or "", item.get("mountpoint") or "")
        existing = deduped.get(key)
        if not existing or _mounted_score(item) > _mounted_score(existing):
            deduped[key] = item
    return list(deduped.values())


def remember_mount_preference(*, device="", uuid="", label="", model="", serial="", mountpoint=""):
    target = normalize_host_path(mountpoint)
    volume_key = _volume_key_from_parts(uuid=uuid, label=label, serial=serial, model=model, device=device)
    VolumeMountPreference.objects.update_or_create(
        volume_key=volume_key,
        defaults={
            "device": (device or "").strip(),
            "uuid": (uuid or "").strip(),
            "label": (label or "").strip(),
            "model": (model or "").strip(),
            "serial": (serial or "").strip(),
            "mountpoint": target,
            "last_mounted_at": timezone.now(),
        },
    )


def list_volumes():
    disk_device_entries = _disk_device_entries()
    mounted_by_path = {item["mountpoint"]: item for item in disk_device_entries if item.get("is_mounted")}
    preferences = _preference_map()
    mounted_items = []
    unmounted_items = []
    seen_mounts = set()
    seen_devices = set()
    seen_volume_keys = set()

    for row in _lsblk_rows():
        if not _device_is_candidate(row):
            continue
        device = row.get("path") or row.get("name") or ""
        mountpoints = _as_list(row.get("mountpoints"))
        fs_used = _int_or_none(row.get("fsused"))
        fs_avail = _int_or_none(row.get("fsavail"))
        fs_percent = _percent_or_none(row.get("fsuse%"))
        size_bytes = _int_or_none(row.get("size"))
        base = {
            "device": device,
            "name": os.path.basename(device),
            "type": row.get("type") or "",
            "fstype": row.get("fstype") or "",
            "label": row.get("label") or "",
            "uuid": row.get("uuid") or "",
            "size_gb": _gb(size_bytes) if size_bytes is not None else None,
            "model": " ".join(part for part in [row.get("vendor") or "", row.get("model") or ""] if part).strip(),
            "serial": row.get("serial") or "",
            "transport": row.get("tran") or "",
            "removable": _truthy(row.get("rm")),
            "readonly": _truthy(row.get("ro")),
            "hotplug": _truthy(row.get("hotplug")),
            "state": row.get("state") or "",
            "fs_used_gb": _gb(fs_used) if fs_used is not None else None,
            "fs_avail_gb": _gb(fs_avail) if fs_avail is not None else None,
            "fs_percent": fs_percent,
        }
        seen_devices.add(device)
        seen_volume_keys.add(_volume_key(base))
        if mountpoints:
            for mountpoint in dict.fromkeys(os.path.normpath(item) for item in mountpoints):
                host_mountpoint = os.path.normpath(mountpoint)
                usage = mounted_by_path.get(host_mountpoint) or _usage_for_mountpoint(host_mountpoint)
                mounted_items.append(
                    {
                        **base,
                        **usage,
                        "mountpoint": host_mountpoint,
                        "is_mounted": True,
                        "status_label": "Mounted",
                    }
                )
                seen_mounts.add(host_mountpoint)
        elif base["type"] != "disk" or base["fstype"]:
            unmounted_items.append(
                {
                    **base,
                    "mountpoint": "",
                    "is_mounted": False,
                    "status_label": "Unmounted",
                }
            )

    for mountpoint, item in mounted_by_path.items():
        if mountpoint in seen_mounts:
            continue
        mounted_items.append(
            {
                **item,
                "name": os.path.basename(item.get("device") or ""),
                "label": "",
                "uuid": "",
                "size_gb": item.get("total_gb"),
                "model": "",
                "serial": "",
                "transport": "",
                "removable": False,
                "readonly": False,
                "hotplug": False,
                "state": "",
                "fs_used_gb": None,
                "fs_avail_gb": None,
                "fs_percent": None,
            }
        )

    for item in disk_device_entries:
        if item.get("is_mounted"):
            continue
        device = item.get("device") or ""
        fallback_item = {
            **item,
            "name": os.path.basename(device),
            "label": item.get("label") or "",
            "uuid": item.get("uuid") or "",
            "size_gb": item.get("total_gb"),
            "model": item.get("model") or "",
            "serial": item.get("serial") or "",
            "transport": item.get("transport") or "",
            "removable": False,
            "readonly": False,
            "hotplug": False,
            "state": "",
            "fs_used_gb": item.get("used_gb"),
            "fs_avail_gb": item.get("free_gb"),
            "fs_percent": item.get("percent"),
        }
        if device in seen_devices or _volume_key(fallback_item) in seen_volume_keys:
            continue
        unmounted_items.append(fallback_item)

    mounted_items = _dedupe_mounted_items(mounted_items)
    _attach_mount_preferences(mounted_items, preferences)
    unmounted_items = _attach_mount_preferences(_dedupe_unmounted_items(unmounted_items), preferences)
    _attach_namespace_references(unmounted_items)
    mounted_items.sort(key=lambda item: (item.get("mountpoint") != "/", item.get("mountpoint") or "", item.get("device") or ""))
    unmounted_items.sort(key=lambda item: (item.get("device") or ""))
    return {
        "mounted": mounted_items,
        "unmounted": unmounted_items,
        "mounted_count": len(mounted_items),
        "unmounted_count": len(unmounted_items),
        "seen_devices": seen_devices,
    }


def _validate_mount_source(device):
    device = (device or "").strip()
    if not device:
        raise ProcessControlError("Select a volume to mount.")
    if device.startswith("/dev/") or device.startswith("UUID=") or device.startswith("LABEL="):
        return device
    raise ProcessControlError("Only /dev, UUID=, or LABEL= mount sources are allowed.")


def _validate_block_device(device):
    device = (device or "").strip()
    if not device:
        raise ProcessControlError("Select a volume.")
    if not device.startswith("/dev/"):
        raise ProcessControlError("Only /dev block devices can be edited or formatted.")
    if device.startswith(SYSTEM_DEVICE_PREFIXES):
        raise ProcessControlError("System pseudo devices cannot be edited or formatted.")
    return device


def _validate_mount_options(options):
    options = (options or "").strip()
    if not options:
        return ""
    if any(char.isspace() for char in options):
        raise ProcessControlError("Mount options must be comma-separated without spaces.")
    return options


def _mount_fstype_candidates(fstype):
    fstype = _normalize_fstype(fstype)
    if fstype == "ntfs":
        return ["ntfs3", "ntfs", ""]
    return [fstype] if fstype else [""]


def _ntfs_mount_hint(error):
    detail = _command_error_text(error).lower()
    if "volume is dirty" in detail and "force" in detail:
        return " NTFS is marked dirty. If you need recovery access from Linux, retry with mount options 'ro,force'."
    if "$mftmirr does not match $mft" in detail or "ntfs is either inconsistent" in detail:
        return " NTFS metadata is inconsistent. If Windows repair is not available, retry read-only with options 'ro,force' to copy data."
    return ""


def mount_volume(device, mountpoint, *, fstype="", options="", sudo_password=""):
    source = _validate_mount_source(device)
    try:
        target = normalize_host_path(mountpoint)
    except ValueError as exc:
        raise ProcessControlError(str(exc)) from exc
    if target == "/":
        raise ProcessControlError("Mounting directly on / is not allowed.")
    opts = _validate_mount_options(options)
    try:
        _run_host_command(["mkdir", "-p", target], sudo_password=sudo_password)
        last_error = None
        for candidate_fstype in _mount_fstype_candidates(fstype):
            command = ["mount"]
            if candidate_fstype:
                command.extend(["-t", candidate_fstype])
            if opts:
                command.extend(["-o", opts])
            command.extend([source, target])
            try:
                _run_host_command(command, sudo_password=sudo_password)
            except ProcessControlError as exc:
                last_error = exc
                continue
            break
        else:
            raise last_error or ProcessControlError("Mount command failed.")
    except ProcessControlError as exc:
        raise ProcessControlError(f"{_format_action_error('Mount', exc, sudo_password=sudo_password)}{_ntfs_mount_hint(exc)}") from exc
    return VolumeActionResult(True, f"Mounted {source} on {target}.")


def unmount_volume(target, *, device="", sudo_password="", force=False):
    raw_target = (target or "").strip()
    if not raw_target:
        raise ProcessControlError("Select a mounted volume to unmount.")
    if raw_target == "/":
        raise ProcessControlError("Unmounting / is not allowed.")
    if not (raw_target.startswith("/") or raw_target.startswith("/dev/")):
        raise ProcessControlError("Unmount target must be a mount path or /dev device.")
    if raw_target.startswith("/dev/"):
        target = raw_target
    else:
        try:
            target = normalize_host_path(raw_target)
        except ValueError as exc:
            raise ProcessControlError(str(exc)) from exc
    command = ["umount", target]
    if force:
        command = ["umount", "-l", target]
    main_unmounted = False
    try:
        _run_host_command(command, sudo_password=sudo_password)
        main_unmounted = True
    except ProcessControlError as exc:
        if not force:
            raise ProcessControlError(_format_action_error("Unmount", exc, sudo_password=sudo_password)) from exc
        if "not mounted" not in _command_error_text(exc).lower():
            raise ProcessControlError(_format_action_error("Unmount", exc, sudo_password=sudo_password)) from exc

    namespace_count = 0
    if force and device:
        namespace_count = _unmount_namespace_references(device, sudo_password=sudo_password, lazy=True)
    elif device and _namespace_mount_references(device):
        raise ProcessControlError(f"Unmounted {target}, but {device} is still mounted in another process namespace. Use forced unmount before formatting.")

    if namespace_count:
        return VolumeActionResult(True, f"Unmounted {target} and {namespace_count} namespace reference(s).")
    if main_unmounted:
        return VolumeActionResult(True, f"Unmounted {target}.")
    return VolumeActionResult(True, f"No active mount found for {target}.")


def release_namespace_mounts(device, *, sudo_password=""):
    device = _validate_block_device(device)
    host_mountpoints = _device_host_mountpoints(device)
    if host_mountpoints:
        raise ProcessControlError(_mounted_device_error(device, host_mountpoints=host_mountpoints, references=[]))
    references = _namespace_mount_references(device)
    if not references:
        return VolumeActionResult(True, f"No stuck namespace mounts found for {device}.")
    namespace_count = _unmount_namespace_references(device, sudo_password=sudo_password, lazy=True)
    return VolumeActionResult(True, f"Released {namespace_count} stuck namespace mount(s) for {device}.")


def update_volume_label(device, label, *, fstype="", sudo_password=""):
    device = _validate_block_device(device)
    fstype = _normalize_fstype(fstype)
    if not fstype:
        row = _row_for_device(device)
        fstype = _normalize_fstype((row or {}).get("fstype"))
    label = _validate_label_for_fstype(label, fstype)
    command_prefix = LABEL_COMMANDS.get(fstype)
    if not command_prefix:
        supported = ", ".join(sorted(LABEL_COMMANDS))
        raise ProcessControlError(f"Changing labels is not supported for filesystem '{fstype or 'unknown'}'. Supported filesystems: {supported}.")
    if fstype == "xfs":
        command = [*command_prefix, label, device]
    else:
        command = [*command_prefix, device, label]
    try:
        _run_host_command(command, sudo_password=sudo_password)
    except ProcessControlError as exc:
        raise ProcessControlError(_format_action_error("Update label", exc, sudo_password=sudo_password)) from exc
    return VolumeActionResult(True, f"Updated label for {device}.")


def format_volume(device, fstype, *, label="", confirm_text="", confirm_device="", sudo_password="", force_namespace_unmount=False):
    device = _validate_block_device(device)
    fstype = _normalize_fstype(fstype)
    label = _validate_label_for_fstype(label, fstype)
    if confirm_text != "FORMAT" or confirm_device != device:
        raise ProcessControlError("Formatting was not confirmed. Type FORMAT and the exact device path before trying again.")
    _prepare_format_target(device, sudo_password=sudo_password, force_namespace_unmount=force_namespace_unmount)
    format_config = SUPPORTED_FORMATS.get(fstype)
    if not format_config:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        raise ProcessControlError(f"Formatting as '{fstype or 'unknown'}' is not supported. Supported filesystems: {supported}.")
    command = [format_config["command"], *format_config["force_args"]]
    if label:
        command.extend([format_config["label_flag"], label])
    command.append(device)
    try:
        _run_host_command(command, sudo_password=sudo_password, timeout_seconds=FORMAT_TIMEOUT_SECONDS)
    except ProcessControlError as exc:
        detail = _command_error_text(exc).lower()
        if "apparently in use" in detail or "is mounted" in detail or "contains a mounted filesystem" in detail:
            raise ProcessControlError(f"Format failed: {device} is in use or mounted. Unmount it first and close any terminal or file browser using it.") from exc
        raise ProcessControlError(_format_action_error("Format", exc, sudo_password=sudo_password)) from exc
    return VolumeActionResult(True, f"Formatted {device} as {fstype}.")


def _operation_initial_summary(action, device):
    if action == "format":
        return f"Formatting {device}."
    if action == "label":
        return f"Updating label for {device}."
    return f"Running volume operation on {device}."


def create_volume_operation(*, action, device, fstype="", label=""):
    device = _validate_block_device(device)
    action = (action or "").strip()
    fstype = _normalize_fstype(fstype)
    label = _validate_label_for_fstype(label, fstype)
    if action not in dict(VolumeOperation.ACTION_CHOICES):
        raise ProcessControlError("Unknown volume operation.")
    return VolumeOperation.objects.create(
        action=action,
        device=device,
        fstype=fstype,
        label=label,
        status="running",
        summary=_operation_initial_summary(action, device),
    )


def start_background_volume_operation(*, action, device, fstype="", label="", sudo_password="", confirm_text="", confirm_device="", force_namespace_unmount=False):
    if action == "format":
        if confirm_text != "FORMAT" or confirm_device != device:
            raise ProcessControlError("Formatting was not confirmed. Type FORMAT and the exact device path before trying again.")
        device = _validate_block_device(device)
        _prepare_format_target(device, sudo_password=sudo_password, force_namespace_unmount=force_namespace_unmount)
        if _normalize_fstype(fstype) not in SUPPORTED_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_FORMATS))
            raise ProcessControlError(f"Formatting as '{fstype or 'unknown'}' is not supported. Supported filesystems: {supported}.")
        _validate_label_for_fstype(label, fstype)
    operation = create_volume_operation(action=action, device=device, fstype=fstype, label=label)
    command = [sys.executable, "manage.py", "run_volume_operation", str(operation.id)]
    env = os.environ.copy()
    if sudo_password:
        env["VOLUME_OPERATION_SUDO_PASSWORD"] = sudo_password
    try:
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parent.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    except OSError as exc:
        operation.status = "failed"
        operation.summary = f"Volume operation could not start: {exc}"
        operation.log_output = str(exc)
        operation.finished_at = timezone.now()
        operation.command_line = _format_command(command)
        operation.save(update_fields=["status", "summary", "log_output", "finished_at", "command_line"])
        raise ProcessControlError(operation.summary) from exc
    operation.process_pid = process.pid
    operation.runner_label = _runner_label()
    operation.command_line = _format_command(command)
    operation.save(update_fields=["process_pid", "runner_label", "command_line"])
    return operation


def execute_volume_operation(operation):
    operation.status = "running"
    operation.runner_label = _runner_label()
    operation.process_pid = os.getpid()
    operation.summary = _operation_initial_summary(operation.action, operation.device)
    operation.save(update_fields=["status", "runner_label", "process_pid", "summary"])
    sudo_password = os.getenv("VOLUME_OPERATION_SUDO_PASSWORD", "")
    started_line = f"Started {operation.get_action_display().lower()} on {operation.device}."
    try:
        if operation.action == "label":
            result = update_volume_label(operation.device, operation.label, fstype=operation.fstype, sudo_password=sudo_password)
        elif operation.action == "format":
            result = format_volume(
                operation.device,
                operation.fstype,
                label=operation.label,
                confirm_text="FORMAT",
                confirm_device=operation.device,
                sudo_password=sudo_password,
            )
        else:
            raise ProcessControlError("Unknown volume operation.")
    except ProcessControlError as exc:
        operation.status = "failed"
        operation.summary = str(exc)
        operation.log_output = f"{started_line}\n{exc}"
    else:
        operation.status = "success"
        operation.summary = result.message
        operation.log_output = f"{started_line}\n{result.message}"
    operation.finished_at = timezone.now()
    operation.save(update_fields=["status", "summary", "log_output", "finished_at"])
    return operation
