import json
import logging
import os
import selectors
import shlex
import signal
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from django.db import OperationalError
from django.utils import timezone

from .models import ScriptJob, ScriptJobRun
from .process_control import host_namespace_prefix


logger = logging.getLogger(__name__)
SQLITE_LOCK_RETRY_SECONDS = 0.2
SQLITE_LOCK_RETRY_ATTEMPTS = 5
SCRIPT_LOG_LIMIT = 20000
SCRIPT_HEARTBEAT_INTERVAL_SECONDS = 15
SCRIPT_STALE_AFTER_SECONDS = 180
SCRIPT_LOG_FLUSH_INTERVAL_SECONDS = 2
SCRIPT_LOG_FLUSH_MAX_BUFFERED_LINES = 25
DEFAULT_STOP_EXIT_CODE = 130
DEFAULT_TIMEOUT_EXIT_CODE = 124
SCRIPT_STOP_POLL_INTERVAL_SECONDS = 2


@dataclass
class ScriptExecutionResult:
    ok: bool
    exit_code: int
    status: str
    summary: str
    log_output: str
    command_line: str = ""


@dataclass
class StreamingCommandResult:
    exit_code: int
    output: str
    termination_reason: str = ""


def _runner_label():
    return os.uname().nodename


def _format_command(command_parts):
    return " ".join(shlex.quote(str(part)) for part in command_parts)


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


def _runtime_root():
    db_path = os.getenv("DJANGO_DB_PATH", "/app/data/db.sqlite3")
    runtime_root = Path(db_path).resolve().parent / "script_job_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root


def _runtime_state_path(run_id):
    return _runtime_root() / f"run_{int(run_id)}.json"


def _runtime_stop_path(run_id):
    return _runtime_root() / f"run_{int(run_id)}.stop"


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
            logger.warning("Could not remove script runtime file %s", path, exc_info=True)


def _request_runtime_stop(run_id):
    try:
        _runtime_stop_path(run_id).touch()
    except OSError:
        logger.warning("Could not create runtime stop flag for script run %s", run_id, exc_info=True)


def _runtime_stop_requested(run_id):
    return _runtime_stop_path(run_id).exists()


def _job_timeout_seconds(job):
    return max(int(job.run_timeout_seconds or 0), 30)


def _job_idle_timeout_seconds(job):
    return max(int(job.idle_timeout_seconds or 0), 30)


def _job_cadence(job):
    return job.cadence_delta


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


def _run_streaming_command(
    command_parts,
    *,
    on_output=None,
    timeout_seconds=None,
    idle_timeout_seconds=None,
    heartbeat_callback=None,
    should_stop=None,
    stdin_text=None,
):
    process = subprocess.Popen(
        command_parts,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        bufsize=0,
        start_new_session=True,
    )
    if stdin_text is not None and process.stdin is not None:
        process.stdin.write(stdin_text.encode("utf-8"))
        process.stdin.close()
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
                message = "Stop requested. Terminating script job."
                collected.append(message)
                if on_output:
                    on_output(message)
                exit_code = _terminate_process_group(process)
                break

            now = time.monotonic()
            if timeout_seconds and now - start_monotonic > timeout_seconds:
                termination_reason = "timed_out"
                message = f"Script job exceeded timeout of {timeout_seconds} seconds. Terminating command."
                collected.append(message)
                if on_output:
                    on_output(message)
                exit_code = _terminate_process_group(process)
                break
            if idle_timeout_seconds and now - last_activity > idle_timeout_seconds:
                termination_reason = "idle_timed_out"
                message = f"Script job produced no output for {idle_timeout_seconds} seconds. Terminating command."
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
    return StreamingCommandResult(exit_code, output[-SCRIPT_LOG_LIMIT:], termination_reason)


