import os
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.db import OperationalError
from django.utils import timezone

from file_manager_app.models import FileOperation
from volumes_app.path_browser import hostfs_path, normalize_host_path


FILE_OPERATION_LOG_LIMIT = 30000
FILE_OPERATION_HEARTBEAT_SECONDS = 5
DOWNLOAD_ARCHIVE_DIR_NAME = "file_manager_downloads"
UPLOAD_SESSION_DIR_NAME = "file_manager_uploads"
SQLITE_LOCK_RETRY_SECONDS = 0.2
SQLITE_LOCK_RETRY_ATTEMPTS = 5


@dataclass
class FileOperationResult:
    status: str
    summary: str


def _runner_label():
    return os.uname().nodename


def _with_db_retry(action, *, default=None):
    for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
        try:
            return action()
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt == SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                return default
            time.sleep(SQLITE_LOCK_RETRY_SECONDS)


def _append_log(operation, message):
    timestamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    operation.log_output = "\n".join([operation.log_output.strip(), line]).strip()[-FILE_OPERATION_LOG_LIMIT:]
    operation.heartbeat_at = timezone.now()


def _validated_sources(raw_sources):
    sources = []
    for source in raw_sources or []:
        normalized = normalize_host_path(str(source or ""))
        hostfs_path(normalized)
        sources.append(normalized)
    if not sources:
        raise ValueError("Select at least one item.")
    return sources


def _validated_destination(destination_path):
    destination = normalize_host_path(destination_path or "")
    absolute_destination = hostfs_path(destination)
    if not os.path.isdir(absolute_destination):
        raise ValueError("Choose an existing destination folder.")
    return destination


def create_file_operation(action, sources, *, destination_path="", conflict_policy="overwrite"):
    if action not in {"copy", "move", "delete", "download"}:
        raise ValueError("Unsupported file operation.")
    if conflict_policy not in {choice[0] for choice in FileOperation.CONFLICT_POLICY_CHOICES}:
        raise ValueError("Unsupported conflict policy.")
    if action not in {"copy", "move"}:
        conflict_policy = "overwrite"
    normalized_sources = _validated_sources(sources)
    destination = _validated_destination(destination_path) if action in {"copy", "move"} else ""
    operation = FileOperation.objects.create(
        action=action,
        status="running",
        sources=normalized_sources,
        destination_path=destination,
        conflict_policy=conflict_policy,
        total_count=len(normalized_sources),
        summary=f"{action.title()} operation queued for {len(normalized_sources)} item(s).",
        heartbeat_at=timezone.now(),
    )
    return operation


def start_background_file_operation(operation):
    if operation.status not in {"running", "paused", "failed", "cancelled"}:
        raise ValueError("This operation cannot be started.")
    operation.status = "running"
    operation.finished_at = None
    operation.cancel_requested_at = None
    operation.pause_requested_at = None
    operation.summary = f"{operation.get_action_display()} operation starting."
    operation.heartbeat_at = timezone.now()
    operation.save(update_fields=["status", "finished_at", "cancel_requested_at", "pause_requested_at", "summary", "heartbeat_at"])
    command = [sys.executable, "manage.py", "run_file_operation", str(operation.id)]
    subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return operation


def pause_file_operation(operation):
    if operation.status != "running":
        return False
    operation.pause_requested_at = timezone.now()
    operation.summary = "Pause requested. The operation will pause after the current item."
    operation.save(update_fields=["pause_requested_at", "summary"])
    return True


def cancel_file_operation(operation):
    if operation.status not in {"running", "paused"}:
        return False
    operation.cancel_requested_at = timezone.now()
    operation.summary = "Cancel requested. The operation will stop after the current item."
    operation.save(update_fields=["cancel_requested_at", "summary"])
    if operation.status == "paused":
        finalize_file_operation(operation, "cancelled", "File operation cancelled while paused.")
    return True


def resume_file_operation(operation):
    if operation.status not in {"paused", "failed", "cancelled"}:
        return False
    start_background_file_operation(operation)
    return True


def finalize_file_operation(operation, status, summary):
    operation.status = status
    operation.summary = summary
    operation.finished_at = timezone.now()
    operation.process_pid = None
    operation.heartbeat_at = timezone.now()
    _append_log(operation, summary)
    operation.save(update_fields=["status", "summary", "finished_at", "process_pid", "heartbeat_at", "log_output"])


