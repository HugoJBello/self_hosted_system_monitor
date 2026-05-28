import fnmatch
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import MonitoringSettings


DEFAULT_HTTP_TIMEOUT_SECONDS = 60
CHUNK_SIZE = 1024 * 1024
MAX_DELETE_BATCH = 1000
MAX_STAT_BATCH = 1000
HTTP_RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_BACKOFF_SECONDS = 1
MANIFEST_PROGRESS_EVERY = 1000
HTTP_BATCH_PROGRESS_EVERY = 100


class HttpBackupError(RuntimeError):
    pass


class HttpBackupResponseError(HttpBackupError):
    def __init__(self, code, body):
        super().__init__(body)
        self.code = code
        self.body = body


def parse_size_limit(value, default=100 * 1024 * 1024):
    text = (value or "").strip().lower()
    if not text:
        return default
    multipliers = {
        "k": 1024,
        "kb": 1024,
        "m": 1024 * 1024,
        "mb": 1024 * 1024,
        "g": 1024 * 1024 * 1024,
        "gb": 1024 * 1024 * 1024,
    }
    for suffix, multiplier in sorted(multipliers.items(), key=lambda item: len(item[0]), reverse=True):
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            return int(float(number) * multiplier)
    return int(float(text))


def _hostfs_path(host_path):
    normalized = os.path.normpath(host_path or "/")
    if not normalized.startswith("/"):
        raise ValueError("Path must be absolute.")
    if normalized.startswith("/hostfs"):
        raise ValueError("Use host paths like /home/user, not /hostfs-prefixed paths.")
    return os.path.join("/hostfs", normalized.lstrip("/"))


def _safe_relative_path(value):
    rel_path = (value or "").replace("\\", "/").lstrip("/")
    normalized = os.path.normpath(rel_path).replace("\\", "/")
    if normalized in {"", "."} or normalized.startswith("../") or normalized == ".." or os.path.isabs(normalized):
        raise ValueError("Invalid relative path.")
    return normalized


def _safe_optional_relative_dir(value):
    rel_path = (value or "").replace("\\", "/").strip("/")
    if not rel_path:
        return ""
    return _safe_relative_path(rel_path)


def _safe_child_path(root_path, relative_path):
    root = Path(root_path).resolve()
    child = (root / _safe_relative_path(relative_path)).resolve()
    if child != root and root not in child.parents:
        raise ValueError("Relative path escapes root.")
    return child


def _patterns(value):
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def _is_excluded(relative_path, patterns):
    rel = relative_path.replace("\\", "/").lstrip("/")
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        clean = pattern.strip().replace("\\", "/").lstrip("/")
        if not clean:
            continue
        if clean.endswith("/") and (rel == clean.rstrip("/") or rel.startswith(clean)):
            return True
        if fnmatch.fnmatch(rel, clean) or fnmatch.fnmatch(name, clean):
            return True
    return False


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    host_root_path,
    *,
    exclude_patterns=None,
    max_size_bytes=None,
    create_root=False,
    include_hashes=True,
    progress_callback=None,
    should_stop=None,
):
    def report_progress(force=False):
        if should_stop and should_stop():
            raise InterruptedError("Stop requested.")
        if progress_callback:
            progress_callback(force=force)

    absolute_root = _hostfs_path(host_root_path)
    if create_root:
        os.makedirs(absolute_root, exist_ok=True)
    if not os.path.isdir(absolute_root):
        raise FileNotFoundError(f"Root folder not found: {host_root_path}")
    excludes = _patterns(exclude_patterns)
    max_size = max_size_bytes if max_size_bytes is not None else 100 * 1024 * 1024
    files = {}
    skipped = []
    scanned = 0
    for current_root, dirnames, filenames in os.walk(absolute_root):
        report_progress()
        relative_dir = os.path.relpath(current_root, absolute_root)
        relative_dir = "" if relative_dir == "." else relative_dir.replace("\\", "/")
        kept_dirs = []
        for dirname in dirnames:
            rel_dir = f"{relative_dir}/{dirname}".strip("/")
            if _is_excluded(f"{rel_dir}/", excludes):
                skipped.append({"path": rel_dir, "reason": "excluded"})
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            scanned += 1
            if scanned % MANIFEST_PROGRESS_EVERY == 0:
                report_progress()
            relative_path = f"{relative_dir}/{filename}".strip("/")
            if _is_excluded(relative_path, excludes):
                skipped.append({"path": relative_path, "reason": "excluded"})
                continue
            absolute_path = os.path.join(current_root, filename)
            try:
                stat = os.stat(absolute_path, follow_symlinks=False)
            except OSError:
                skipped.append({"path": relative_path, "reason": "stat_failed"})
                continue
            if not os.path.isfile(absolute_path):
                skipped.append({"path": relative_path, "reason": "not_regular_file"})
                continue
            if max_size and stat.st_size > max_size:
                skipped.append({"path": relative_path, "reason": "too_large", "size": stat.st_size})
                continue
            metadata = _stat_metadata(stat)
            if include_hashes:
                metadata["sha256"] = _sha256_file(absolute_path)
                report_progress()
            files[relative_path] = metadata
    report_progress(force=True)
    return {"root_path": host_root_path, "files": files, "skipped": skipped}


