import os
import re
import select
import shutil
import subprocess
import time
from dataclasses import dataclass

from django.utils import timezone

from file_manager_app.browser import file_entry_for_path
from file_manager_app.models import FileOperation, FileSearch
from volumes_app import path_browser
from volumes_app.path_browser import hostfs_path, normalize_host_path


SEARCH_RESULT_LIMIT = 500
SEARCH_TIMEOUT_OPTIONS = (10, 30, 60, 300)
SEARCH_DEFAULT_TIMEOUT = 30
SEARCH_READ_INTERVAL_SECONDS = 0.5
SEARCH_PROGRESS_INTERVAL_SECONDS = 1.5


@dataclass
class FileSearchResult:
    items: list
    truncated: bool = False
    timed_out: bool = False
    error: str = ""


def create_search_operation(root_path, query, *, recursive=True, timeout_seconds=SEARCH_DEFAULT_TIMEOUT, case_sensitive=False, use_regex=False):
    root_path = normalize_host_path(root_path or "/")
    absolute_root = hostfs_path(root_path)
    query = (query or "").strip()
    if not os.path.isdir(absolute_root):
        raise ValueError("Choose an existing folder to search.")
    if not query:
        raise ValueError("Enter a name or pattern to search for.")
    if "\0" in query:
        raise ValueError("Search text contains an invalid character.")
    if use_regex:
        try:
            re.compile(query, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
    if timeout_seconds in {"", "none", None, 0, "0"}:
        timeout_seconds = None
    else:
        try:
            timeout_seconds = int(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a valid search timeout.") from exc
        if timeout_seconds not in SEARCH_TIMEOUT_OPTIONS:
            raise ValueError("Choose a valid search timeout.")

    operation = FileOperation.objects.create(
        action="search",
        status="running",
        sources=[root_path],
        current_path=root_path,
        total_count=0,
        summary=f"Searching for '{query}'...",
        heartbeat_at=timezone.now(),
    )
    FileSearch.objects.create(
        operation=operation,
        root_path=root_path,
        query=query,
        recursive=bool(recursive),
        case_sensitive=bool(case_sensitive),
        use_regex=bool(use_regex),
        timeout_seconds=timeout_seconds,
    )
    return operation


def search_operation_url(operation):
    from django.urls import reverse

    return f"{reverse('monitor:file-manager-search')}?operation_id={operation.id}"


def search_result_items(search):
    items = []
    for path in search.result_paths or []:
        item = file_entry_for_path(path)
        if not item:
            continue
        item["browse_path"] = path if item.get("is_dir") else os.path.dirname(path.rstrip("/")) or "/"
        items.append(item)
    return items


def execute_search_operation(operation):
    from file_manager_app.services import _append_log, finalize_file_operation

    search = operation.search
    search.result_paths = []
    search.result_count = 0
    search.truncated = False
    search.timed_out = False
    search.save(update_fields=["result_paths", "result_count", "truncated", "timed_out"])
    executable = shutil.which("find")
    if not executable:
        finalize_file_operation(operation, "failed", "The find command is not available on the server.")
        return

    absolute_root = hostfs_path(search.root_path)
    command = [executable, absolute_root]
    if not search.recursive:
        command.extend(["-maxdepth", "1"])
    if not search.use_regex:
        command.extend(["-name" if search.case_sensitive else "-iname", f"*{search.query}*"])
    command.append("-print0")
    matcher = re.compile(search.query, 0 if search.case_sensitive else re.IGNORECASE) if search.use_regex else None
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    operation.process_pid = process.pid
    operation.runner_label = os.uname().nodename
    operation.heartbeat_at = timezone.now()
    _append_log(operation, f"Search started in {search.root_path} for '{search.query}'.")
    _append_log(operation, f"Mode: {'recursive' if search.recursive else 'current folder only'}; timeout: {search.timeout_label}.")
    operation.save(update_fields=["process_pid", "runner_label", "heartbeat_at", "log_output"])

    result_paths = []
    buffer = b""
    started_at = time.monotonic()
    last_progress_at = started_at
    timed_out = False
    stopped_status = ""

    try:
        while True:
            operation.refresh_from_db(fields=["status", "cancel_requested_at", "pause_requested_at"])
            if operation.cancel_requested_at:
                stopped_status = "cancelled"
                _terminate_process(process)
                break
            if operation.pause_requested_at:
                stopped_status = "paused"
                _terminate_process(process)
                break
            if search.timeout_seconds and time.monotonic() - started_at >= search.timeout_seconds:
                timed_out = True
                _terminate_process(process)
                break

            ready, _, _ = select.select([process.stdout], [], [], SEARCH_READ_INTERVAL_SECONDS)
            if ready:
                chunk = process.stdout.read(64 * 1024)
                if chunk:
                    buffer += chunk
                    complete, buffer = _split_null_terminated(buffer)
                    for raw_path in complete:
                        if len(result_paths) >= SEARCH_RESULT_LIMIT:
                            search.truncated = True
                            continue
                        decoded_path = _decode_path(raw_path)
                        if decoded_path and (not matcher or matcher.search(os.path.basename(decoded_path))):
                            result_paths.append(_host_path_from_absolute(decoded_path))
                elif process.poll() is not None:
                    break
            elif process.poll() is not None:
                break

            if time.monotonic() - last_progress_at >= SEARCH_PROGRESS_INTERVAL_SECONDS:
                _save_search_progress(operation, search, result_paths, _append_log)
                last_progress_at = time.monotonic()
        if buffer and len(result_paths) < SEARCH_RESULT_LIMIT:
            decoded_path = _decode_path(buffer)
            if decoded_path and (not matcher or matcher.search(os.path.basename(decoded_path))):
                result_paths.append(_host_path_from_absolute(decoded_path))
    finally:
        if process.stdout:
            process.stdout.close()
        if process.poll() is None:
            _terminate_process(process)

    search.result_paths = [path for path in result_paths if path]
    search.result_count = len(search.result_paths)
    search.timed_out = timed_out
    search.save(update_fields=["result_paths", "result_count", "truncated", "timed_out"])
    operation.processed_count = search.result_count
    operation.current_path = search.result_paths[-1] if search.result_paths else search.root_path
    if stopped_status == "cancelled":
        finalize_file_operation(operation, "cancelled", f"Search cancelled after finding {search.result_count} result(s).")
    elif stopped_status == "paused":
        operation.process_pid = None
        operation.status = "paused"
        operation.summary = f"Search paused after finding {search.result_count} result(s)."
        _append_log(operation, operation.summary)
        operation.save(update_fields=["process_pid", "status", "summary", "processed_count", "current_path", "log_output", "heartbeat_at"])
    elif timed_out:
        finalize_file_operation(operation, "success", f"Search timed out after finding {search.result_count} result(s). Narrow the search to continue.")
    else:
        finalize_file_operation(operation, "success", f"Search completed with {search.result_count} result(s).")


def _save_search_progress(operation, search, result_paths, append_log):
    operation.processed_count = len(result_paths)
    operation.current_path = result_paths[-1] if result_paths else search.root_path
    operation.summary = f"Searching... {len(result_paths)} result(s) found."
    operation.heartbeat_at = timezone.now()
    search.result_paths = result_paths
    search.result_count = len(result_paths)
    search.save(update_fields=["result_paths", "result_count"])
    append_log(operation, operation.summary)
    operation.save(update_fields=["processed_count", "current_path", "summary", "heartbeat_at", "log_output"])


def _split_null_terminated(buffer):
    parts = buffer.split(b"\0")
    return parts[:-1], parts[-1]


def _decode_path(raw_path):
    try:
        return raw_path.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _terminate_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _host_path_from_absolute(absolute_path):
    root = os.path.normpath(path_browser.HOST_ROOT_PATH)
    absolute_path = os.path.normpath(absolute_path)
    if root == "/":
        try:
            return normalize_host_path(absolute_path)
        except ValueError:
            return ""
    try:
        relative = os.path.relpath(absolute_path, root)
    except ValueError:
        return ""
    if relative == ".." or relative.startswith(f"..{os.sep}"):
        return ""
    try:
        return normalize_host_path("/" + relative.replace(os.sep, "/"))
    except ValueError:
        return ""


def search_file_manager(root_path, query, *, recursive=True):
    """Compatibility helper for callers that need a bounded synchronous search."""
    operation = create_search_operation(root_path, query, recursive=recursive)
    execute_search_operation(operation)
    operation.refresh_from_db()
    search = operation.search
    return FileSearchResult(
        search_result_items(search),
        truncated=search.truncated,
        timed_out=search.timed_out,
        error="" if operation.status == "success" else operation.summary,
    )
