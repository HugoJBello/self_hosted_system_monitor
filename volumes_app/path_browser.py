import os
import pwd
import grp
import stat
from datetime import datetime, timezone


HOST_ROOT_PATH = os.getenv("MONITOR_ROOT_PATH", "/")
MOUNT_SENSITIVE_ROOTS = ("/media", "/mnt", "/run/media")
BROWSER_ROOTS = [
    "/home",
    "/media",
    "/mnt",
    "/srv",
    "/opt",
    "/var/backups",
]
EXCLUDED_BROWSER_PATHS = {
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/tmp",
    "/var/lib/docker",
}


def hostfs_path(host_path):
    normalized = os.path.normpath(host_path or "/")
    if not normalized.startswith("/"):
        raise ValueError("Host paths must be absolute.")
    if normalized.startswith("/hostfs"):
        raise ValueError("Use host paths like /home/user, not /hostfs-prefixed paths.")
    if HOST_ROOT_PATH == "/":
        return normalized
    return os.path.join(HOST_ROOT_PATH, normalized.lstrip("/"))


def normalize_host_path(host_path):
    normalized = os.path.normpath(host_path or "/")
    if normalized == ".":
        normalized = "/"
    if not normalized.startswith("/"):
        raise ValueError("Host paths must be absolute.")
    if normalized in EXCLUDED_BROWSER_PATHS:
        raise ValueError("This host path is not selectable.")
    return normalized


def _mounted_host_paths():
    procfs_path = os.getenv("MONITOR_PROCFS_PATH", "/proc")
    mounts_file = os.path.join(procfs_path, "mounts")
    mounts = set()
    try:
        with open(mounts_file, encoding="utf-8") as handle:
            for raw_line in handle:
                parts = raw_line.split()
                if len(parts) < 2:
                    continue
                mount_path = os.path.normpath(parts[1].replace("\\040", " "))
                if HOST_ROOT_PATH != "/" and (mount_path == HOST_ROOT_PATH or mount_path.startswith(f"{HOST_ROOT_PATH}/")):
                    mount_path = os.path.normpath("/" + os.path.relpath(mount_path, HOST_ROOT_PATH).lstrip("./"))
                mounts.add(mount_path)
    except OSError:
        return set()
    return mounts


def list_browser_roots():
    mounted_paths = _mounted_host_paths()
    roots = []
    seen_paths = set()
    for root_path in BROWSER_ROOTS:
        try:
            absolute_path = hostfs_path(root_path)
        except ValueError:
            continue
        if os.path.isdir(absolute_path):
            roots.append({"path": root_path, "name": root_path.strip("/") or "/", "is_mounted": root_path in mounted_paths})
            seen_paths.add(root_path)
    for mount_path in sorted(mounted_paths):
        if not mount_path.startswith(MOUNT_SENSITIVE_ROOTS):
            continue
        if mount_path in seen_paths:
            continue
        try:
            absolute_path = hostfs_path(mount_path)
        except ValueError:
            continue
        if os.path.isdir(absolute_path):
            roots.append({"path": mount_path, "name": f"Mounted: {mount_path}", "is_mounted": True})
            seen_paths.add(mount_path)
    return roots


def list_directory_children(host_path):
    return [
        {
            "path": item["path"],
            "name": item["name"],
            "is_mounted": item["is_mounted"],
        }
        for item in list_directory_entries(host_path, include_files=False)
    ]


def list_directory_entries(host_path, *, include_files=False):
    normalized_path = normalize_host_path(host_path)
    try:
        absolute_path = hostfs_path(normalized_path)
    except ValueError:
        return []
    if not os.path.isdir(absolute_path):
        return []

    children = []
    try:
        entries = sorted(
            os.scandir(absolute_path),
            key=lambda entry: (not entry.is_dir(follow_symlinks=False), entry.name.lower()),
        )
    except PermissionError:
        return []

    mounted_paths = _mounted_host_paths()
    for entry in entries:
        is_dir = entry.is_dir(follow_symlinks=False)
        if not is_dir and not include_files:
            continue
        relative_path = os.path.join(normalized_path, entry.name).replace("\\", "/")
        if relative_path in EXCLUDED_BROWSER_PATHS:
            continue
        relative_path = relative_path if relative_path.startswith("/") else f"/{relative_path}"
        children.append(_entry_metadata(entry, relative_path, is_mounted=relative_path in mounted_paths))
    return children


def _entry_metadata(entry, host_path, *, is_mounted=False):
    try:
        stat_result = entry.stat(follow_symlinks=False)
    except OSError:
        stat_result = None

    mode = stat_result.st_mode if stat_result else 0
    is_dir = entry.is_dir(follow_symlinks=False)
    is_symlink = entry.is_symlink()
    modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat() if stat_result else ""

    return {
        "path": host_path,
        "name": entry.name,
        "kind": "folder" if is_dir else "file",
        "is_dir": is_dir,
        "is_file": not is_dir,
        "is_symlink": is_symlink,
        "is_mounted": is_mounted,
        "size_bytes": stat_result.st_size if stat_result and not is_dir else None,
        "modified_at": modified_at,
        "permissions": stat.filemode(mode) if stat_result else "",
        "owner": _owner_name(stat_result.st_uid) if stat_result else "",
        "group": _group_name(stat_result.st_gid) if stat_result else "",
    }


def _owner_name(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _group_name(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def create_directory(parent_path, folder_name):
    parent_path = normalize_host_path(parent_path)
    folder_name = (folder_name or "").strip()
    if not folder_name:
        raise ValueError("Folder name is required.")
    if folder_name in {".", ".."} or "/" in folder_name or "\\" in folder_name or "\0" in folder_name:
        raise ValueError("Folder name cannot contain path separators.")
    if any(char in folder_name for char in ["\n", "\r"]):
        raise ValueError("Folder name cannot contain line breaks.")
    target_path = normalize_host_path(os.path.join(parent_path, folder_name))
    absolute_target = hostfs_path(target_path)
    if os.path.exists(absolute_target):
        raise ValueError("A file or folder with this name already exists.")
    try:
        os.makedirs(absolute_target, exist_ok=False)
    except PermissionError as exc:
        raise ValueError("Permission denied while creating the folder.") from exc
    except OSError as exc:
        raise ValueError(f"Could not create folder: {exc}") from exc
    return {
        "path": target_path,
        "name": folder_name,
        "is_mounted": target_path in _mounted_host_paths(),
    }