def _stat_metadata(stat):
    return {
        "size": stat.st_size,
        "mtime": stat.st_mtime_ns // 1_000_000_000,
        "mtime_ns": stat.st_mtime_ns,
    }


def _auth_ok(request):
    expected = (MonitoringSettings.load().http_backup_token or "").strip()
    header = request.headers.get("Authorization", "")
    return bool(expected) and header == f"Bearer {expected}"


def _json_request(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON body.") from exc


def _json_error(message, status=400):
    return JsonResponse({"ok": False, "error": str(message)}, status=status)


def _write_request_stream_to_file(request, destination_path):
    stream = request.META.get("wsgi.input")
    if stream is None:
        raise ValueError("Request input stream is not available.")
    remaining = int(request.META.get("CONTENT_LENGTH") or 0)
    with open(destination_path, "wb") as handle:
        if remaining:
            while remaining > 0:
                chunk = stream.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError("Upload ended before the declared content length.")
                handle.write(chunk)
                remaining -= len(chunk)
        else:
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)


def _temporary_upload_path(file_path):
    prefix = f".{file_path.name}.http-sync."
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=file_path.parent,
        prefix=prefix,
        suffix=".tmp",
        delete=False,
    )
    handle.close()
    return Path(handle.name)


@csrf_exempt
def http_backup_manifest_view(request):
    if not _auth_ok(request):
        return _json_error("Unauthorized.", status=401)
    if request.method != "POST":
        return _json_error("Method not allowed.", status=405)
    try:
        payload = _json_request(request)
        manifest = build_manifest(
            payload.get("root_path", ""),
            exclude_patterns=payload.get("exclude_patterns") or [],
            max_size_bytes=payload.get("max_size_bytes"),
            create_root=bool(payload.get("create_root")),
            include_hashes=payload.get("include_hashes", True),
        )
    except Exception as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True, **manifest})


@csrf_exempt
def http_backup_stat_view(request):
    if not _auth_ok(request):
        return _json_error("Unauthorized.", status=401)
    if request.method != "POST":
        return _json_error("Method not allowed.", status=405)
    try:
        payload = _json_request(request)
        absolute_root = _hostfs_path(payload.get("root_path", ""))
        if payload.get("create_root"):
            os.makedirs(absolute_root, exist_ok=True)
        if not os.path.isdir(absolute_root):
            raise FileNotFoundError(f"Root folder not found: {payload.get('root_path', '')}")
        relative_paths = payload.get("relative_paths") or []
        if len(relative_paths) > MAX_STAT_BATCH:
            raise ValueError(f"Stat batch too large. Maximum is {MAX_STAT_BATCH}.")
        files = {}
        missing = []
        skipped = []
        for relative_path in relative_paths:
            safe_relative_path = _safe_relative_path(relative_path)
            file_path = _safe_child_path(absolute_root, safe_relative_path)
            try:
                stat = os.stat(file_path, follow_symlinks=False)
            except FileNotFoundError:
                missing.append(safe_relative_path)
                continue
            except OSError:
                skipped.append({"path": safe_relative_path, "reason": "stat_failed"})
                continue
            if not os.path.isfile(file_path):
                skipped.append({"path": safe_relative_path, "reason": "not_regular_file"})
                continue
            files[safe_relative_path] = _stat_metadata(stat)
    except Exception as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True, "files": files, "missing": missing, "skipped": skipped})


