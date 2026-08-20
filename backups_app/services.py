import os
import selectors
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import logging
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from django.utils import timezone
from django.db import OperationalError

from main_app.models import BackupJob, BackupRun
from .http_services import sync_http_backup
from volumes_app.path_browser import list_browser_roots as _list_browser_roots
from volumes_app.path_browser import list_directory_children as _list_directory_children


logger = logging.getLogger(__name__)
SQLITE_LOCK_RETRY_SECONDS = 0.2
SQLITE_LOCK_RETRY_ATTEMPTS = 5


HOST_ROOT_PREFIX = "/hostfs"
BACKUP_LOG_LIMIT = 20000
BACKUP_HEARTBEAT_INTERVAL_SECONDS = 15
BACKUP_STALE_AFTER_SECONDS = 180
BACKUP_LOG_FLUSH_INTERVAL_SECONDS = 2
BACKUP_LOG_FLUSH_MAX_BUFFERED_LINES = 25
DEFAULT_STOP_EXIT_CODE = 130
DEFAULT_TIMEOUT_EXIT_CODE = 124
RSYNC_PARTIAL_SUCCESS_EXIT_CODES = {23, 24}
BACKUP_NICE_LEVEL = 19
BACKUP_STOP_POLL_INTERVAL_SECONDS = 2
MOUNT_SENSITIVE_ROOTS = ("/media", "/mnt", "/run/media")


@dataclass
class BackupExecutionResult:
    ok: bool
    exit_code: int
    status: str
    summary: str
    log_output: str
    command_line: str = ""
    created_remote_dir: bool = False


@dataclass
class StreamingCommandResult:
    exit_code: int
    output: str
    termination_reason: str = ""


