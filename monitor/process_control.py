import os
import re
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass

import psutil
from django.utils import timezone


HOST_PROCFS_PATH = os.getenv("MONITOR_PROCFS_PATH")
HOST_ROOT_PATH = os.getenv("MONITOR_ROOT_PATH", "/")
if HOST_PROCFS_PATH:
    psutil.PROCFS_PATH = HOST_PROCFS_PATH

_CONTAINER_PID_CACHE = {"timestamp": 0.0, "items": {}}


class ProcessControlError(Exception):
    pass


@dataclass
class CurrentProcess:
    pid: int
    name: str
    username: str
    command: str
    command_argv: list[str]
    create_time: float | None
    cwd: str
    container_id: str = ""
    container_name: str = ""


def _host_path(path):
    path = path or "/"
    if HOST_ROOT_PATH == "/" or path.startswith(HOST_ROOT_PATH):
        return path
    return os.path.join(HOST_ROOT_PATH, path.lstrip("/"))


def _read_host_link(pid, link_name, default="/"):
    link_path = _host_path(f"/proc/{pid}/{link_name}")
    try:
        return os.readlink(link_path)
    except OSError:
        return default


def _nsenter_prefix():
    return ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid"]


def host_namespace_prefix():
    return _nsenter_prefix()


def _run_host_command(command, *, check=True):
    try:
        result = subprocess.run(
            [*_nsenter_prefix(), *command],
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise ProcessControlError("Cannot enter the host namespace because nsenter is not installed.") from exc
    except PermissionError as exc:
        raise ProcessControlError("Permission denied while entering the host namespace.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessControlError(f"Host command timed out: {' '.join(command)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ProcessControlError(detail or f"Host command failed: {' '.join(command)}") from exc
    return result


def _read_host_file(path, default=""):
    try:
        with open(_host_path(path), encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return default


def _container_id_from_cgroup(pid):
    cgroup = _read_host_file(f"/proc/{pid}/cgroup")
    if not cgroup:
        return ""
    patterns = [
        r"docker[-/](?P<id>[0-9a-f]{64})(?:\.scope)?",
        r"docker/(?P<id>[0-9a-f]{64})",
        r"libpod[-/](?P<id>[0-9a-f]{64})(?:\.scope)?",
        r"cri-containerd[-/](?P<id>[0-9a-f]{64})(?:\.scope)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, cgroup)
        if match:
            return match.group("id")
    return ""


def container_name(container_id):
    if not container_id:
        return ""
    try:
        result = _run_host_command(["docker", "inspect", "--format", "{{.Name}}", container_id])
    except ProcessControlError:
        return container_id[:12]
    return result.stdout.strip().lstrip("/") or container_id[:12]


def _docker_container_pid_map():
    now = time.monotonic()
    if now - _CONTAINER_PID_CACHE["timestamp"] < 5:
        return _CONTAINER_PID_CACHE["items"]
    try:
        ids_result = _run_host_command(["docker", "ps", "-q"])
    except ProcessControlError:
        return {}
    container_ids = [line.strip() for line in ids_result.stdout.splitlines() if line.strip()]
    if not container_ids:
        _CONTAINER_PID_CACHE.update({"timestamp": now, "items": {}})
        return {}
    try:
        inspect_result = _run_host_command(
            ["docker", "inspect", "--format", "{{.Id}} {{.State.Pid}} {{.Name}}", *container_ids]
        )
    except ProcessControlError:
        return {}
    items = {}
    for line in inspect_result.stdout.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) != 3:
            continue
        container_id, pid_text, raw_name = parts
        try:
            init_pid = int(pid_text)
        except ValueError:
            continue
        if init_pid > 0:
            items[init_pid] = {
                "id": container_id,
                "name": raw_name.lstrip("/") or container_id[:12],
            }
    _CONTAINER_PID_CACHE.update({"timestamp": now, "items": items})
    return items


def _parent_pid(pid):
    status = _read_host_file(f"/proc/{pid}/status")
    for line in status.splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def _container_from_parent_chain(pid):
    containers_by_init_pid = _docker_container_pid_map()
    current_pid = int(pid)
    visited = set()
    while current_pid > 1 and current_pid not in visited:
        visited.add(current_pid)
        container = containers_by_init_pid.get(current_pid)
        if container:
            return container["id"], container["name"]
        current_pid = _parent_pid(current_pid)
    return "", ""


def container_info_for_pid(pid):
    container_id = _container_id_from_cgroup(pid)
    if not container_id:
        return _container_from_parent_chain(pid)
    return container_id, container_name(container_id)


def get_current_process(pid):
    try:
        process = psutil.Process(int(pid))
        with process.oneshot():
            cmdline = process.cmdline()
            container_id, detected_container_name = container_info_for_pid(process.pid)
            return CurrentProcess(
                pid=process.pid,
                name=process.name() or "",
                username=process.username() or "",
                command=" ".join(cmdline),
                command_argv=cmdline,
                create_time=process.create_time(),
                cwd=_read_host_link(process.pid, "cwd", "/"),
                container_id=container_id,
                container_name=detected_container_name,
            )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError) as exc:
        raise ProcessControlError(f"Process {pid} is not available: {exc}") from exc


def validate_process_identity(pid, *, expected_name="", expected_username="", expected_command="", observed_at=None):
    current = get_current_process(pid)
    expected_name = (expected_name or "").strip()
    expected_username = (expected_username or "").strip()
    expected_command = (expected_command or "").strip()

    if expected_name and current.name != expected_name:
        raise ProcessControlError(f"PID {pid} now belongs to '{current.name}', not '{expected_name}'.")
    if expected_username and current.username != expected_username:
        raise ProcessControlError(f"PID {pid} now runs as '{current.username}', not '{expected_username}'.")
    if expected_command and current.command and current.command != expected_command:
        raise ProcessControlError("PID still exists, but its command line no longer matches the observed process.")
    if observed_at and current.create_time:
        observed_ts = timezone.localtime(observed_at).timestamp() if timezone.is_aware(observed_at) else observed_at.timestamp()
        if current.create_time > observed_ts + 60:
            raise ProcessControlError("PID exists, but it was created after the historical sample. It is probably a reused PID.")
    return current


def signal_process(pid, sig):
    try:
        os.kill(int(pid), sig)
    except ProcessLookupError as exc:
        raise ProcessControlError(f"Process {pid} no longer exists.") from exc
    except PermissionError as exc:
        raise ProcessControlError(f"Permission denied while signalling process {pid}.") from exc


def terminate_process(pid):
    signal_process(pid, signal.SIGTERM)


def kill_process(pid):
    signal_process(pid, signal.SIGKILL)


def restart_process(current_process):
    if not current_process.command:
        raise ProcessControlError("Cannot restart this process because its command line is empty.")

    terminate_process(current_process.pid)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not psutil.pid_exists(current_process.pid):
            break
        time.sleep(0.2)
    if psutil.pid_exists(current_process.pid):
        kill_process(current_process.pid)

    cwd = current_process.cwd or "/"
    command = shlex.join(current_process.command_argv) if current_process.command_argv else current_process.command
    shell_command = f"cd {shlex.quote(cwd)} && exec {command}"
    try:
        subprocess.Popen(
            [*_nsenter_prefix(), "/bin/sh", "-lc", shell_command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise ProcessControlError("Cannot restart process because nsenter is not installed in the web container.") from exc
    except PermissionError as exc:
        raise ProcessControlError("Permission denied while entering the host namespace to restart the process.") from exc


def docker_container_action(container_id, action):
    if not container_id:
        raise ProcessControlError("This process does not belong to a detected Docker container.")
    docker_actions = {
        "restart": "restart",
        "stop": "stop",
        "kill": "kill",
    }
    docker_action = docker_actions.get(action)
    if not docker_action:
        raise ProcessControlError("Unknown Docker container action.")
    _run_host_command(["docker", docker_action, container_id])


def reboot_host():
    commands = [
        [*_nsenter_prefix(), "/bin/systemctl", "reboot"],
        [*_nsenter_prefix(), "/sbin/reboot"],
    ]
    last_error = None
    for command in commands:
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
        except FileNotFoundError as exc:
            last_error = exc
        except PermissionError as exc:
            raise ProcessControlError("Permission denied while requesting host reboot.") from exc
    raise ProcessControlError(f"Cannot request reboot: {last_error}")