@csrf_exempt
def http_backup_list_view(request):
    if not _auth_ok(request):
        return _json_error("Unauthorized.", status=401)
    if request.method != "POST":
        return _json_error("Method not allowed.", status=405)
    try:
        payload = _json_request(request)
        absolute_root = _hostfs_path(payload.get("root_path", ""))
        relative_dir = _safe_optional_relative_dir(payload.get("relative_dir", ""))
        if payload.get("create_root"):
            os.makedirs(absolute_root, exist_ok=True)
        root = Path(absolute_root).resolve()
        directory = root if not relative_dir else _safe_child_path(root, relative_dir)
        if not directory.is_dir():
            raise FileNotFoundError(f"Folder not found: {payload.get('root_path', '')}/{relative_dir}".rstrip("/"))
        excludes = _patterns(payload.get("exclude_patterns") or [])
        max_size = payload.get("max_size_bytes")
        files = {}
        dirs = []
        skipped = []
        with os.scandir(directory) as entries:
            for entry in entries:
                relative_path = f"{relative_dir}/{entry.name}".strip("/")
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if _is_excluded(f"{relative_path}/", excludes):
                            skipped.append({"path": relative_path, "reason": "excluded"})
                        else:
                            dirs.append(relative_path)
                        continue
                    if _is_excluded(relative_path, excludes):
                        skipped.append({"path": relative_path, "reason": "excluded"})
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    if not entry.is_file(follow_symlinks=False):
                        skipped.append({"path": relative_path, "reason": "not_regular_file"})
                        continue
                    if max_size and stat.st_size > max_size:
                        skipped.append({"path": relative_path, "reason": "too_large", "size": stat.st_size})
                        continue
                    files[relative_path] = _stat_metadata(stat)
                except OSError:
                    skipped.append({"path": relative_path, "reason": "stat_failed"})
    except Exception as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True, "relative_dir": relative_dir, "dirs": sorted(dirs), "files": files, "skipped": skipped})


@csrf_exempt
def http_backup_file_view(request):
    if not _auth_ok(request):
        return _json_error("Unauthorized.", status=401)
    try:
        root_path = request.GET.get("root_path") or request.POST.get("root_path")
        relative_path = request.GET.get("relative_path") or request.POST.get("relative_path")
        absolute_root = _hostfs_path(root_path)
        file_path = _safe_child_path(absolute_root, relative_path)
    except Exception as exc:
        return _json_error(exc)

    if request.method == "GET":
        if not file_path.is_file():
            return _json_error("File not found.", status=404)
        return FileResponse(open(file_path, "rb"), as_attachment=False)

    if request.method == "HEAD":
        if not file_path.is_file():
            return HttpResponse(status=404)
        try:
            stat = os.stat(file_path, follow_symlinks=False)
        except OSError:
            return HttpResponse(status=404)
        response = HttpResponse()
        metadata = _stat_metadata(stat)
        response.headers["X-Backup-Size"] = str(metadata["size"])
        response.headers["X-Backup-Mtime"] = str(metadata["mtime"])
        response.headers["X-Backup-Mtime-Ns"] = str(metadata["mtime_ns"])
        return response

    if request.method == "POST":
        tmp_path = None
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = _temporary_upload_path(file_path)
            _write_request_stream_to_file(request, tmp_path)
            os.replace(tmp_path, file_path)
            mtime_ns = request.GET.get("mtime_ns")
            if mtime_ns:
                ns = int(mtime_ns)
                os.utime(file_path, ns=(ns, ns))
        except Exception as exc:
            if tmp_path:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return _json_error(exc)
        return JsonResponse({"ok": True})

    return _json_error("Method not allowed.", status=405)