def _build_script_command(job):
    bash_command = (job.script_body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if job.working_directory:
        bash_command = f"cd {shlex.quote(job.working_directory)} && {bash_command}"
    command = [*host_namespace_prefix()]
    script_arguments = list(job.script_argument_parts)
    bash_argument_tail = ["script-job", *script_arguments]
    if job.run_as_sudo:
        if (job.sudo_password or "").strip():
            command.extend(["sudo", "-S", "-p", "", "/bin/bash", "-lc", bash_command, *bash_argument_tail])
            stdin_text = f"{job.sudo_password}\n"
        else:
            command.extend(["sudo", "-n", "/bin/bash", "-lc", bash_command, *bash_argument_tail])
            stdin_text = None
    else:
        command.extend(["/bin/bash", "-lc", bash_command, *bash_argument_tail])
        stdin_text = None
    return command, stdin_text


def run_script_job(job, *, log_callback=None, heartbeat_callback=None, should_stop=None):
    def push_log(message):
        if log_callback and message:
            log_callback(message)
        if heartbeat_callback:
            heartbeat_callback(force=False)

    command_parts, stdin_text = _build_script_command(job)
    log_lines = [
        f"Starting script job {job.name}",
        f"Runner: {_runner_label()}",
        f"Schedule: {job.schedule_label}",
        f"Working directory: {job.working_directory or '/'}",
        f"Run as sudo: {'yes' if job.run_as_sudo else 'no'}",
        f"Configured timeout: {job.run_timeout_seconds}s",
        f"Configured idle timeout: {job.idle_timeout_seconds}s",
        f"Script arguments: {_format_command(job.script_argument_parts) if job.script_argument_parts else '(none)'}",
        f"Launch command: {_format_command(command_parts)}",
        "Script content:",
        job.script_body,
    ]
    for line in log_lines:
        push_log(line)

    command_result = _run_streaming_command(
        command_parts,
        on_output=push_log,
        timeout_seconds=_job_timeout_seconds(job),
        idle_timeout_seconds=_job_idle_timeout_seconds(job),
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
        stdin_text=stdin_text,
    )
    if command_result.output:
        log_lines.append(command_result.output)
    if command_result.termination_reason == "cancelled":
        return ScriptExecutionResult(
            False,
            command_result.exit_code or DEFAULT_STOP_EXIT_CODE,
            "cancelled",
            "Script job cancelled by operator.",
            "\n\n".join(log_lines),
            command_line=_format_command(command_parts),
        )
    if command_result.termination_reason in {"timed_out", "idle_timed_out"}:
        summary = (
            f"Script job timed out after {job.run_timeout_seconds}s."
            if command_result.termination_reason == "timed_out"
            else f"Script job stopped after {job.idle_timeout_seconds}s without output."
        )
        return ScriptExecutionResult(
            False,
            command_result.exit_code or DEFAULT_TIMEOUT_EXIT_CODE,
            "timed_out",
            summary,
            "\n\n".join(log_lines),
            command_line=_format_command(command_parts),
        )
    if command_result.exit_code == 0:
        return ScriptExecutionResult(
            True,
            0,
            "success",
            "Script job finished successfully.",
            "\n\n".join(log_lines),
            command_line=_format_command(command_parts),
        )
    return ScriptExecutionResult(
        False,
        command_result.exit_code,
        "failed",
        f"Script job failed with exit code {command_result.exit_code}.",
        "\n\n".join(log_lines),
        command_line=_format_command(command_parts),
    )


def create_running_script_run(job, *, launched_by="manual"):
    now = timezone.now()
    return ScriptJobRun.objects.create(
        job=job,
        started_at=now,
        finished_at=None,
        status="running",
        exit_code=0,
        summary=f"Script job started for {job.name}",
        log_output=f"Script job launched by {launched_by} and is waiting for worker output.",
        launched_by=launched_by,
        heartbeat_at=now,
        runner_label=_runner_label(),
    )


def _runtime_state_from_script_run(script_run, *, log_output=None, heartbeat_at=None, last_output_at=None):
    heartbeat_value = heartbeat_at or script_run.heartbeat_at
    last_output_value = last_output_at or script_run.last_output_at
    return {
        "id": script_run.id,
        "status": script_run.status,
        "summary": script_run.summary,
        "exit_code": script_run.exit_code,
        "log_output": (log_output if log_output is not None else script_run.log_output or "")[-SCRIPT_LOG_LIMIT:],
        "process_pid": script_run.process_pid,
        "runner_label": script_run.runner_label,
        "command_line": script_run.command_line or "",
        "heartbeat_at": heartbeat_value.isoformat() if heartbeat_value else None,
        "last_output_at": last_output_value.isoformat() if last_output_value else None,
        "finished_at": script_run.finished_at.isoformat() if script_run.finished_at else None,
        "launched_by": script_run.get_launched_by_display(),
        "status_label": script_run.get_status_display(),
    }


def mark_script_run_worker_started(script_run):
    script_run.process_pid = os.getpid()
    script_run.runner_label = _runner_label()
    script_run.heartbeat_at = timezone.now()
    _with_db_retry(
        lambda: script_run.save(update_fields=["process_pid", "runner_label", "heartbeat_at"]),
        label="mark script worker started",
    )
    _write_runtime_state(script_run.id, _runtime_state_from_script_run(script_run))


def stop_requested(run_id, *, last_checked_at=None):
    now_monotonic = time.monotonic()
    if last_checked_at is not None and now_monotonic - last_checked_at < SCRIPT_STOP_POLL_INTERVAL_SECONDS:
        return False, last_checked_at
    return _runtime_stop_requested(run_id), now_monotonic


def finalize_script_run(script_run, result, *, finished_at=None):
    script_run.status = result.status
    script_run.exit_code = result.exit_code
    script_run.summary = result.summary
    script_run.log_output = result.log_output[-SCRIPT_LOG_LIMIT:]
    script_run.command_line = result.command_line
    now = finished_at or timezone.now()
    script_run.finished_at = now
    script_run.heartbeat_at = now
    _with_db_retry(
        lambda: script_run.save(
            update_fields=[
                "status",
                "exit_code",
                "summary",
                "log_output",
                "command_line",
                "finished_at",
                "heartbeat_at",
            ]
        ),
        label="finalize script run",
    )
    _write_runtime_state(script_run.id, _runtime_state_from_script_run(script_run))
    _remove_runtime_files(script_run.id)
    return script_run


def _advance_job_schedule(job, finished_at):
    job.last_run_at = finished_at
    if job.is_manual:
        job.next_run_at = None
        job.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
        return
    if job.is_one_off:
        job.enabled = False
        job.next_run_at = None
        job.save(update_fields=["enabled", "last_run_at", "next_run_at", "updated_at"])
        return
    next_run_at = job.next_run_at or finished_at
    cadence = _job_cadence(job)
    while next_run_at <= finished_at:
        next_run_at += cadence
    job.next_run_at = next_run_at
    job.save(update_fields=["last_run_at", "next_run_at", "updated_at"])


def request_script_run_stop(script_run):
    if script_run.status != "running":
        return False
    script_run.stop_requested_at = timezone.now()
    script_run.summary = f"Stop requested for script job '{script_run.job.name}'."
    _with_db_retry(
        lambda: script_run.save(update_fields=["stop_requested_at", "summary"]),
        label="request script stop",
    )
    _request_runtime_stop(script_run.id)
    if not script_run.process_pid:
        result = ScriptExecutionResult(
            False,
            DEFAULT_STOP_EXIT_CODE,
            "cancelled",
            f"Script job '{script_run.job.name}' was cancelled because no active worker process was attached to this run.",
            "\n".join(
                part
                for part in [
                    script_run.log_output.strip(),
                    "Stop requested after the run lost its worker metadata. Marking it as cancelled.",
                ]
                if part
            ),
            command_line=script_run.command_line,
        )
        finalize_script_run(script_run, result, finished_at=timezone.now())
    return True


def _start_periodic_heartbeat(heartbeat_callback):
    if heartbeat_callback is None:
        return None, None
    stop_event = threading.Event()

    def heartbeat_loop():
        while not stop_event.wait(SCRIPT_HEARTBEAT_INTERVAL_SECONDS):
            try:
                heartbeat_callback(force=True)
            except Exception:
                logger.exception("Failed to write periodic script heartbeat.")

    thread = threading.Thread(target=heartbeat_loop, name="script-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


def _stop_periodic_heartbeat(stop_event, thread):
    if stop_event is None or thread is None:
        return
    stop_event.set()
    thread.join(timeout=2)


def execute_script_job(job, *, script_run=None):
    started_at = timezone.now()
    pending_log_lines = []
    last_log_flush = time.monotonic()
    stop_poll_checked_at = 0.0
    runtime_log_output = (script_run.log_output if script_run is not None else "") or ""
    state_lock = threading.RLock()

    def flush_pending_logs(*, force=False):
        nonlocal pending_log_lines, last_log_flush, runtime_log_output
        with state_lock:
            if script_run is None or not pending_log_lines:
                return
            now_monotonic = time.monotonic()
            if (
                not force
                and len(pending_log_lines) < SCRIPT_LOG_FLUSH_MAX_BUFFERED_LINES
                and now_monotonic - last_log_flush < SCRIPT_LOG_FLUSH_INTERVAL_SECONDS
            ):
                return
            new_log = "\n".join(part for part in [runtime_log_output.strip(), "\n".join(pending_log_lines).strip()] if part)
            runtime_log_output = new_log[-SCRIPT_LOG_LIMIT:]
            now = timezone.now()
            script_run.heartbeat_at = now
            script_run.last_output_at = now
            _write_runtime_state(
                script_run.id,
                _runtime_state_from_script_run(
                    script_run,
                    log_output=runtime_log_output,
                    heartbeat_at=script_run.heartbeat_at,
                    last_output_at=script_run.last_output_at,
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
        if script_run is not None:
            log_callback = buffered_log_callback
            mark_script_run_worker_started(script_run)

            def heartbeat(force=False):
                nonlocal runtime_log_output
                with state_lock:
                    flush_pending_logs(force=force)
                    now = timezone.now()
                    if not force and script_run.heartbeat_at and (now - script_run.heartbeat_at).total_seconds() < SCRIPT_HEARTBEAT_INTERVAL_SECONDS:
                        return
                    script_run.heartbeat_at = now
                    _write_runtime_state(
                        script_run.id,
                        _runtime_state_from_script_run(
                            script_run,
                            log_output=runtime_log_output,
                            heartbeat_at=script_run.heartbeat_at,
                            last_output_at=script_run.last_output_at,
                        ),
                    )

            def should_stop():
                nonlocal stop_poll_checked_at
                stop_now, stop_poll_checked_at = stop_requested(script_run.id, last_checked_at=stop_poll_checked_at)
                return stop_now

            heartbeat_stop_event, heartbeat_thread = _start_periodic_heartbeat(heartbeat)
        else:
            heartbeat = None
            should_stop = None
        result = run_script_job(job, log_callback=log_callback, heartbeat_callback=heartbeat, should_stop=should_stop)
    except Exception as exc:
        flush_pending_logs(force=True)
        error_log = "".join(traceback.format_exception(exc)).strip()
        result = ScriptExecutionResult(False, 1, "failed", f"Script job failed: {exc}", error_log)
    finally:
        _stop_periodic_heartbeat(heartbeat_stop_event, heartbeat_thread)
    finished_at = timezone.now()
    if script_run is not None:
        flush_pending_logs(force=True)
        runtime_text = runtime_log_output.strip()
        result_text = result.log_output.strip()
        if runtime_text:
            if result_text and runtime_text not in result_text and result_text not in runtime_text:
                result.log_output = "\n\n".join([runtime_text, result_text])[-SCRIPT_LOG_LIMIT:]
            else:
                result.log_output = runtime_text[-SCRIPT_LOG_LIMIT:]
        if script_run.started_at is None:
            script_run.started_at = started_at
        finalize_script_run(script_run, result, finished_at=finished_at)
    else:
        script_run = ScriptJobRun.objects.create(
            job=job,
            started_at=started_at,
            finished_at=finished_at,
            status=result.status,
            exit_code=result.exit_code,
            summary=result.summary,
            log_output=result.log_output[-SCRIPT_LOG_LIMIT:],
            command_line=result.command_line,
            heartbeat_at=finished_at,
            last_output_at=finished_at,
            runner_label=_runner_label(),
        )
    _advance_job_schedule(job, finished_at)
    return script_run


def start_background_script_job(job, *, launched_by="manual"):
    script_run = create_running_script_run(job, launched_by=launched_by)
    command = [sys.executable, "manage.py", "run_script_job", str(job.id), "--run-id", str(script_run.id)]
    try:
        subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parent.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        failure = ScriptExecutionResult(False, 1, "failed", f"Script job could not start: {exc}", str(exc), command_line=_format_command(command))
        finalize_script_run(script_run, failure, finished_at=timezone.now())
        raise
    script_run.command_line = _format_command(command)
    _with_db_retry(lambda: script_run.save(update_fields=["command_line"]), label="store script launcher command")
    return script_run


def mark_stale_running_script_jobs(snapshot_time=None):
    snapshot_time = snapshot_time or timezone.now()
    stale_before = snapshot_time - timedelta(seconds=SCRIPT_STALE_AFTER_SECONDS)
    stale_runs = _with_db_retry(
        lambda: list(ScriptJobRun.objects.select_related("job").filter(status="running")),
        default=[],
        label="load running script runs",
    )
    updated = []
    for script_run in stale_runs:
        runtime_state = _load_runtime_state(script_run.id)
        runtime_heartbeat = None
        runtime_last_output = None
        if runtime_state:
            try:
                runtime_heartbeat = datetime.fromisoformat(runtime_state.get("heartbeat_at")) if runtime_state.get("heartbeat_at") else None
                runtime_last_output = datetime.fromisoformat(runtime_state.get("last_output_at")) if runtime_state.get("last_output_at") else None
            except ValueError:
                runtime_heartbeat = None
                runtime_last_output = None
        timestamps = [value for value in [runtime_last_output, runtime_heartbeat, script_run.last_output_at, script_run.heartbeat_at, script_run.started_at] if value is not None]
        reference_time = max(timestamps) if timestamps else None
        if script_run.stop_requested_at and not _pid_is_alive(script_run.process_pid):
            result = ScriptExecutionResult(
                False,
                DEFAULT_STOP_EXIT_CODE,
                "cancelled",
                f"Script job '{script_run.job.name}' was cancelled after a stop request.",
                "\n".join(
                    part
                    for part in [
                        script_run.log_output.strip(),
                        "Run reconciled as cancelled because a stop request was pending and no worker process is alive.",
                    ]
                    if part
                ),
                command_line=script_run.command_line,
            )
            finalize_script_run(script_run, result, finished_at=snapshot_time)
            updated.append(script_run)
            continue
        if reference_time is not None and reference_time < stale_before and _pid_is_alive(script_run.process_pid):
            continue
        if reference_time is None or reference_time >= stale_before:
            continue
        result = ScriptExecutionResult(
            False,
            1,
            "failed",
            f"Script worker stopped reporting after {reference_time:%Y-%m-%d %H:%M:%S}.",
            "\n".join(
                part
                for part in [
                    script_run.log_output.strip(),
                    "Script job marked as failed because the worker heartbeat became stale.",
                ]
                if part
            ),
            command_line=script_run.command_line,
        )
        finalize_script_run(script_run, result, finished_at=snapshot_time)
        updated.append(script_run)
    return updated


def dispatch_scheduled_script_jobs(snapshot_time=None):
    snapshot_time = snapshot_time or timezone.now()
    try:
        mark_stale_running_script_jobs(snapshot_time)
    except Exception:
        logger.exception("Failed to reconcile stale script job runs.")
    due_jobs = ScriptJob.objects.filter(enabled=True, next_run_at__isnull=False, next_run_at__lte=snapshot_time).exclude(schedule_mode="manual").order_by("position", "id")
    runs = []
    for job in due_jobs:
        if ScriptJobRun.objects.filter(job=job, status="running").exists():
            continue
        try:
            runs.append(start_background_script_job(job, launched_by="scheduler"))
        except Exception:
            logger.exception("Failed to launch scheduled script job %s.", job.id)
    return runs
