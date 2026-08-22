import mimetypes
import os
import stat
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from volumes_app.path_browser import hostfs_path, normalize_host_path


INFO_BATCH_SIZE = 300
INFO_SESSION_TTL_SECONDS = 15 * 60
_INFO_SESSIONS = {}


def start_file_information(paths):
    normalized_paths = _normalize_paths(paths)
    session_id = uuid.uuid4().hex
    now = time.monotonic()
    session = {
        "id": session_id,
        "created_at": now,
        "updated_at": now,
        "paths": normalized_paths,
        "items": [],
        "queue": deque(),
        "aggregate": _empty_aggregate(),
        "errors": [],
        "complete": False,
    }
    _INFO_SESSIONS[session_id] = session
    _prune_sessions(now)

    for path in normalized_paths:
        item = _path_metadata(path)
        session["items"].append(item)
        _add_top_level_item(session["aggregate"], item)
        if item["kind"] == "folder" and item["scan_available"]:
            session["queue"].append((path, 0))
        elif item.get("error"):
            session["errors"].append({"path": path, "message": item["error"]})

    return continue_file_information(session_id)


def continue_file_information(session_id):
    session = _INFO_SESSIONS.get(session_id)
    if not session:
        raise ValueError("Information session not found.")

    processed = 0
    while session["queue"] and processed < INFO_BATCH_SIZE:
        current_path, offset = session["queue"].popleft()
        absolute_path = hostfs_path(current_path)
        try:
            with os.scandir(absolute_path) as entries:
                for index, entry in enumerate(entries):
                    if index < offset:
                        continue
                    child_path = os.path.join(current_path, entry.name).replace("\\", "/")
                    if not child_path.startswith("/"):
                        child_path = f"/{child_path}"
                    child_info = _entry_scan_metadata(entry, child_path)
                    _add_scanned_item(session["aggregate"], child_info)
                    processed += 1
                    if child_info["kind"] == "folder" and child_info["scan_available"]:
                        session["queue"].append((child_path, 0))
                    if processed >= INFO_BATCH_SIZE:
                        session["queue"].appendleft((current_path, index + 1))
                        break
        except OSError as exc:
            session["aggregate"]["unreadable_directories"] += 1
            session["errors"].append({"path": current_path, "message": str(exc)})

    session["complete"] = not session["queue"]
    session["updated_at"] = time.monotonic()
    return _session_payload(session)


def _normalize_paths(paths):
    normalized = []
    seen = set()
    for raw_path in paths:
        path = normalize_host_path(raw_path)
        if path in seen:
            continue
        normalized.append(path)
        seen.add(path)
    if not normalized:
        raise ValueError("Choose at least one file or folder.")
    return normalized


def _path_metadata(path):
    absolute_path = hostfs_path(path)
    try:
        stat_result = os.lstat(absolute_path)
    except OSError as exc:
        return _missing_item(path, str(exc))
    return _metadata_from_stat(path, os.path.basename(path.rstrip("/")) or "/", stat_result)


def _entry_scan_metadata(entry, path):
    try:
        stat_result = entry.stat(follow_symlinks=False)
    except OSError as exc:
        return _missing_item(path, str(exc))
    return _metadata_from_stat(path, entry.name, stat_result)


def _metadata_from_stat(path, name, stat_result):
    mode = stat_result.st_mode
    is_dir = stat.S_ISDIR(mode)
    is_file = stat.S_ISREG(mode)
    is_symlink = stat.S_ISLNK(mode)
    content_type = "" if is_dir else (mimetypes.guess_type(name or path)[0] or "")
    return {
        "path": path,
        "name": name,
        "kind": "folder" if is_dir else "file",
        "is_file": is_file,
        "is_dir": is_dir,
        "is_symlink": is_symlink,
        "scan_available": is_dir and not is_symlink,
        "size_bytes": stat_result.st_size if is_file else None,
        "allocated_bytes": getattr(stat_result, "st_blocks", 0) * 512,
        "content_type": content_type,
        "permissions": stat.filemode(mode),
        "mode_octal": oct(stat.S_IMODE(mode)),
        "uid": stat_result.st_uid,
        "gid": stat_result.st_gid,
        "inode": stat_result.st_ino,
        "device": stat_result.st_dev,
        "links": stat_result.st_nlink,
        "modified_at": _timestamp(stat_result.st_mtime),
        "accessed_at": _timestamp(stat_result.st_atime),
        "changed_at": _timestamp(stat_result.st_ctime),
        "error": "",
    }


def _missing_item(path, message):
    return {
        "path": path,
        "name": os.path.basename(path.rstrip("/")) or "/",
        "kind": "unknown",
        "is_file": False,
        "is_dir": False,
        "is_symlink": False,
        "scan_available": False,
        "size_bytes": None,
        "allocated_bytes": 0,
        "content_type": "",
        "permissions": "",
        "mode_octal": "",
        "uid": None,
        "gid": None,
        "inode": None,
        "device": None,
        "links": None,
        "modified_at": "",
        "accessed_at": "",
        "changed_at": "",
        "error": message,
    }


def _empty_aggregate():
    return {
        "selected_count": 0,
        "selected_files": 0,
        "selected_folders": 0,
        "files": 0,
        "folders": 0,
        "symlinks": 0,
        "size_bytes": 0,
        "allocated_bytes": 0,
        "unreadable_directories": 0,
        "scanned_entries": 0,
    }


def _add_top_level_item(aggregate, item):
    aggregate["selected_count"] += 1
    if item["kind"] == "folder":
        aggregate["selected_folders"] += 1
        aggregate["folders"] += 1
    elif item["kind"] == "file":
        aggregate["selected_files"] += 1
        aggregate["files"] += 1
    if item["is_symlink"]:
        aggregate["symlinks"] += 1
    if item["size_bytes"]:
        aggregate["size_bytes"] += item["size_bytes"]
    aggregate["allocated_bytes"] += item["allocated_bytes"] or 0


def _add_scanned_item(aggregate, item):
    aggregate["scanned_entries"] += 1
    if item["kind"] == "folder":
        aggregate["folders"] += 1
    elif item["kind"] == "file":
        aggregate["files"] += 1
    if item["is_symlink"]:
        aggregate["symlinks"] += 1
    if item["size_bytes"]:
        aggregate["size_bytes"] += item["size_bytes"]
    aggregate["allocated_bytes"] += item["allocated_bytes"] or 0


def _session_payload(session):
    return {
        "ok": True,
        "session_id": session["id"],
        "complete": session["complete"],
        "items": session["items"],
        "aggregate": session["aggregate"],
        "errors": session["errors"][-25:],
    }


def _timestamp(value):
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _prune_sessions(now):
    expired = [
        session_id
        for session_id, session in _INFO_SESSIONS.items()
        if now - session["updated_at"] > INFO_SESSION_TTL_SECONDS
    ]
    for session_id in expired:
        _INFO_SESSIONS.pop(session_id, None)