@csrf_exempt
def http_backup_delete_view(request):
    if not _auth_ok(request):
        return _json_error("Unauthorized.", status=401)
    if request.method != "POST":
        return _json_error("Method not allowed.", status=405)
    try:
        payload = _json_request(request)
        absolute_root = _hostfs_path(payload.get("root_path", ""))
        relative_paths = payload.get("relative_paths") or []
        if len(relative_paths) > MAX_DELETE_BATCH:
            raise ValueError(f"Delete batch too large. Maximum is {MAX_DELETE_BATCH}.")
        deleted = []
        for relative_path in relative_paths:
            file_path = _safe_child_path(absolute_root, relative_path)
            if file_path.is_file() or file_path.is_symlink():
                file_path.unlink()
                deleted.append(relative_path)
        _prune_empty_dirs(absolute_root)
    except Exception as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True, "deleted": deleted})


def _prune_empty_dirs(root_path):
    root = Path(root_path).resolve()
    for current_root, dirnames, _ in os.walk(root, topdown=False):
        for dirname in dirnames:
            path = Path(current_root) / dirname
            try:
                path.rmdir()
            except OSError:
                pass


def _api_url(base_url, endpoint):
    return f"{base_url.rstrip('/')}/backups/http/{endpoint}/"


def _http_request_timeout(job):
    return max(DEFAULT_HTTP_TIMEOUT_SECONDS, int(job.idle_timeout_seconds or 0))