def execute_file_operation(operation):
    operation.process_pid = os.getpid()
    operation.runner_label = _runner_label()
    operation.status = "running"
    operation.heartbeat_at = timezone.now()
    _append_log(operation, f"Starting {operation.get_action_display().lower()} operation on {_runner_label()}.")
    operation.save(update_fields=["process_pid", "runner_label", "status", "heartbeat_at", "log_output"])
    if operation.action == "download":
        _execute_download_operation(operation)
        return

    completed = set(operation.completed_sources or [])
    errors = []
    sources = operation.sources or []
    total_sources = len(sources)
    for source_index, source in enumerate(sources, start=1):
        operation.refresh_from_db()
        if source in completed:
            continue
        if operation.cancel_requested_at:
            finalize_file_operation(operation, "cancelled", "File operation cancelled by operator.")
            return
        if operation.pause_requested_at:
            operation.status = "paused"
            operation.summary = "File operation paused."
            operation.process_pid = None
            _append_log(operation, "Paused before next item.")
            operation.save(update_fields=["status", "summary", "process_pid", "log_output", "heartbeat_at"])
            return

        operation.current_path = source
        operation.summary = f"Processing item {source_index}/{total_sources}: {source}"
        operation.heartbeat_at = timezone.now()
        _append_log(operation, f"Starting item {source_index}/{total_sources}: {source}")
        operation.save(update_fields=["current_path", "summary", "log_output", "heartbeat_at"])
        try:
            item_result = _perform_item(operation, source)
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            _append_log(operation, f"ERROR item {source_index}/{total_sources}: {source}: {exc}")
        else:
            completed.add(source)
            operation.completed_sources = sorted(completed)
            operation.processed_count = len(completed)
            if item_result == "skipped":
                operation.summary = f"Skipped item {source_index}/{total_sources}: {source}"
                _append_log(operation, f"Skipped item {source_index}/{total_sources}: {source}")
            else:
                operation.summary = f"Completed item {source_index}/{total_sources}: {source}"
                _append_log(operation, f"Completed item {source_index}/{total_sources}: {source}")
        operation.save(update_fields=["completed_sources", "processed_count", "summary", "log_output", "heartbeat_at"])

    if errors:
        finalize_file_operation(operation, "failed", f"File operation finished with {len(errors)} error(s).")
    else:
        finalize_file_operation(operation, "success", f"File operation completed for {len(completed)} item(s).")


def _perform_item(operation, source):
    absolute_source = hostfs_path(source)
    if not os.path.lexists(absolute_source):
        raise FileNotFoundError("Source no longer exists.")
    if operation.action == "delete":
        _append_log(operation, f"Deleting {source}")
        operation.save(update_fields=["log_output", "heartbeat_at"])
        _delete_path(absolute_source)
        return

    destination_root = hostfs_path(operation.destination_path)
    target = os.path.join(destination_root, os.path.basename(source.rstrip("/")))
    if os.path.abspath(target) == os.path.abspath(absolute_source):
        _append_log(operation, f"Skipped {source}: source and destination are the same path")
        operation.save(update_fields=["log_output", "heartbeat_at"])
        return "skipped"
    if os.path.lexists(target):
        if operation.conflict_policy == "skip":
            _append_log(operation, f"Skipped {source}: destination already exists")
            operation.save(update_fields=["log_output", "heartbeat_at"])
            return "skipped"
        if operation.conflict_policy == "rename":
            target = _available_conflict_target(destination_root, os.path.basename(source.rstrip("/")))
            _append_log(operation, f"Destination exists; using renamed target {target}")
            operation.save(update_fields=["log_output", "heartbeat_at"])
        else:
            _append_log(operation, f"Destination exists; overwriting {target}")
            _delete_path(target)
    if operation.action == "copy":
        if os.path.isdir(absolute_source) and not os.path.islink(absolute_source):
            _copy_directory_with_progress(operation, absolute_source, target, source)
        else:
            _append_log(operation, f"Copying file {source}")
            operation.save(update_fields=["log_output", "heartbeat_at"])
            shutil.copy2(absolute_source, target, follow_symlinks=False)
        return
    if operation.action == "move":
        _append_log(operation, f"Moving {source} to {operation.destination_path}")
        operation.save(update_fields=["log_output", "heartbeat_at"])
        shutil.move(absolute_source, target)
        return
    raise ValueError("Unsupported file operation.")