def _normalize_stream_output(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _consume_stream_buffer(buffer, collected, on_output):
    while buffer:
        newline_index = buffer.find("\n")
        carriage_index = buffer.find("\r")
        delimiter_indexes = [index for index in (newline_index, carriage_index) if index != -1]
        if not delimiter_indexes:
            break
        delimiter_index = min(delimiter_indexes)
        delimiter = buffer[delimiter_index]
        line = buffer[:delimiter_index]
        if delimiter == "\r" and delimiter_index + 1 < len(buffer) and buffer[delimiter_index + 1] == "\n":
            buffer = buffer[delimiter_index + 2 :]
        else:
            buffer = buffer[delimiter_index + 1 :]
        cleaned = line.rstrip("\r")
        if cleaned:
            collected.append(cleaned)
            if on_output:
                on_output(cleaned)
    return buffer


def _runner_label():
    return socket.gethostname()


def _format_command(command_parts):
    return " ".join(shlex.quote(str(part)) for part in command_parts)


def _pid_is_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def _process_cmdline(pid):
    if not pid:
        return ""
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _backup_worker_matches_run(backup_run, *, current_runner=None):
    current_runner = current_runner or _runner_label()
    if (backup_run.runner_label or "") != current_runner:
        return False
    if not _pid_is_alive(backup_run.process_pid):
        return False
    cmdline = _process_cmdline(backup_run.process_pid)
    if not cmdline:
        return False
    return all(
        fragment in cmdline
        for fragment in (
            "manage.py",
            "run_backup_job",
            str(backup_run.job_id),
            "--run-id",
            str(backup_run.id),
        )
    )


def _with_db_retry(action, *, default=None, label="database operation"):
    for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
        try:
            return action()
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt == SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                logger.warning("Skipping %s after repeated SQLite lock contention.", label)
                return default
            time.sleep(SQLITE_LOCK_RETRY_SECONDS)


def _with_low_priority(command_parts):
    wrapped = list(command_parts)
    nice_bin = shutil.which("nice")
    if nice_bin:
        wrapped = [nice_bin, "-n", str(BACKUP_NICE_LEVEL), *wrapped]
    ionice_bin = shutil.which("ionice")
    if ionice_bin:
        wrapped = [ionice_bin, "-c3", *wrapped]
    return wrapped


def _lower_current_process_priority():
    try:
        os.nice(BACKUP_NICE_LEVEL)
    except OSError:
        logger.warning("Could not lower backup worker nice level.", exc_info=True)


def _backup_runtime_root():
    db_path = os.getenv("DJANGO_DB_PATH", "/app/data/db.sqlite3")
    runtime_root = Path(db_path).resolve().parent / "backup_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root


def _runtime_state_path(run_id):
    return _backup_runtime_root() / f"run_{int(run_id)}.json"


def _runtime_stop_path(run_id):
    return _backup_runtime_root() / f"run_{int(run_id)}.stop"


def _write_runtime_state(run_id, payload):
    runtime_path = _runtime_state_path(run_id)
    tmp_path = runtime_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(runtime_path)


def _load_runtime_state(run_id):
    runtime_path = _runtime_state_path(run_id)
    if not runtime_path.exists():
        return None
    try:
        return json.loads(runtime_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get_runtime_state(run_id):
    return _load_runtime_state(run_id)


def _remove_runtime_files(run_id):
    for path in (_runtime_state_path(run_id), _runtime_stop_path(run_id)):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("Could not remove backup runtime file %s", path, exc_info=True)


def _request_runtime_stop(run_id):
    try:
        _runtime_stop_path(run_id).touch()
    except OSError:
        logger.warning("Could not create runtime stop flag for backup run %s", run_id, exc_info=True)


def _runtime_stop_requested(run_id):
    return _runtime_stop_path(run_id).exists()


def _hostfs_path(host_path):
    normalized = os.path.normpath(host_path or "/")
    if not normalized.startswith("/"):
        raise ValueError("Backup paths must be absolute.")
    if normalized.startswith(HOST_ROOT_PREFIX):
        raise ValueError("Use host paths like /home/user, not /hostfs-prefixed paths.")
    return os.path.join(HOST_ROOT_PREFIX, normalized.lstrip("/"))


def _ensure_local_source(job):
    source_path = _hostfs_path(job.source_path)
    if not os.path.isdir(source_path):
        raise FileNotFoundError(f"Source directory not found inside container mapping: {job.source_path}")
    return source_path


def _ensure_remote_pull_destination(job):
    destination_path = _hostfs_path(job.source_path)
    os.makedirs(destination_path, exist_ok=True)
    if not os.path.isdir(destination_path):
        raise FileNotFoundError(f"Local destination directory is not available inside container mapping: {job.source_path}")
    return destination_path


def _host_mounts_file():
    procfs_path = os.getenv("MONITOR_PROCFS_PATH", "/hostfs/proc")
    return os.path.join(procfs_path, "mounts")


def _decode_mount_path(value):
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _mounted_host_paths():
    mounts = set()
    mounts_file = _host_mounts_file()
    try:
        with open(mounts_file, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                mount_path = os.path.normpath(_decode_mount_path(parts[1]))
                if mount_path == HOST_ROOT_PREFIX or mount_path.startswith(f"{HOST_ROOT_PREFIX}/"):
                    mount_path = os.path.normpath("/" + os.path.relpath(mount_path, HOST_ROOT_PREFIX).lstrip("./"))
                mounts.add(mount_path)
    except OSError:
        return set()
    return mounts


def _path_is_on_sensitive_mount(path, mounted_paths=None):
    normalized = os.path.normpath(path)
    if not normalized.startswith(MOUNT_SENSITIVE_ROOTS):
        return True
    mounted_paths = mounted_paths if mounted_paths is not None else _mounted_host_paths()
    for mount_path in mounted_paths:
        if mount_path == "/":
            continue
        if normalized == mount_path or normalized.startswith(f"{mount_path.rstrip('/')}/"):
            return True
    return False


def _local_destination_is_available(job, mounted_paths=None):
    destination_path = os.path.normpath((job.local_dest_path or "").strip() or "/")
    if not destination_path.startswith("/"):
        return False
    if not destination_path.startswith(MOUNT_SENSITIVE_ROOTS):
        return False
    return _path_is_on_sensitive_mount(destination_path, mounted_paths=mounted_paths)


def _local_destination_requires_mount_check(job):
    return bool(getattr(job, "verify_mounted_device", False) or getattr(job, "trigger_on_mount", False))


def _ensure_local_destination(job):
    if not (job.local_dest_path or "").strip():
        raise ValueError("Local backup destination path is required.")
    if _local_destination_requires_mount_check(job):
        mounted_paths = _mounted_host_paths()
        if not _local_destination_is_available(job, mounted_paths=mounted_paths):
            raise RuntimeError(f"Local destination is not mounted right now: {job.local_dest_path}")
    destination_path = _hostfs_path(job.local_dest_path)
    os.makedirs(destination_path, exist_ok=True)
    if not os.path.isdir(destination_path):
        raise FileNotFoundError(f"Local destination directory is not available inside container mapping: {job.local_dest_path}")
    return destination_path


def _proxy_command(job):
    if job.connection_mode != "cloudflare":
        return None
    cloudflared_bin = shutil_which("cloudflared")
    if not cloudflared_bin:
        raise RuntimeError("cloudflared is not installed in the container.")
    service_token_id = (job.cloudflare_service_token_id or "").strip()
    service_token_secret = (job.cloudflare_service_token_secret or "").strip()
    command = f"{cloudflared_bin} access ssh --hostname %h"
    if service_token_id and service_token_secret:
        command = (
            f"{command} "
            f"--service-token-id {shlex.quote(service_token_id)} "
            f"--service-token-secret {shlex.quote(service_token_secret)}"
        )
    return command


def _normalized_remote_host(job):
    raw_host = (job.remote_host or "").strip()
    if not raw_host:
        raise ValueError("Remote host is required.")
    if "://" not in raw_host:
        return raw_host

    parsed = urlparse(raw_host)
    if not parsed.hostname:
        raise ValueError(f"Invalid remote host value: {job.remote_host}")
    if parsed.path and parsed.path not in {"", "/"}:
        raise ValueError(
            "Remote host must be a plain hostname or base URL without a path. "
            f"Received: {job.remote_host}"
        )
    return parsed.hostname


def shutil_which(binary_name):
    return shutil.which(binary_name)


def _ssh_base_cmd(job, *, for_rsync=False):
    ssh_bin = shutil_which("ssh")
    if not ssh_bin:
        raise RuntimeError("ssh is not installed in the container.")
    parts = [ssh_bin, "-o", "StrictHostKeyChecking=accept-new"]
    if job.connection_mode == "cloudflare":
        parts.extend(["-o", f"ProxyCommand={_proxy_command(job)}"])
    else:
        parts.extend(["-p", str(job.ssh_port)])
    if for_rsync:
        return " ".join(shlex.quote(part) for part in parts)
    return parts


def _ssh_target(job):
    return f"{job.remote_user}@{_normalized_remote_host(job)}"


def _remote_rsync_target(job):
    return f"{job.remote_user}@{_normalized_remote_host(job)}:{job.remote_dir.rstrip('/')}/"


def _local_rsync_target(job):
    destination_path = _ensure_local_destination(job)
    return f"{destination_path.rstrip('/')}/"


def _resolve_password(job):
    if job.auth_mode == "password_file":
        password_file_path = _hostfs_path(job.password_file_path)
        if not os.path.isfile(password_file_path):
            raise FileNotFoundError(f"Password file not found: {job.password_file_path}")
        return Path(password_file_path).read_text(encoding="utf-8").strip()
    if job.auth_mode == "password_value":
        if not job.ssh_password:
            raise ValueError("Saved password auth selected but no password was configured.")
        return job.ssh_password
    return ""


def _command_env(job):
    env = os.environ.copy()
    if job.connection_mode != "cloudflare":
        return env

    auth_home = (job.cloudflare_auth_home or "").strip()
    if not auth_home:
        return env

    mapped_home = _hostfs_path(auth_home)
    if not os.path.isdir(mapped_home):
        raise FileNotFoundError(f"Cloudflare auth home not found on host mount: {auth_home}")
    env["HOME"] = mapped_home
    env["XDG_CONFIG_HOME"] = mapped_home
    return env


def _command_with_sshpass(password, command_parts):
    sshpass_bin = shutil_which("sshpass")
    if not sshpass_bin:
        raise RuntimeError("sshpass is not installed in the container.")
    return [sshpass_bin, "-p", password, *command_parts]


def _terminate_process_group(process):
    if process.poll() is not None:
        return process.returncode
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return process.poll()
    except OSError:
        process.terminate()
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return process.poll()
        except OSError:
            process.kill()
        return process.wait(timeout=5)


def _run_command(
    command_parts,
    *,
    env=None,
    timeout_seconds=None,
    idle_timeout_seconds=None,
    heartbeat_callback=None,
    should_stop=None,
):
    result = _run_streaming_command(
        command_parts,
        env=env,
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
    )
    return result.exit_code, result.output


def _run_streaming_command(
    command_parts,
    *,
    env=None,
    on_output=None,
    timeout_seconds=None,
    idle_timeout_seconds=None,
    heartbeat_callback=None,
    should_stop=None,
):
    process = subprocess.Popen(
        command_parts,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=env,
        start_new_session=True,
    )
    collected = []
    buffer = ""
    start_monotonic = time.monotonic()
    last_activity = start_monotonic
    termination_reason = ""
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ)

    try:
        while True:
            if heartbeat_callback:
                heartbeat_callback()
            if should_stop and should_stop():
                termination_reason = "cancelled"
                collected.append("Stop requested. Terminating backup command.")
                if on_output:
                    on_output("Stop requested. Terminating backup command.")
                exit_code = _terminate_process_group(process)
                break

            now = time.monotonic()
            if timeout_seconds and now - start_monotonic > timeout_seconds:
                termination_reason = "timed_out"
                message = f"Backup exceeded timeout of {timeout_seconds} seconds. Terminating command."
                collected.append(message)
                if on_output:
                    on_output(message)
                exit_code = _terminate_process_group(process)
                break
            if idle_timeout_seconds and now - last_activity > idle_timeout_seconds:
                termination_reason = "idle_timed_out"
                message = f"Backup produced no output for {idle_timeout_seconds} seconds. Terminating command."
                collected.append(message)
                if on_output:
                    on_output(message)
                exit_code = _terminate_process_group(process)
                break

            events = selector.select(timeout=1)
            if not events:
                if process.poll() is not None:
                    exit_code = process.returncode
                    break
                continue

            for key, _ in events:
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                last_activity = time.monotonic()
                buffer += chunk.decode("utf-8", errors="replace")
                buffer = _consume_stream_buffer(buffer, collected, on_output)

            if process.poll() is not None and not selector.get_map():
                exit_code = process.returncode
                break
    finally:
        if process.stdout is not None:
            process.stdout.close()
        selector.close()

    trailing = buffer.strip()
    if trailing:
        collected.append(trailing)
        if on_output:
            on_output(trailing)
    output = "\n".join(collected).strip()
    return StreamingCommandResult(exit_code, output[:BACKUP_LOG_LIMIT], termination_reason)


def _cloudflare_error_hint(job, output):
    if job.connection_mode != "cloudflare":
        return None
    lowered = (output or "").lower()
    if "websocket: bad handshake" not in lowered and "unknown port 65535" not in lowered:
        return None
    return (
        "Cloudflare SSH handshake failed. Use only the host name for the remote host field "
        "(for example `ssh.example.com`, not a full `https://...` URL), and make sure that "
        "host is exposed as a Cloudflare SSH target that accepts `cloudflared access ssh --hostname`. "
        "If your host script works thanks to an existing cloudflared session, set `Cloudflare auth home on host` "
        "to the local home that contains `.cloudflared`."
    )


def _job_timeout_seconds(job):
    return max(int(job.run_timeout_seconds or 0), 60)


def _job_idle_timeout_seconds(job):
    return max(int(job.idle_timeout_seconds or 0), 30)


def _rsync_exit_is_partial_success(exit_code):
    return int(exit_code) in RSYNC_PARTIAL_SUCCESS_EXIT_CODES


def _ensure_remote_directory(job, password, *, create=True, heartbeat_callback=None, should_stop=None):
    test_command = [*_ssh_base_cmd(job), _ssh_target(job), f"test -d -- {shlex.quote(job.remote_dir)}"]
    test_parts = _command_with_sshpass(password, test_command) if password else test_command
    test_exit_code, test_output = _run_command(
        test_parts,
        env=_command_env(job),
        timeout_seconds=min(_job_timeout_seconds(job), 300),
        idle_timeout_seconds=min(_job_idle_timeout_seconds(job), 120),
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
    )
    if test_exit_code == 0:
        return False, "Remote source directory exists." if not create else "Remote directory already existed."
    error_hint = _cloudflare_error_hint(job, test_output)
    if error_hint:
        raise RuntimeError(f"{error_hint}\nRemote output: {test_output}")
    if not create:
        raise RuntimeError(f"Remote source directory does not exist: {job.remote_dir}")

    mkdir_command = [*_ssh_base_cmd(job), _ssh_target(job), f"mkdir -p -- {shlex.quote(job.remote_dir)} && echo dir_ok"]
    command_parts = _command_with_sshpass(password, mkdir_command) if password else mkdir_command
    exit_code, output = _run_command(
        command_parts,
        env=_command_env(job),
        timeout_seconds=min(_job_timeout_seconds(job), 300),
        idle_timeout_seconds=min(_job_idle_timeout_seconds(job), 120),
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
    )
    if exit_code != 0:
        error_hint = _cloudflare_error_hint(job, output)
        if error_hint:
            raise RuntimeError(f"{error_hint}\nRemote output: {output}")
        raise RuntimeError(f"Failed to ensure remote directory: {output or exit_code}")
    return True, output


def _install_public_key(job, password, *, heartbeat_callback=None, should_stop=None):
    if not job.install_public_key or not job.public_key_path:
        return ""
    if not password:
        return "Public key installation skipped because no password auth is configured."
    public_key_path = _hostfs_path(job.public_key_path)
    if not os.path.isfile(public_key_path):
        return f"Public key not found at {job.public_key_path}."

    key_text = Path(public_key_path).read_text(encoding="utf-8").strip()
    escaped_key = key_text.replace("'", "'\"'\"'")
    setup_command = [
        *_ssh_base_cmd(job),
        _ssh_target(job),
        "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys",
    ]
    append_command = [
        *_ssh_base_cmd(job),
        _ssh_target(job),
        f"grep -qxF '{escaped_key}' ~/.ssh/authorized_keys || printf '%s\\n' '{escaped_key}' >> ~/.ssh/authorized_keys; echo key_installed",
    ]
    setup_exit, setup_output = _run_command(
        _command_with_sshpass(password, setup_command),
        env=_command_env(job),
        timeout_seconds=min(_job_timeout_seconds(job), 300),
        idle_timeout_seconds=min(_job_idle_timeout_seconds(job), 120),
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
    )
    if setup_exit != 0:
        return f"Public key setup failed: {setup_output}"
    append_exit, append_output = _run_command(
        _command_with_sshpass(password, append_command),
        env=_command_env(job),
        timeout_seconds=min(_job_timeout_seconds(job), 300),
        idle_timeout_seconds=min(_job_idle_timeout_seconds(job), 120),
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
    )
    if append_exit != 0:
        return f"Public key append failed: {append_output}"
    return append_output or "Public key installed."


def _key_auth_works(job, *, heartbeat_callback=None, should_stop=None):
    test_command = [*_ssh_base_cmd(job), _ssh_target(job), "echo key_test"]
    exit_code, _ = _run_command(
        test_command,
        env=_command_env(job),
        timeout_seconds=min(_job_timeout_seconds(job), 180),
        idle_timeout_seconds=min(_job_idle_timeout_seconds(job), 90),
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
    )
    return exit_code == 0


def _rsync_command(job, source_path, password, use_key_auth):
    rsync_bin = shutil_which("rsync")
    if not rsync_bin:
        raise RuntimeError("rsync is not installed in the container.")
    base_cmd = [
        rsync_bin,
        "-rltH",
        "--chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r",
        "--no-owner",
        "--no-group",
        "--no-perms",
        "--no-acls",
        "--no-xattrs",
        "--info=progress2",
        "--stats",
        "--human-readable",
        "--itemize-changes",
    ]
    if job.delete_enabled:
        base_cmd.extend(["--delete", "--delete-after"])
    if job.max_size:
        base_cmd.append(f"--max-size={job.max_size}")
    for pattern in job.exclude_patterns_list:
        base_cmd.extend(["--exclude", pattern])

    if job.is_local:
        return [
            *base_cmd,
            f"{source_path.rstrip('/')}/",
            _local_rsync_target(job),
        ]

    ssh_command = _ssh_base_cmd(job, for_rsync=True)
    ssh_command = f"{ssh_command} -o User={shlex.quote(job.remote_user)}"

    rsync_cmd = [
        *base_cmd,
        "-e",
        ssh_command,
    ]
    if job.is_remote_pull:
        rsync_cmd.extend([_remote_rsync_target(job), f"{source_path.rstrip('/')}/"])
    else:
        rsync_cmd.extend([f"{source_path.rstrip('/')}/", _remote_rsync_target(job)])
    if not use_key_auth:
        return _command_with_sshpass(password, rsync_cmd)
    return rsync_cmd


def run_backup_job(job, *, log_callback=None, heartbeat_callback=None, should_stop=None):
    def push_log(message):
        if log_callback and message:
            log_callback(message)
        if heartbeat_callback:
            heartbeat_callback(force=False)

    _lower_current_process_priority()
    if job.is_http:
        command_line = f"http-sync {job.http_direction} {job.source_path if job.http_direction == 'push' else job.http_remote_path} -> {job.destination_label}"
        log_lines = [
            f"Starting backup job {job.name}",
            f"Type: HTTP server to server backup",
            f"Direction: {job.http_direction}",
            f"Source: {job.source_path if job.http_direction == 'push' else job.http_remote_path}",
            f"Target: {job.destination_label}",
            f"Runner: {_runner_label()}",
            f"Configured timeout: {job.run_timeout_seconds}s",
            f"Configured idle timeout: {job.idle_timeout_seconds}s",
            f"Planned command: {command_line}",
        ]
        for line in log_lines:
            push_log(line)
        started = time.monotonic()
        try:
            stats = sync_http_backup(
                job,
                log_callback=lambda message: log_lines.append(message) or push_log(message),
                heartbeat_callback=heartbeat_callback,
                should_stop=should_stop,
            )
        except InterruptedError:
            summary = "Backup cancelled by operator."
            return BackupExecutionResult(False, DEFAULT_STOP_EXIT_CODE, "cancelled", summary, "\n".join(log_lines), command_line=command_line)
        elapsed = time.monotonic() - started
        if elapsed > _job_timeout_seconds(job):
            summary = f"Backup timed out after {job.run_timeout_seconds}s."
            return BackupExecutionResult(False, DEFAULT_TIMEOUT_EXIT_CODE, "timed_out", summary, "\n".join(log_lines), command_line=command_line)
        failed = stats.get("failed", 0)
        vanished = stats.get("vanished", 0)
        transferred = stats.get("transferred", stats["changed"])
        if failed:
            summary = f"HTTP backup finished with file errors: {transferred}/{stats['changed']} transferred, {failed} failed, {vanished} vanished, {stats['deleted']} deleted, {stats['skipped']} skipped."
            return BackupExecutionResult(False, 1, "failed", summary, "\n".join(log_lines), command_line=command_line)
        summary = f"HTTP backup finished: {transferred}/{stats['changed']} transferred, {vanished} vanished, {stats['deleted']} deleted, {stats['skipped']} skipped."
        return BackupExecutionResult(True, 0, "success", summary, "\n".join(log_lines), command_line=command_line)

    if job.is_local:
        source_path = _ensure_local_source(job)
        normalized_target = job.local_dest_path
        password = ""
        command_preview = _format_command(_with_low_priority(_rsync_command(job, source_path, "", use_key_auth=True)))
    else:
        source_path = _ensure_remote_pull_destination(job) if job.is_remote_pull else _ensure_local_source(job)
        normalized_target = _normalized_remote_host(job)
        password = _resolve_password(job)
        command_preview = _format_command(_with_low_priority(_rsync_command(job, source_path, password, use_key_auth=not bool(password))))
    log_lines = [
        f"Starting backup job {job.name}",
        f"Direction: {'remote SSH to local folder' if job.is_remote_pull else 'local folder to remote SSH directory' if not job.is_local else 'local folder to local folder'}",
        f"Source: {job.source_label}",
        f"Target: {job.destination_label}",
        f"Runner: {_runner_label()}",
        f"Configured timeout: {job.run_timeout_seconds}s",
        f"Configured idle timeout: {job.idle_timeout_seconds}s",
        f"Planned rsync command: {command_preview}",
    ]
    if not job.is_local and job.connection_mode == "cloudflare":
        auth_home = (job.cloudflare_auth_home or "").strip()
        if auth_home:
            log_lines.append(f"Cloudflare auth home: {auth_home}")
        elif job.cloudflare_service_token_id and job.cloudflare_service_token_secret:
            log_lines.append("Cloudflare auth: service token pair configured.")
        else:
            log_lines.append("Cloudflare auth: relying on container default cloudflared state.")
    for line in log_lines:
        push_log(line)

    if job.is_local:
        created_remote_dir = False
        ensure_output = f"Local destination ready: {job.local_dest_path}"
        log_lines.append(ensure_output)
        push_log(ensure_output)
        use_key_auth = True
    else:
        created_remote_dir, ensure_output = _ensure_remote_directory(
            job,
            password if password else "",
            create=not job.is_remote_pull,
            heartbeat_callback=heartbeat_callback,
            should_stop=should_stop,
        )
        if ensure_output:
            log_lines.append(ensure_output)
            push_log(ensure_output)

        public_key_output = _install_public_key(
            job,
            password,
            heartbeat_callback=heartbeat_callback,
            should_stop=should_stop,
        )
        if public_key_output:
            log_lines.append(public_key_output)
            push_log(public_key_output)

        use_key_auth = _key_auth_works(job, heartbeat_callback=heartbeat_callback, should_stop=should_stop)
        auth_message = "Key-based auth works." if use_key_auth else "Key-based auth unavailable, using password mode."
        log_lines.append(auth_message)
        push_log(auth_message)
        if not use_key_auth and not password:
            raise RuntimeError("Key authentication failed and no password-based auth is configured.")

    rsync_cmd = _with_low_priority(_rsync_command(job, source_path, password, use_key_auth))
    push_log(f"Starting rsync transfer with command: {_format_command(rsync_cmd)}")
    transfer_timeout_seconds = None if job.is_local else _job_timeout_seconds(job)
    if job.is_local:
        push_log("Local rsync transfer runs without a hard timeout; it is limited by stop requests and process health.")
    command_result = _run_streaming_command(
        rsync_cmd,
        env=_command_env(job),
        on_output=push_log,
        timeout_seconds=transfer_timeout_seconds,
        # Rsync can legitimately stay quiet for long periods while a large file is
        # transferred over SSH. Using an output-based idle timeout here produces
        # false failures, so only the hard timeout applies to non-local transfers.
        idle_timeout_seconds=None,
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
    )
    if command_result.output:
        log_lines.append(command_result.output)
    if command_result.termination_reason == "cancelled":
        summary = "Backup cancelled by operator."
        return BackupExecutionResult(
            False,
            command_result.exit_code or DEFAULT_STOP_EXIT_CODE,
            "cancelled",
            summary,
            "\n\n".join(log_lines),
            command_line=_format_command(rsync_cmd),
            created_remote_dir=created_remote_dir,
        )
    if command_result.termination_reason in {"timed_out", "idle_timed_out"}:
        summary = (
            f"Backup timed out after {job.run_timeout_seconds}s."
            if command_result.termination_reason == "timed_out"
            else f"Backup stopped after {job.idle_timeout_seconds}s without output."
        )
        return BackupExecutionResult(
            False,
            command_result.exit_code or DEFAULT_TIMEOUT_EXIT_CODE,
            "timed_out",
            summary,
            "\n\n".join(log_lines),
            command_line=_format_command(rsync_cmd),
            created_remote_dir=created_remote_dir,
        )
    if command_result.exit_code == 0:
        summary = f"Backup finished to {job.destination_label}"
        return BackupExecutionResult(
            True,
            command_result.exit_code,
            "success",
            summary,
            "\n\n".join(log_lines),
            command_line=_format_command(rsync_cmd),
            created_remote_dir=created_remote_dir,
        )
    if _rsync_exit_is_partial_success(command_result.exit_code):
        summary = (
            f"Backup finished with warnings (rsync exit code {command_result.exit_code}). "
            "Some files could not be transferred, but rsync continued with the rest."
        )
        return BackupExecutionResult(
            True,
            command_result.exit_code,
            "success",
            summary,
            "\n\n".join(log_lines),
            command_line=_format_command(rsync_cmd),
            created_remote_dir=created_remote_dir,
        )
    summary = f"Backup failed with exit code {command_result.exit_code}"
    return BackupExecutionResult(
        False,
        command_result.exit_code,
        "failed",
        summary,
        "\n\n".join(log_lines),
        command_line=_format_command(rsync_cmd),
        created_remote_dir=created_remote_dir,
    )


def record_backup_run(job, result, *, started_at=None, finished_at=None):
    return BackupRun.objects.create(
        job=job,
        started_at=started_at or timezone.now(),
        finished_at=finished_at or timezone.now(),
        status=result.status,
        exit_code=result.exit_code,
        summary=result.summary,
        log_output=result.log_output[:BACKUP_LOG_LIMIT],
        command_line=result.command_line,
        created_remote_dir=result.created_remote_dir,
        heartbeat_at=finished_at or timezone.now(),
        last_output_at=finished_at or timezone.now(),
        runner_label=_runner_label(),
    )


def create_running_backup_run(job, *, launched_by="manual"):
    now = timezone.now()
    return BackupRun.objects.create(
        job=job,
        started_at=now,
        finished_at=None,
        status="running",
        exit_code=0,
        summary=f"Backup started for {job.name}",
        log_output=f"Backup launched by {launched_by} and is waiting for worker output.",
        created_remote_dir=False,
        launched_by=launched_by,
        heartbeat_at=now,
        runner_label=_runner_label(),
    )


def _runtime_state_from_backup_run(backup_run, *, log_output=None, heartbeat_at=None, last_output_at=None):
    heartbeat_value = heartbeat_at or backup_run.heartbeat_at
    last_output_value = last_output_at or backup_run.last_output_at
    return {
        "id": backup_run.id,
        "status": backup_run.status,
        "summary": backup_run.summary,
        "exit_code": backup_run.exit_code,
        "log_output": (log_output if log_output is not None else backup_run.log_output or "")[-BACKUP_LOG_LIMIT:],
        "process_pid": backup_run.process_pid,
        "runner_label": backup_run.runner_label,
        "command_line": backup_run.command_line or "",
        "heartbeat_at": heartbeat_value.isoformat() if heartbeat_value else None,
        "last_output_at": last_output_value.isoformat() if last_output_value else None,
        "finished_at": backup_run.finished_at.isoformat() if backup_run.finished_at else None,
        "launched_by": backup_run.get_launched_by_display(),
        "status_label": backup_run.get_status_display(),
    }


def mark_backup_run_worker_started(backup_run):
    backup_run.process_pid = os.getpid()
    backup_run.runner_label = _runner_label()
    backup_run.heartbeat_at = timezone.now()
    _with_db_retry(
        lambda: backup_run.save(update_fields=["process_pid", "runner_label", "heartbeat_at"]),
        label="mark backup worker started",
    )
    _write_runtime_state(backup_run.id, _runtime_state_from_backup_run(backup_run))


def stop_requested(run_id, *, last_checked_at=None):
    now_monotonic = time.monotonic()
    if last_checked_at is not None and now_monotonic - last_checked_at < BACKUP_STOP_POLL_INTERVAL_SECONDS:
        return False, last_checked_at
    return _runtime_stop_requested(run_id), now_monotonic


def request_backup_run_stop(backup_run):
    if backup_run.status != "running":
        return False
    backup_run.stop_requested_at = timezone.now()
    backup_run.summary = f"Stop requested for backup '{backup_run.job.name}'."
    _with_db_retry(
        lambda: backup_run.save(update_fields=["stop_requested_at", "summary"]),
        label="request backup stop",
    )
    _request_runtime_stop(backup_run.id)
    if not _backup_worker_matches_run(backup_run):
        result = BackupExecutionResult(
            False,
            DEFAULT_STOP_EXIT_CODE,
            "cancelled",
            f"Backup '{backup_run.job.name}' was cancelled because no active worker process was attached to this run.",
            "\n".join(
                part
                for part in [
                    backup_run.log_output.strip(),
                    "Stop requested after the run lost its worker metadata. Marking it as cancelled.",
                ]
                if part
            ),
            command_line=backup_run.command_line,
            created_remote_dir=backup_run.created_remote_dir,
        )
        finalize_backup_run(backup_run, result, finished_at=timezone.now())
    return True


def _start_periodic_heartbeat(heartbeat_callback):
    if heartbeat_callback is None:
        return None, None
    stop_event = threading.Event()

    def heartbeat_loop():
        while not stop_event.wait(BACKUP_HEARTBEAT_INTERVAL_SECONDS):
            try:
                heartbeat_callback(force=True)
            except Exception:
                logger.exception("Failed to write periodic backup heartbeat.")

    thread = threading.Thread(target=heartbeat_loop, name="backup-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


def _stop_periodic_heartbeat(stop_event, thread):
    if stop_event is None or thread is None:
        return
    stop_event.set()
    thread.join(timeout=2)


def finalize_backup_run(backup_run, result, *, finished_at=None):
    backup_run.status = result.status
    backup_run.exit_code = result.exit_code
    backup_run.summary = result.summary
    backup_run.log_output = result.log_output[:BACKUP_LOG_LIMIT]
    backup_run.created_remote_dir = result.created_remote_dir
    backup_run.command_line = result.command_line
    now = finished_at or timezone.now()
    backup_run.finished_at = now
    backup_run.heartbeat_at = now
    update_fields = [
        "status",
        "exit_code",
        "summary",
        "log_output",
        "created_remote_dir",
        "command_line",
        "finished_at",
        "heartbeat_at",
    ]
    persisted = _with_db_retry(
        lambda: (backup_run.save(update_fields=update_fields) or True),
        default=False,
        label="finalize backup run",
    )
    if not persisted:
        logger.warning(
            "Falling back to direct update for backup run %s after repeated SQLite lock contention.",
            backup_run.id,
        )
        _with_db_retry(
            lambda: BackupRun.objects.filter(pk=backup_run.pk).update(
                status=backup_run.status,
                exit_code=backup_run.exit_code,
                summary=backup_run.summary,
                log_output=backup_run.log_output,
                created_remote_dir=backup_run.created_remote_dir,
                command_line=backup_run.command_line,
                finished_at=backup_run.finished_at,
                heartbeat_at=backup_run.heartbeat_at,
            ),
            label="finalize backup run fallback",
        )
    _write_runtime_state(backup_run.id, _runtime_state_from_backup_run(backup_run))
    _remove_runtime_files(backup_run.id)
    return backup_run


def _advance_job_schedule(job, finished_at):
    job.last_run_at = finished_at
    if job.is_manual:
        job.next_run_at = None
        job.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
        return
    next_run_at = job.next_run_at or finished_at
    cadence = timedelta(minutes=max(job.schedule_minutes, 5))
    while next_run_at <= finished_at:
        next_run_at += cadence
    job.next_run_at = next_run_at
    job.save(update_fields=["last_run_at", "next_run_at", "updated_at"])


def _skip_job_schedule(job, skipped_at):
    if job.is_manual:
        job.next_run_at = None
        job.save(update_fields=["next_run_at", "updated_at"])
        return
    next_run_at = job.next_run_at or skipped_at
    cadence = timedelta(minutes=max(job.schedule_minutes, 5))
    while next_run_at <= skipped_at:
        next_run_at += cadence
    job.next_run_at = next_run_at
    job.save(update_fields=["next_run_at", "updated_at"])


def execute_backup_job(job, *, backup_run=None):
    started_at = timezone.now()
    pending_log_lines = []
    last_log_flush = time.monotonic()
    stop_poll_checked_at = 0.0
    runtime_log_output = (backup_run.log_output if backup_run is not None else "") or ""
    state_lock = threading.RLock()

    def flush_pending_logs(*, force=False):
        nonlocal pending_log_lines, last_log_flush, runtime_log_output
        with state_lock:
            if backup_run is None or not pending_log_lines:
                return
            now_monotonic = time.monotonic()
            if (
                not force
                and len(pending_log_lines) < BACKUP_LOG_FLUSH_MAX_BUFFERED_LINES
                and now_monotonic - last_log_flush < BACKUP_LOG_FLUSH_INTERVAL_SECONDS
            ):
                return
            new_log = "\n".join(part for part in [runtime_log_output.strip(), "\n".join(pending_log_lines).strip()] if part)
            runtime_log_output = new_log[-BACKUP_LOG_LIMIT:]
            now = timezone.now()
            backup_run.heartbeat_at = now
            backup_run.last_output_at = now
            _write_runtime_state(
                backup_run.id,
                _runtime_state_from_backup_run(
                    backup_run,
                    log_output=runtime_log_output,
                    heartbeat_at=backup_run.heartbeat_at,
                    last_output_at=backup_run.last_output_at,
                ),
            )
            pending_log_lines = []
            last_log_flush = now_monotonic

    def buffered_log_callback(message):
        with state_lock:
            pending_log_lines.append(message)
        flush_pending_logs()

    heartbeat_stop_event = None
    heartbeat_thread = None
    try:
        log_callback = None
        if backup_run is not None:
            log_callback = buffered_log_callback
            mark_backup_run_worker_started(backup_run)
            def heartbeat(force=False):
                nonlocal runtime_log_output
                with state_lock:
                    flush_pending_logs(force=force)
                    now = timezone.now()
                    if not force and backup_run.heartbeat_at and (now - backup_run.heartbeat_at).total_seconds() < BACKUP_HEARTBEAT_INTERVAL_SECONDS:
                        return
                    backup_run.heartbeat_at = now
                    _write_runtime_state(
                        backup_run.id,
                        _runtime_state_from_backup_run(
                            backup_run,
                            log_output=runtime_log_output,
                            heartbeat_at=backup_run.heartbeat_at,
                            last_output_at=backup_run.last_output_at,
                        ),
                    )
            def should_stop():
                nonlocal stop_poll_checked_at
                stop_now, stop_poll_checked_at = stop_requested(backup_run.id, last_checked_at=stop_poll_checked_at)
                return stop_now
            heartbeat_stop_event, heartbeat_thread = _start_periodic_heartbeat(heartbeat)
        else:
            heartbeat = None
            should_stop = None
        result = run_backup_job(job, log_callback=log_callback, heartbeat_callback=heartbeat, should_stop=should_stop)
    except Exception as exc:
        flush_pending_logs(force=True)
        error_log = "".join(traceback.format_exception(exc)).strip()
        result = BackupExecutionResult(False, 1, "failed", f"Backup failed: {exc}", error_log)
    finally:
        _stop_periodic_heartbeat(heartbeat_stop_event, heartbeat_thread)
    finished_at = timezone.now()
    if backup_run is None:
        backup_run = record_backup_run(job, result, started_at=started_at, finished_at=finished_at)
    else:
        flush_pending_logs(force=True)
        runtime_text = runtime_log_output.strip()
        result_text = result.log_output.strip()
        if runtime_text:
            combined_parts = [runtime_text]
            if result_text and result_text not in runtime_text:
                combined_parts.append(result_text)
            result.log_output = "\n\n".join(combined_parts)[-BACKUP_LOG_LIMIT:]
        if backup_run.started_at is None:
            backup_run.started_at = started_at
        finalize_backup_run(backup_run, result, finished_at=finished_at)
    _advance_job_schedule(job, finished_at)
    return backup_run


def start_background_backup(job, *, launched_by="manual"):
    backup_run = create_running_backup_run(job, launched_by=launched_by)
    command = _with_low_priority([sys.executable, "manage.py", "run_backup_job", str(job.id), "--run-id", str(backup_run.id)])
    try:
        subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parent.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        failure = BackupExecutionResult(False, 1, "failed", f"Backup could not start: {exc}", str(exc), command_line=_format_command(command))
        finalize_backup_run(backup_run, failure, finished_at=timezone.now())
        raise
    backup_run.command_line = _format_command(command)
    _with_db_retry(lambda: backup_run.save(update_fields=["command_line"]), label="store backup launcher command")
    return backup_run


def mark_stale_running_backups(snapshot_time=None):
    snapshot_time = snapshot_time or timezone.now()
    stale_before = snapshot_time - timedelta(seconds=BACKUP_STALE_AFTER_SECONDS)
    current_runner = _runner_label()
    stale_runs = _with_db_retry(
        lambda: list(BackupRun.objects.select_related("job").filter(status="running")),
        default=[],
        label="load running backup runs",
    )
    updated = []
    for backup_run in stale_runs:
        runtime_state = _load_runtime_state(backup_run.id)
        runtime_heartbeat = None
        runtime_last_output = None
        if runtime_state:
            try:
                runtime_heartbeat = datetime.fromisoformat(runtime_state.get("heartbeat_at")) if runtime_state.get("heartbeat_at") else None
                runtime_last_output = datetime.fromisoformat(runtime_state.get("last_output_at")) if runtime_state.get("last_output_at") else None
            except ValueError:
                runtime_heartbeat = None
                runtime_last_output = None
        runtime_runner = (runtime_state or {}).get("runner_label") or backup_run.runner_label
        timestamps = [value for value in [runtime_last_output, runtime_heartbeat, backup_run.last_output_at, backup_run.heartbeat_at, backup_run.started_at] if value is not None]
        reference_time = max(timestamps) if timestamps else None
        worker_matches = _backup_worker_matches_run(backup_run, current_runner=current_runner) if runtime_runner else False
        if backup_run.stop_requested_at and not worker_matches:
            result = BackupExecutionResult(
                False,
                DEFAULT_STOP_EXIT_CODE,
                "cancelled",
                f"Backup '{backup_run.job.name}' was cancelled after a stop request.",
                "\n".join(
                    part
                    for part in [
                        backup_run.log_output.strip(),
                        "Run reconciled as cancelled because a stop request was pending and no worker process is alive.",
                    ]
                    if part
                ),
                command_line=backup_run.command_line,
                created_remote_dir=backup_run.created_remote_dir,
            )
            finalize_backup_run(backup_run, result, finished_at=snapshot_time)
            updated.append(backup_run)
            continue
        if reference_time is not None and reference_time < stale_before and worker_matches:
            continue
        if reference_time is None or reference_time >= stale_before:
            continue
        summary = f"Backup worker stopped reporting after {reference_time:%Y-%m-%d %H:%M:%S}."
        result = BackupExecutionResult(
            False,
            1,
            "failed",
            summary,
            "\n".join(
                part
                for part in [
                    backup_run.log_output.strip(),
                    "Backup marked as failed because the worker heartbeat became stale.",
                ]
                if part
            ),
            command_line=backup_run.command_line,
            created_remote_dir=backup_run.created_remote_dir,
        )
        finalize_backup_run(backup_run, result, finished_at=snapshot_time)
        updated.append(backup_run)
    return updated


def dispatch_scheduled_backups(snapshot_time=None):
    snapshot_time = snapshot_time or timezone.now()
    try:
        mark_stale_running_backups(snapshot_time)
    except Exception:
        logger.exception("Failed to reconcile stale backup runs.")
    due_jobs = BackupJob.objects.filter(enabled=True, next_run_at__isnull=False, next_run_at__lte=snapshot_time).exclude(schedule_mode="manual").order_by("position", "id")
    mounted_paths = _mounted_host_paths()
    local_jobs = BackupJob.objects.filter(enabled=True, backup_type="local").exclude(schedule_mode="manual").order_by("position", "id")
    runs = []
    for job in local_jobs:
        was_mounted = job.last_mount_was_available
        mounted_now = _local_destination_is_available(job, mounted_paths=mounted_paths)
        fields_to_update = []
        if was_mounted != mounted_now:
            job.last_mount_was_available = mounted_now
            fields_to_update.extend(["last_mount_was_available", "updated_at"])
        if mounted_now and job.trigger_on_mount and not BackupRun.objects.filter(job=job, status="running").exists() and not was_mounted:
            try:
                runs.append(start_background_backup(job, launched_by="scheduler"))
            except Exception:
                logger.exception("Failed to launch mount-triggered local backup job %s.", job.id)
        if fields_to_update:
            job.save(update_fields=fields_to_update)
    for job in due_jobs:
        if BackupRun.objects.filter(job=job, status="running").exists():
            continue
        if (
            job.is_local
            and _local_destination_requires_mount_check(job)
            and not _local_destination_is_available(job, mounted_paths=mounted_paths)
        ):
            _skip_job_schedule(job, snapshot_time)
            continue
        try:
            runs.append(start_background_backup(job, launched_by="scheduler"))
        except Exception:
            logger.exception("Failed to launch scheduled backup job %s.", job.id)
    return runs


def list_browser_roots():
    return _list_browser_roots()


def list_directory_children(host_path):
    return _list_directory_children(host_path)