def _http_auth_headers(token, job=None, content_type=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "system-monitor-http-backup/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _retry_delay(attempt):
    return min(HTTP_RETRY_BACKOFF_SECONDS * (2 ** attempt), 10)


def _read_http_response(make_request, timeout):
    for attempt in range(HTTP_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(make_request(), timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in HTTP_RETRY_STATUS_CODES and attempt < HTTP_RETRY_ATTEMPTS:
                time.sleep(_retry_delay(attempt))
                continue
            raise HttpBackupResponseError(exc.code, body) from exc
        except (URLError, TimeoutError):
            if attempt < HTTP_RETRY_ATTEMPTS:
                time.sleep(_retry_delay(attempt))
                continue
            raise
    raise HttpBackupError("HTTP request failed after retries.")


def _request_json(base_url, endpoint, token, payload, timeout, job=None):
    data = json.dumps(payload).encode("utf-8")

    def make_request():
        return Request(
            _api_url(base_url, endpoint),
            data=data,
            method="POST",
            headers=_http_auth_headers(token, job, "application/json"),
        )

    try:
        result = json.loads(_read_http_response(make_request, timeout).decode("utf-8"))
    except HttpBackupResponseError as exc:
        raise HttpBackupError(f"HTTP {exc.code} from {endpoint}: {exc.body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HttpBackupError(f"HTTP request to {endpoint} failed: {exc}") from exc
    if not result.get("ok"):
        raise HttpBackupError(result.get("error") or f"{endpoint} returned ok=false")
    return result


def _request_remote_stats(base_url, token, root_path, relative_paths, timeout, job=None, progress_callback=None):
    files = {}
    skipped = []
    total_batches = max(1, (len(relative_paths) + MAX_STAT_BATCH - 1) // MAX_STAT_BATCH)
    for start in range(0, len(relative_paths), MAX_STAT_BATCH):
        batch = relative_paths[start : start + MAX_STAT_BATCH]
        result = _request_json(
            base_url,
            "stat",
            token,
            {"root_path": root_path, "create_root": start == 0, "relative_paths": batch},
            timeout,
            job,
        )
        files.update(result.get("files", {}))
        skipped.extend(result.get("skipped", []))
        if progress_callback:
            batch_number = start // MAX_STAT_BATCH + 1
            progress_callback(
                f"Remote stat progress: {min(start + len(batch), len(relative_paths))}/{len(relative_paths)} paths checked."
                if batch_number == total_batches or batch_number % HTTP_BATCH_PROGRESS_EVERY == 0
                else None
            )
    return {"files": files, "skipped": skipped}


def _request_remote_tree(base_url, token, root_path, common_payload, timeout, job=None, progress_callback=None):
    files = {}
    skipped = []
    pending_dirs = [""]
    checked_dirs = 0
    while pending_dirs:
        relative_dir = pending_dirs.pop(0)
        result = _request_json(
            base_url,
            "list",
            token,
            {"root_path": root_path, "relative_dir": relative_dir, "create_root": relative_dir == "", **common_payload},
            timeout,
            job,
        )
        files.update(result.get("files", {}))
        skipped.extend(result.get("skipped", []))
        pending_dirs.extend(result.get("dirs", []))
        checked_dirs += 1
        if progress_callback:
            progress_callback(
                f"Remote listing progress: {checked_dirs} folders scanned, {len(files)} files found."
                if checked_dirs % HTTP_BATCH_PROGRESS_EVERY == 0 or not pending_dirs
                else None
            )
    return {"files": files, "skipped": skipped}


def _head_remote_file(base_url, token, root_path, relative_path, timeout, job=None):
    query = urlencode({"root_path": root_path, "relative_path": relative_path})

    def make_request():
        return Request(
            f"{_api_url(base_url, 'file')}?{query}",
            method="HEAD",
            headers=_http_auth_headers(token, job),
        )

    for attempt in range(HTTP_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(make_request(), timeout=timeout) as response:
                size = response.headers.get("X-Backup-Size")
                mtime = response.headers.get("X-Backup-Mtime")
                mtime_ns = response.headers.get("X-Backup-Mtime-Ns")
                if size is None or mtime is None:
                    raise HttpBackupError("Remote file endpoint did not return backup metadata headers.")
                metadata = {"size": int(size), "mtime": int(mtime)}
                if mtime_ns is not None:
                    metadata["mtime_ns"] = int(mtime_ns)
                return metadata
        except HTTPError as exc:
            if exc.code == 404:
                return None
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in HTTP_RETRY_STATUS_CODES and attempt < HTTP_RETRY_ATTEMPTS:
                time.sleep(_retry_delay(attempt))
                continue
            raise HttpBackupResponseError(exc.code, body) from exc
        except (URLError, TimeoutError):
            if attempt < HTTP_RETRY_ATTEMPTS:
                time.sleep(_retry_delay(attempt))
                continue
            raise
    raise HttpBackupError("HTTP HEAD request failed after retries.")


def _request_remote_file_heads(base_url, token, root_path, relative_paths, timeout, job=None, progress_callback=None):
    files = {}
    for index, relative_path in enumerate(relative_paths, start=1):
        try:
            metadata = _head_remote_file(base_url, token, root_path, relative_path, timeout, job)
        except HttpBackupResponseError as exc:
            raise HttpBackupError(f"HTTP {exc.code} while checking {relative_path}: {exc.body}") from exc
        except (URLError, TimeoutError) as exc:
            raise HttpBackupError(f"HEAD check failed for {relative_path}: {exc}") from exc
        if metadata is not None:
            files[relative_path] = metadata
        if progress_callback:
            progress_callback(
                f"Remote HEAD progress: {index}/{len(relative_paths)} paths checked."
                if index == len(relative_paths) or index % HTTP_BATCH_PROGRESS_EVERY == 0
                else None
            )
    return {"files": files, "skipped": []}


def _endpoint_missing_error(exc, endpoint):
    return f"HTTP 404 from {endpoint}" in str(exc)


def _download_file(base_url, token, root_path, relative_path, timeout, job=None):
    query = urlencode({"root_path": root_path, "relative_path": relative_path})

    def make_request():
        return Request(
            f"{_api_url(base_url, 'file')}?{query}",
            method="GET",
            headers=_http_auth_headers(token, job),
        )

    try:
        return _read_http_response(make_request, timeout)
    except HttpBackupResponseError as exc:
        raise HttpBackupError(f"HTTP {exc.code} while downloading {relative_path}: {exc.body}") from exc
    except (URLError, TimeoutError) as exc:
        raise HttpBackupError(f"Download failed for {relative_path}: {exc}") from exc


def _upload_file(base_url, token, root_path, relative_path, metadata, content, timeout, job=None):
    query = urlencode(
        {
            "root_path": root_path,
            "relative_path": relative_path,
            "mtime_ns": metadata.get("mtime_ns") or "",
        }
    )
    def make_request():
        return Request(
            f"{_api_url(base_url, 'file')}?{query}",
            data=content,
            method="POST",
            headers=_http_auth_headers(token, job, "application/octet-stream"),
        )

    try:
        result = json.loads(_read_http_response(make_request, timeout).decode("utf-8"))
    except HttpBackupResponseError as exc:
        raise HttpBackupError(f"HTTP {exc.code} while uploading {relative_path}: {exc.body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HttpBackupError(f"Upload failed for {relative_path}: {exc}") from exc
    if not result.get("ok"):
        raise HttpBackupError(result.get("error") or f"Upload failed for {relative_path}")


def _write_local_file(root_path, relative_path, metadata, content):
    absolute_root = _hostfs_path(root_path)
    file_path = _safe_child_path(absolute_root, relative_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f".{file_path.name}.http-sync.tmp")
    with open(tmp_path, "wb") as handle:
        handle.write(content)
    os.replace(tmp_path, file_path)
    mtime_ns = metadata.get("mtime_ns")
    if mtime_ns:
        os.utime(file_path, ns=(int(mtime_ns), int(mtime_ns)))


def _read_local_file(root_path, relative_path):
    absolute_root = _hostfs_path(root_path)
    file_path = _safe_child_path(absolute_root, relative_path)
    with open(file_path, "rb") as handle:
        return handle.read()


def _delete_local_files(root_path, relative_paths):
    absolute_root = _hostfs_path(root_path)
    deleted = []
    for relative_path in relative_paths:
        file_path = _safe_child_path(absolute_root, relative_path)
        if file_path.is_file() or file_path.is_symlink():
            file_path.unlink()
            deleted.append(relative_path)
    _prune_empty_dirs(absolute_root)
    return deleted


def _changed_files(source_files, dest_files):
    changed = []
    for relative_path, metadata in sorted(source_files.items()):
        other = dest_files.get(relative_path)
        if not other:
            changed.append(relative_path)
            continue
        source_hash = metadata.get("sha256")
        dest_hash = other.get("sha256")
        if source_hash and dest_hash:
            differs = other.get("size") != metadata.get("size") or dest_hash != source_hash
        else:
            differs = other.get("size") != metadata.get("size") or _mtime_seconds(other) != _mtime_seconds(metadata)
        if differs:
            changed.append(relative_path)
    return changed


def _mtime_seconds(metadata):
    if metadata.get("mtime") is not None:
        return int(metadata.get("mtime"))
    if metadata.get("mtime_ns") is not None:
        return int(metadata.get("mtime_ns")) // 1_000_000_000
    return None


def sync_http_backup(job, *, log_callback=None, heartbeat_callback=None, should_stop=None):
    def log(message):
        if log_callback:
            log_callback(message)
        if heartbeat_callback:
            heartbeat_callback(force=False)

    def ensure_not_stopped():
        if should_stop and should_stop():
            raise InterruptedError("Stop requested.")

    def progress(message=None):
        if message:
            log(message)
        elif heartbeat_callback:
            heartbeat_callback(force=False)
        ensure_not_stopped()

    timeout = _http_request_timeout(job)
    base_url = job.http_remote_url.rstrip("/")
    token = (job.http_remote_token or "").strip()
    if not base_url:
        raise ValueError("HTTP remote server URL is required.")
    if not token:
        raise ValueError("HTTP remote Bearer token is required.")
    if not (job.http_remote_path or "").startswith("/"):
        raise ValueError("HTTP remote folder must be absolute.")
    max_size_bytes = parse_size_limit(job.max_size)
    common_payload = {
        "exclude_patterns": job.exclude_patterns_list,
        "max_size_bytes": max_size_bytes,
        "include_hashes": False,
    }

    log(f"HTTP backup mode: {job.http_direction}")
    log(f"Remote server: {base_url}")
    log(f"Remote path: {job.http_remote_path}")
    log(f"Max file size: {max_size_bytes} bytes")
    log(f"HTTP request timeout: {timeout}s")
    log("HTTP manifest comparison: size and mtime seconds.")
    if job.http_direction == "pull":
        local_root = job.local_dest_path
        remote_root = job.http_remote_path
        if not local_root:
            raise ValueError("Pull backups need a local destination folder.")
        remote_manifest = _request_json(base_url, "manifest", token, {"root_path": remote_root, **common_payload}, timeout, job)
        local_manifest = build_manifest(local_root, create_root=True, progress_callback=heartbeat_callback, should_stop=should_stop, **common_payload)
        source_files = remote_manifest["files"]
        dest_files = local_manifest["files"]
        changed = _changed_files(source_files, dest_files)
        extra = sorted(set(dest_files) - set(source_files))
        log(f"Remote manifest: {len(source_files)} files, {len(remote_manifest.get('skipped', []))} skipped.")
        log(f"Local manifest: {len(dest_files)} files, {len(local_manifest.get('skipped', []))} skipped.")
        for index, relative_path in enumerate(changed, start=1):
            ensure_not_stopped()
            content = _download_file(base_url, token, remote_root, relative_path, timeout, job)
            _write_local_file(local_root, relative_path, source_files[relative_path], content)
            log(f"Pulled {index}/{len(changed)} {relative_path}")
        deleted = _delete_local_files(local_root, extra) if job.delete_enabled else []
        if deleted:
            log(f"Deleted {len(deleted)} local files missing on remote.")
        return {"changed": len(changed), "deleted": len(deleted), "skipped": len(remote_manifest.get("skipped", []))}

    local_root = job.source_path
    remote_root = job.http_remote_path
    local_manifest = build_manifest(local_root, progress_callback=heartbeat_callback, should_stop=should_stop, **common_payload)
    source_files = local_manifest["files"]
    log(f"Local manifest: {len(source_files)} files, {len(local_manifest.get('skipped', []))} skipped.")
    job_delete_enabled = job.delete_enabled
    if job.delete_enabled:
        try:
            remote_manifest = _request_remote_tree(base_url, token, remote_root, common_payload, timeout, job, progress_callback=progress)
            log(f"Remote directory listing: {len(remote_manifest['files'])} files, {len(remote_manifest.get('skipped', []))} skipped.")
        except HttpBackupError as exc:
            if not _endpoint_missing_error(exc, "list"):
                raise
            log("Remote list endpoint is unavailable; using stat batches and skipping remote deletion for this run.")
            try:
                remote_manifest = _request_remote_stats(base_url, token, remote_root, sorted(source_files), timeout, job, progress_callback=progress)
            except HttpBackupError as stat_exc:
                if not _endpoint_missing_error(stat_exc, "stat"):
                    raise
                log("Remote stat endpoint is unavailable; using file HEAD checks and skipping remote deletion for this run.")
                remote_manifest = _request_remote_file_heads(base_url, token, remote_root, sorted(source_files), timeout, job, progress_callback=progress)
                log(f"Remote HEAD checks: {len(remote_manifest['files'])} matching-path files.")
            else:
                log(f"Remote stat: {len(remote_manifest['files'])} matching-path files, {len(remote_manifest.get('skipped', []))} skipped.")
            job_delete_enabled = False
    else:
        try:
            remote_manifest = _request_remote_stats(base_url, token, remote_root, sorted(source_files), timeout, job, progress_callback=progress)
            log(f"Remote stat: {len(remote_manifest['files'])} matching-path files, {len(remote_manifest.get('skipped', []))} skipped.")
        except HttpBackupError as exc:
            if not _endpoint_missing_error(exc, "stat"):
                raise
            log("Remote stat endpoint is unavailable; using file HEAD checks.")
            remote_manifest = _request_remote_file_heads(base_url, token, remote_root, sorted(source_files), timeout, job, progress_callback=progress)
            log(f"Remote HEAD checks: {len(remote_manifest['files'])} matching-path files.")
    dest_files = remote_manifest["files"]
    changed = _changed_files(source_files, dest_files)
    extra = sorted(set(dest_files) - set(source_files))
    for index, relative_path in enumerate(changed, start=1):
        ensure_not_stopped()
        content = _read_local_file(local_root, relative_path)
        _upload_file(base_url, token, remote_root, relative_path, source_files[relative_path], content, timeout, job)
        log(f"Pushed {index}/{len(changed)} {relative_path}")
    deleted_count = 0
    if job.delete_enabled and not job_delete_enabled:
        log("Remote deletion skipped because the destination does not expose the list endpoint.")
    if job_delete_enabled and extra:
        for start in range(0, len(extra), MAX_DELETE_BATCH):
            ensure_not_stopped()
            batch = extra[start : start + MAX_DELETE_BATCH]
            result = _request_json(base_url, "delete", token, {"root_path": remote_root, "relative_paths": batch}, timeout, job)
            deleted_count += len(result.get("deleted", []))
        log(f"Deleted {deleted_count} remote files missing locally.")
    return {"changed": len(changed), "deleted": deleted_count, "skipped": len(local_manifest.get("skipped", []))}