def _available_conflict_target(destination_root, name):
    stem, suffix = os.path.splitext(name)
    index = 1
    while True:
        candidate_name = f"{stem} ({index}){suffix}"
        candidate = os.path.join(destination_root, candidate_name)
        if not os.path.lexists(candidate):
            return candidate
        index += 1


def _copy_directory_with_progress(operation, source, target, display_source):
    copied_files = 0

    def copy_with_progress(source_file, target_file):
        nonlocal copied_files
        shutil.copy2(source_file, target_file, follow_symlinks=False)
        copied_files += 1
        if copied_files == 1 or copied_files % 25 == 0:
            relative_file = os.path.relpath(source_file, source).replace("\\", "/")
            operation.current_path = f"{display_source}/{relative_file}"
            operation.summary = f"Copying {display_source}: {copied_files} file(s) copied"
            _append_log(operation, f"Progress {display_source}: {copied_files} file(s) copied")
            operation.save(update_fields=["current_path", "summary", "log_output", "heartbeat_at"])

    _append_log(operation, f"Copying directory tree {display_source}")
    operation.save(update_fields=["log_output", "heartbeat_at"])
    shutil.copytree(source, target, symlinks=True, copy_function=copy_with_progress)


def _download_root():
    db_path = os.getenv("DJANGO_DB_PATH", "/app/data/db.sqlite3")
    root = Path(db_path).resolve().parent / DOWNLOAD_ARCHIVE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def download_archive_path(operation_id):
    return _download_root() / f"download_{int(operation_id)}.zip"


