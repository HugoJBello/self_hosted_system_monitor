import os


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
    normalized_path = normalize_host_path(host_path)
    try:
        absolute_path = hostfs_path(normalized_path)
    except ValueError:
        return []
    if not os.path.isdir(absolute_path):
        return []

    children = []
    try:
        entries = sorted(os.scandir(absolute_path), key=lambda entry: entry.name.lower())
    except PermissionError:
        return []

    mounted_paths = _mounted_host_paths()
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        relative_path = os.path.join(normalized_path, entry.name).replace("\\", "/")
        if relative_path in EXCLUDED_BROWSER_PATHS:
            continue
        relative_path = relative_path if relative_path.startswith("/") else f"/{relative_path}"
        children.append(
            {
                "path": relative_path,
                "name": entry.name,
                "is_mounted": relative_path in mounted_paths,
            }
        )
    return children


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
