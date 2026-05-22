import os
import selectors
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from django.utils import timezone
from django.db import OperationalError

from .models import BackupJob, BackupRun


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
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    cleaned = line.rstrip("\r")
                    if cleaned:
                        collected.append(cleaned)
                        if on_output:
                            on_output(cleaned)

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


def _ensure_remote_directory(job, password, *, heartbeat_callback=None, should_stop=None):
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
        return False, "Remote directory already existed."
    error_hint = _cloudflare_error_hint(job, test_output)
    if error_hint:
        raise RuntimeError(f"{error_hint}\nRemote output: {test_output}")

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

    ssh_command = _ssh_base_cmd(job, for_rsync=True)
    if job.connection_mode == "direct":
        ssh_command = f"{ssh_command} -o User={shlex.quote(job.remote_user)}"
    else:
        ssh_command = f"{ssh_command} -o User={shlex.quote(job.remote_user)}"

    rsync_cmd = [
        *base_cmd,
        "-e",
        ssh_command,
        f"{source_path.rstrip('/')}/",
        _remote_rsync_target(job),
    ]
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
    source_path = _ensure_local_source(job)
    normalized_host = _normalized_remote_host(job)
    password = _resolve_password(job)
    command_preview = _format_command(_with_low_priority(_rsync_command(job, source_path, password, use_key_auth=not bool(password))))
    log_lines = [
        f"Starting backup job {job.name}",
        f"Source: {job.source_path}",
        f"Target: {job.remote_user}@{normalized_host}:{job.remote_dir}",
        f"Runner: {_runner_label()}",
        f"Configured timeout: {job.run_timeout_seconds}s",
        f"Configured idle timeout: {job.idle_timeout_seconds}s",
        f"Planned rsync command: {command_preview}",
    ]
    if job.connection_mode == "cloudflare":
        auth_home = (job.cloudflare_auth_home or "").strip()
        if auth_home:
            log_lines.append(f"Cloudflare auth home: {auth_home}")
        elif job.cloudflare_service_token_id and job.cloudflare_service_token_secret:
            log_lines.append("Cloudflare auth: service token pair configured.")
        else:
            log_lines.append("Cloudflare auth: relying on container default cloudflared state.")
    for line in log_lines:
        push_log(line)

    created_remote_dir, ensure_output = _ensure_remote_directory(
        job,
        password if password else "",
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
    command_result = _run_streaming_command(
        rsync_cmd,
        env=_command_env(job),
        on_output=push_log,
        timeout_seconds=_job_timeout_seconds(job),
        idle_timeout_seconds=_job_idle_timeout_seconds(job),
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
        summary = f"Backup finished to {normalized_host}:{job.remote_dir}"
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


def append_backup_run_log(backup_run, message):
    lines = [part for part in [backup_run.log_output.strip(), message.strip()] if part]
    backup_run.log_output = "\n".join(lines)[-BACKUP_LOG_LIMIT:]
    now = timezone.now()
    backup_run.heartbeat_at = now
    backup_run.last_output_at = now
    _with_db_retry(
        lambda: backup_run.save(update_fields=["log_output", "heartbeat_at", "last_output_at"]),
        label="append backup run log",
    )


def heartbeat_backup_run(backup_run, *, force=False):
    now = timezone.now()
    if not force and backup_run.heartbeat_at and (now - backup_run.heartbeat_at).total_seconds() < BACKUP_HEARTBEAT_INTERVAL_SECONDS:
        return
    backup_run.heartbeat_at = now
    _with_db_retry(lambda: backup_run.save(update_fields=["heartbeat_at"]), label="backup heartbeat")


def mark_backup_run_worker_started(backup_run):
    backup_run.process_pid = os.getpid()
    backup_run.runner_label = _runner_label()
    backup_run.heartbeat_at = timezone.now()
    _with_db_retry(
        lambda: backup_run.save(update_fields=["process_pid", "runner_label", "heartbeat_at"]),
        label="mark backup worker started",
    )


def stop_requested(backup_run):
    return _with_db_retry(
        lambda: BackupRun.objects.filter(pk=backup_run.pk, stop_requested_at__isnull=False).exists(),
        default=False,
        label="check stop requested",
    )


def request_backup_run_stop(backup_run):
    if backup_run.status != "running":
        return False
    backup_run.stop_requested_at = timezone.now()
    backup_run.summary = f"Stop requested for backup '{backup_run.job.name}'."
    _with_db_retry(
        lambda: backup_run.save(update_fields=["stop_requested_at", "summary"]),
        label="request backup stop",
    )
    if not backup_run.process_pid:
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
    _with_db_retry(
        lambda: backup_run.save(
            update_fields=[
                "status",
                "exit_code",
                "summary",
                "log_output",
                "created_remote_dir",
                "command_line",
                "finished_at",
                "heartbeat_at",
            ]
        ),
        label="finalize backup run",
    )
    return backup_run


def _advance_job_schedule(job, finished_at):
    job.last_run_at = finished_at
    next_run_at = job.next_run_at or finished_at
    cadence = timedelta(minutes=max(job.schedule_minutes, 5))
    while next_run_at <= finished_at:
        next_run_at += cadence
    job.next_run_at = next_run_at
    job.save(update_fields=["last_run_at", "next_run_at", "updated_at"])


def execute_backup_job(job, *, backup_run=None):
    started_at = timezone.now()
    pending_log_lines = []
    last_log_flush = time.monotonic()

    def flush_pending_logs(*, force=False):
        nonlocal pending_log_lines, last_log_flush
        if backup_run is None or not pending_log_lines:
            return
        now_monotonic = time.monotonic()
        if (
            not force
            and len(pending_log_lines) < BACKUP_LOG_FLUSH_MAX_BUFFERED_LINES
            and now_monotonic - last_log_flush < BACKUP_LOG_FLUSH_INTERVAL_SECONDS
        ):
            return
        append_backup_run_log(backup_run, "\n".join(pending_log_lines))
        pending_log_lines = []
        last_log_flush = now_monotonic

    def buffered_log_callback(message):
        pending_log_lines.append(message)
        flush_pending_logs()

    try:
        log_callback = None
        if backup_run is not None:
            log_callback = buffered_log_callback
            mark_backup_run_worker_started(backup_run)
            heartbeat = lambda force=False: (flush_pending_logs(force=force), heartbeat_backup_run(backup_run, force=force))
            should_stop = lambda: stop_requested(backup_run)
        else:
            heartbeat = None
            should_stop = None
        result = run_backup_job(job, log_callback=log_callback, heartbeat_callback=heartbeat, should_stop=should_stop)
    except Exception as exc:
        flush_pending_logs(force=True)
        error_log = "".join(traceback.format_exception(exc)).strip()
        result = BackupExecutionResult(False, 1, "failed", f"Backup failed: {exc}", error_log)
    finished_at = timezone.now()
    if backup_run is None:
        backup_run = record_backup_run(job, result, started_at=started_at, finished_at=finished_at)
    else:
        flush_pending_logs(force=True)
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
    stale_runs = _with_db_retry(
        lambda: list(BackupRun.objects.select_related("job").filter(status="running")),
        default=[],
        label="load running backup runs",
    )
    updated = []
    for backup_run in stale_runs:
        reference_time = backup_run.last_output_at or backup_run.heartbeat_at or backup_run.started_at
        if backup_run.stop_requested_at and not _pid_is_alive(backup_run.process_pid):
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
    due_jobs = BackupJob.objects.filter(enabled=True, next_run_at__isnull=False, next_run_at__lte=snapshot_time).order_by("position", "id")
    runs = []
    for job in due_jobs:
        if BackupRun.objects.filter(job=job, status="running").exists():
            continue
        try:
            runs.append(start_background_backup(job, launched_by="scheduler"))
        except Exception:
            logger.exception("Failed to launch scheduled backup job %s.", job.id)
    return runs


def list_browser_roots():
    roots = []
    for root_path in BROWSER_ROOTS:
        absolute_path = _hostfs_path(root_path)
        if os.path.isdir(absolute_path):
            roots.append({"path": root_path, "name": root_path.strip("/") or "/"})
    return roots


def list_directory_children(host_path):
    normalized_path = os.path.normpath(host_path or "/")
    if normalized_path == ".":
        normalized_path = "/"
    absolute_path = _hostfs_path(normalized_path)
    if not os.path.isdir(absolute_path):
        return []

    children = []
    try:
        entries = sorted(os.scandir(absolute_path), key=lambda entry: entry.name.lower())
    except PermissionError:
        return []

    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        relative_path = os.path.join(normalized_path, entry.name).replace("\\", "/")
        if relative_path in EXCLUDED_BROWSER_PATHS:
            continue
        children.append(
            {
                "path": relative_path if relative_path.startswith("/") else f"/{relative_path}",
                "name": entry.name,
            }
        )
    return children