def _upload_session_root(operation_id):
    db_path = os.getenv("DJANGO_DB_PATH", "/app/data/db.sqlite3")
    root = Path(db_path).resolve().parent / UPLOAD_SESSION_DIR_NAME / str(int(operation_id))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _execute_download_operation(operation):
    completed = set()
    operation.completed_sources = []
    operation.processed_count = 0
    archive_path = download_archive_path(operation.id)
    tmp_archive_path = archive_path.with_suffix(".tmp")
    errors = []
    if tmp_archive_path.exists():
        tmp_archive_path.unlink()

    _append_log(operation, f"Preparing ZIP archive: {archive_path.name}")
    operation.destination_path = str(archive_path)
    operation.save(update_fields=["destination_path", "completed_sources", "processed_count", "log_output", "heartbeat_at"])

    with zipfile.ZipFile(tmp_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_handle:
        sources = operation.sources or []
        total_sources = len(sources)
        for source_index, source in enumerate(sources, start=1):
            operation.refresh_from_db()
            if source in completed:
                continue
            if operation.cancel_requested_at:
                finalize_file_operation(operation, "cancelled", "Download preparation cancelled by operator.")
                return
            if operation.pause_requested_at:
                operation.status = "paused"
                operation.summary = "Download preparation paused."
                operation.process_pid = None
                _append_log(operation, "Paused before next item.")
                operation.save(update_fields=["status", "summary", "process_pid", "log_output", "heartbeat_at"])
                return

            operation.current_path = source
            operation.summary = f"Adding item {source_index}/{total_sources} to ZIP: {source}"
            operation.heartbeat_at = timezone.now()
            _append_log(operation, f"Starting ZIP item {source_index}/{total_sources}: {source}")
            operation.save(update_fields=["current_path", "summary", "log_output", "heartbeat_at"])
            try:
                _write_source_to_zip(zip_handle, source, operation)
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                _append_log(operation, f"ERROR ZIP item {source_index}/{total_sources}: {source}: {exc}")
            else:
                completed.add(source)
                operation.completed_sources = sorted(completed)
                operation.processed_count = len(completed)
                operation.summary = f"Completed ZIP item {source_index}/{total_sources}: {source}"
                _append_log(operation, f"Completed ZIP item {source_index}/{total_sources}: {source}")
            operation.save(update_fields=["completed_sources", "processed_count", "summary", "log_output", "heartbeat_at"])

    tmp_archive_path.replace(archive_path)
    if errors:
        finalize_file_operation(operation, "failed", f"Download ZIP finished with {len(errors)} error(s).")
    else:
        finalize_file_operation(operation, "success", f"Download ZIP ready for {len(completed)} item(s).")


def _write_source_to_zip(zip_handle, source, operation=None):
    absolute_source = hostfs_path(source)
    if not os.path.lexists(absolute_source):
        raise FileNotFoundError("Source no longer exists.")
    archive_root = os.path.basename(source.rstrip("/")) or "root"
    if os.path.isdir(absolute_source) and not os.path.islink(absolute_source):
        archived_files = 0
        for root, dirs, files in os.walk(absolute_source):
            dirs.sort()
            files.sort()
            relative_root = os.path.relpath(root, absolute_source)
            if relative_root != ".":
                zip_handle.write(root, os.path.join(archive_root, relative_root))
            for file_name in files:
                absolute_file = os.path.join(root, file_name)
                relative_name = os.path.relpath(absolute_file, absolute_source)
                zip_handle.write(absolute_file, os.path.join(archive_root, relative_name))
                archived_files += 1
                if operation and (archived_files == 1 or archived_files % 25 == 0):
                    operation.current_path = f"{source}/{relative_name}".replace("//", "/")
                    operation.summary = f"Adding {source} to ZIP: {archived_files} file(s)"
                    _append_log(operation, f"ZIP progress {source}: {archived_files} file(s) added")
                    operation.save(update_fields=["current_path", "summary", "log_output", "heartbeat_at"])
        return
    zip_handle.write(absolute_source, archive_root)


def _delete_path(absolute_path):
    if os.path.isdir(absolute_path) and not os.path.islink(absolute_path):
        shutil.rmtree(absolute_path)
    else:
        os.unlink(absolute_path)


def save_uploaded_files(current_path, uploaded_files, *, worker_count=2):
    destination = normalize_host_path(current_path or "/")
    absolute_destination = hostfs_path(destination)
    if not os.path.isdir(absolute_destination):
        raise ValueError("Upload destination does not exist.")
    if not uploaded_files:
        raise ValueError("Choose at least one file to upload.")

    try:
        worker_count = max(1, min(int(worker_count or 2), 4))
    except (TypeError, ValueError):
        worker_count = 2

    operation = FileOperation.objects.create(
        action="upload",
        status="running",
        destination_path=destination,
        total_count=len(uploaded_files),
        summary=f"Receiving {len(uploaded_files)} uploaded file(s).",
        heartbeat_at=timezone.now(),
        runner_label=_runner_label(),
        process_pid=os.getpid(),
    )
    _append_log(operation, f"Upload target: {destination}")
    _append_log(operation, f"Requested upload workers: {worker_count}. Files are committed conservatively as they arrive from the browser.")
    operation.save(update_fields=["log_output", "heartbeat_at"])

    saved = []
    errors = []
    for uploaded_file in uploaded_files:
        try:
            safe_name = _safe_upload_name(uploaded_file.name)
            absolute_target = _available_upload_path(absolute_destination, safe_name)
            os.makedirs(os.path.dirname(absolute_target), exist_ok=True)
            with open(absolute_target, "wb") as target:
                for chunk in uploaded_file.chunks():
                    target.write(chunk)
            relative_saved = os.path.relpath(absolute_target, absolute_destination).replace("\\", "/")
            saved_path = os.path.join(destination, relative_saved).replace("\\", "/")
            saved.append(saved_path)
            operation.current_path = saved_path
            operation.processed_count = len(saved)
            operation.completed_sources = saved
            operation.sources = saved
            _append_log(operation, f"Saved {saved_path}.")
            operation.save(update_fields=["current_path", "processed_count", "completed_sources", "sources", "log_output", "heartbeat_at"])
        except Exception as exc:
            errors.append(f"{uploaded_file.name}: {exc}")
            _append_log(operation, f"ERROR {uploaded_file.name}: {exc}")
            operation.save(update_fields=["log_output", "heartbeat_at"])

    if errors:
        finalize_file_operation(operation, "failed", f"Upload finished with {len(errors)} error(s).")
    else:
        finalize_file_operation(operation, "success", f"Uploaded {len(saved)} file(s).")
    return operation


def start_chunked_upload(current_path, file_count, *, worker_count=2):
    destination = normalize_host_path(current_path or "/")
    absolute_destination = hostfs_path(destination)
    if not os.path.isdir(absolute_destination):
        raise ValueError("Upload destination does not exist.")
    try:
        file_count = int(file_count or 0)
    except (TypeError, ValueError):
        file_count = 0
    if file_count < 1:
        raise ValueError("Choose at least one file to upload.")
    try:
        worker_count = max(1, min(int(worker_count or 2), 4))
    except (TypeError, ValueError):
        worker_count = 2

    operation = FileOperation.objects.create(
        action="upload",
        status="running",
        destination_path=destination,
        total_count=file_count,
        summary=f"Receiving {file_count} uploaded file(s).",
        heartbeat_at=timezone.now(),
        runner_label=_runner_label(),
        process_pid=os.getpid(),
    )
    _append_log(operation, f"Upload target: {destination}")
    _append_log(operation, f"Chunked upload started. Requested workers: {worker_count}.")
    operation.save(update_fields=["log_output", "heartbeat_at"])
    _upload_session_root(operation.id)
    return operation


def save_upload_chunk(operation_id, current_path, relative_name, uploaded_chunk, chunk_index, total_chunks):
    operation = FileOperation.objects.get(pk=operation_id, action="upload")
    if operation.status != "running":
        raise ValueError("Upload operation is not running.")
    if uploaded_chunk is None:
        raise ValueError("Upload chunk is missing.")
    destination = normalize_host_path(current_path or operation.destination_path or "/")
    if destination != operation.destination_path:
        raise ValueError("Upload destination changed during upload.")
    absolute_destination = hostfs_path(destination)
    if not os.path.isdir(absolute_destination):
        raise ValueError("Upload destination does not exist.")
    safe_name = _safe_upload_name(relative_name)
    try:
        chunk_index = int(chunk_index)
        total_chunks = int(total_chunks)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid upload chunk metadata.") from exc
    if chunk_index < 0 or total_chunks < 1 or chunk_index >= total_chunks:
        raise ValueError("Invalid upload chunk index.")

    session_root = _upload_session_root(operation.id)
    partial_path = session_root / f"{safe_name}.part"
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if chunk_index == 0 else "ab"
    with open(partial_path, mode) as target:
        for chunk in uploaded_chunk.chunks():
            target.write(chunk)

    operation.current_path = os.path.join(destination, safe_name).replace("\\", "/")
    operation.summary = f"Uploading {safe_name} ({chunk_index + 1}/{total_chunks})"
    _append_log(operation, f"Received chunk {chunk_index + 1}/{total_chunks} for {safe_name}.")

    saved_path = ""
    if chunk_index == total_chunks - 1:
        absolute_target = _available_upload_path(absolute_destination, safe_name)
        os.makedirs(os.path.dirname(absolute_target), exist_ok=True)
        shutil.move(str(partial_path), absolute_target)
        relative_saved = os.path.relpath(absolute_target, absolute_destination).replace("\\", "/")
        saved_path = os.path.join(destination, relative_saved).replace("\\", "/")
        completed = list(operation.completed_sources or [])
        completed.append(saved_path)
        operation.completed_sources = completed
        operation.sources = completed
        operation.processed_count = len(completed)
        operation.current_path = saved_path
        operation.summary = f"Uploaded {len(completed)}/{operation.total_count} file(s)."
        _append_log(operation, f"Saved {saved_path}.")

    operation.save(update_fields=["current_path", "summary", "completed_sources", "sources", "processed_count", "log_output", "heartbeat_at"])
    return operation, saved_path


def finish_chunked_upload(operation_id):
    operation = FileOperation.objects.get(pk=operation_id, action="upload")
    if operation.status != "running":
        return operation
    if operation.processed_count != operation.total_count:
        finalize_file_operation(operation, "failed", f"Upload incomplete: {operation.processed_count}/{operation.total_count} file(s) received.")
        return operation
    shutil.rmtree(_upload_session_root(operation.id), ignore_errors=True)
    finalize_file_operation(operation, "success", f"Uploaded {operation.processed_count} file(s).")
    return operation


def _safe_upload_name(name):
    normalized = os.path.normpath(str(name or "").replace("\\", "/")).lstrip("/")
    if not normalized or normalized == ".":
        raise ValueError("Uploaded file name is empty.")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Uploaded file path is not safe.")
    if any("\0" in part or "\n" in part or "\r" in part for part in parts):
        raise ValueError("Uploaded file path contains invalid characters.")
    return normalized


def _available_upload_path(root, relative_name):
    base, ext = os.path.splitext(relative_name)
    candidate = os.path.join(root, relative_name)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(root, f"{base}_{counter}{ext}")
        counter += 1
    return candidate
