import fnmatch
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import MonitoringSettings


DEFAULT_HTTP_TIMEOUT_SECONDS = 60
CHUNK_SIZE = 1024 * 1024
MAX_DELETE_BATCH = 1000


class HttpBackupError(RuntimeError):
    pass


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


def build_manifest(host_root_path, *, exclude_patterns=None, max_size_bytes=None, create_root=False):
    absolute_root = _hostfs_path(host_root_path)
    if create_root:
        os.makedirs(absolute_root, exist_ok=True)
    if not os.path.isdir(absolute_root):
        raise FileNotFoundError(f"Root folder not found: {host_root_path}")
    excludes = _patterns(exclude_patterns)
    max_size = max_size_bytes if max_size_bytes is not None else 100 * 1024 * 1024
    files = {}
    skipped = []
    for current_root, dirnames, filenames in os.walk(absolute_root):
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
            files[relative_path] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": _sha256_file(absolute_path),
            }
    return {"root_path": host_root_path, "files": files, "skipped": skipped}


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
        )
    except Exception as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True, **manifest})


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

    if request.method == "POST":
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = file_path.with_name(f".{file_path.name}.http-sync.tmp")
            with open(tmp_path, "wb") as handle:
                handle.write(request.body)
            os.replace(tmp_path, file_path)
            mtime_ns = request.GET.get("mtime_ns") or request.POST.get("mtime_ns")
            if mtime_ns:
                ns = int(mtime_ns)
                os.utime(file_path, ns=(ns, ns))
        except Exception as exc:
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


def _request_json(base_url, endpoint, token, payload, timeout, job=None):
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        _api_url(base_url, endpoint),
        data=data,
        method="POST",
        headers=_http_auth_headers(token, job, "application/json"),
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpBackupError(f"HTTP {exc.code} from {endpoint}: {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HttpBackupError(f"HTTP request to {endpoint} failed: {exc}") from exc
    if not result.get("ok"):
        raise HttpBackupError(result.get("error") or f"{endpoint} returned ok=false")
    return result


def _download_file(base_url, token, root_path, relative_path, timeout, job=None):
    query = urlencode({"root_path": root_path, "relative_path": relative_path})
    request = Request(
        f"{_api_url(base_url, 'file')}?{query}",
        method="GET",
        headers=_http_auth_headers(token, job),
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpBackupError(f"HTTP {exc.code} while downloading {relative_path}: {body}") from exc
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
    request = Request(
        f"{_api_url(base_url, 'file')}?{query}",
        data=content,
        method="POST",
        headers=_http_auth_headers(token, job, "application/octet-stream"),
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpBackupError(f"HTTP {exc.code} while uploading {relative_path}: {body}") from exc
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
        if not other or other.get("size") != metadata.get("size") or other.get("sha256") != metadata.get("sha256"):
            changed.append(relative_path)
    return changed


def sync_http_backup(job, *, log_callback=None, heartbeat_callback=None, should_stop=None):
    def log(message):
        if log_callback:
            log_callback(message)
        if heartbeat_callback:
            heartbeat_callback(force=False)

    def ensure_not_stopped():
        if should_stop and should_stop():
            raise InterruptedError("Stop requested.")

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
    }

    log(f"HTTP backup mode: {job.http_direction}")
    log(f"Remote server: {base_url}")
    log(f"Remote path: {job.http_remote_path}")
    log(f"Max file size: {max_size_bytes} bytes")
    log(f"HTTP request timeout: {timeout}s")
    if job.http_direction == "pull":
        local_root = job.local_dest_path
        remote_root = job.http_remote_path
        if not local_root:
            raise ValueError("Pull backups need a local destination folder.")
        remote_manifest = _request_json(base_url, "manifest", token, {"root_path": remote_root, **common_payload}, timeout, job)
        local_manifest = build_manifest(local_root, create_root=True, **common_payload)
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
    local_manifest = build_manifest(local_root, **common_payload)
    remote_manifest = _request_json(base_url, "manifest", token, {"root_path": remote_root, "create_root": True, **common_payload}, timeout, job)
    source_files = local_manifest["files"]
    dest_files = remote_manifest["files"]
    changed = _changed_files(source_files, dest_files)
    extra = sorted(set(dest_files) - set(source_files))
    log(f"Local manifest: {len(source_files)} files, {len(local_manifest.get('skipped', []))} skipped.")
    log(f"Remote manifest: {len(dest_files)} files, {len(remote_manifest.get('skipped', []))} skipped.")
    for index, relative_path in enumerate(changed, start=1):
        ensure_not_stopped()
        content = _read_local_file(local_root, relative_path)
        _upload_file(base_url, token, remote_root, relative_path, source_files[relative_path], content, timeout, job)
        log(f"Pushed {index}/{len(changed)} {relative_path}")
    deleted_count = 0
    if job.delete_enabled and extra:
        for start in range(0, len(extra), MAX_DELETE_BATCH):
            ensure_not_stopped()
            batch = extra[start : start + MAX_DELETE_BATCH]
            result = _request_json(base_url, "delete", token, {"root_path": remote_root, "relative_paths": batch}, timeout, job)
            deleted_count += len(result.get("deleted", []))
        log(f"Deleted {deleted_count} remote files missing locally.")
    return {"changed": len(changed), "deleted": deleted_count, "skipped": len(local_manifest.get("skipped", []))}
