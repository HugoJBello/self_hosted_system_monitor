import os
import shutil
import subprocess
from dataclasses import dataclass

from file_manager_app.browser import file_entry_for_path
from volumes_app import path_browser
from volumes_app.path_browser import hostfs_path, normalize_host_path


SEARCH_RESULT_LIMIT = 500
SEARCH_TIMEOUT_SECONDS = 20


@dataclass
class FileSearchResult:
    items: list
    truncated: bool = False
    timed_out: bool = False
    error: str = ""


def search_file_manager(root_path, query, *, recursive=True):
    root_path = normalize_host_path(root_path)
    absolute_root = hostfs_path(root_path)
    if not os.path.isdir(absolute_root):
        raise ValueError("Choose an existing folder to search.")
    query = (query or "").strip()
    if not query:
        return FileSearchResult([])
    if "\0" in query:
        raise ValueError("Search text contains an invalid character.")
    executable = shutil.which("find")
    if not executable:
        raise RuntimeError("The find command is not available on the server.")

    command = [executable, absolute_root]
    if not recursive:
        command.extend(["-maxdepth", "1"])
    command.extend(["-iname", f"*{query}*", "-print0"])
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        output, _ = process.communicate(timeout=SEARCH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        raw_paths = output.split(b"\0") if output else []
        return FileSearchResult(_metadata_for_results(_decode_paths(raw_paths[:SEARCH_RESULT_LIMIT])), timed_out=True)
    raw_paths = output.split(b"\0") if output else []
    truncated = len(raw_paths) > SEARCH_RESULT_LIMIT
    return FileSearchResult(
        _metadata_for_results(_decode_paths(raw_paths[:SEARCH_RESULT_LIMIT])),
        truncated=truncated,
    )


def _decode_paths(raw_paths):
    paths = []
    for raw_path in raw_paths:
        if not raw_path:
            continue
        try:
            paths.append(raw_path.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return paths


def _metadata_for_results(raw_paths):
    items = []
    for absolute_path in raw_paths:
        normalized_path = _host_path_from_absolute(absolute_path)
        if not normalized_path:
            continue
        item = file_entry_for_path(normalized_path)
        if item:
            item["browse_path"] = normalized_path if item.get("is_dir") else os.path.dirname(normalized_path.rstrip("/")) or "/"
            items.append(item)
    return items


def _host_path_from_absolute(absolute_path):
    root = os.path.normpath(path_browser.HOST_ROOT_PATH)
    absolute_path = os.path.normpath(absolute_path)
    if root == "/":
        return normalize_host_path(absolute_path)
    try:
        relative = os.path.relpath(absolute_path, root)
    except ValueError:
        return ""
    if relative == ".." or relative.startswith(f"..{os.sep}"):
        return ""
    return normalize_host_path("/" + relative.replace(os.sep, "/"))
