import getpass
import hmac
import os
import shutil
import socket
import sys
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

import crypt


HOST_ROOT = os.getenv("MONITOR_ROOT_PATH", "/hostfs")
DEFAULT_HOST_SSH_NAME = "host.docker.internal"


def host_path(path):
    return os.path.join(HOST_ROOT, path.lstrip("/"))


def read_host_passwd():
    users = {}
    with open(host_path("/etc/passwd"), encoding="utf-8", errors="replace") as passwd_file:
        for line in passwd_file:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split(":")
            if len(parts) < 7:
                continue
            username, _, uid, gid, _, home, shell = parts[:7]
            users[username] = {
                "uid": int(uid),
                "gid": int(gid),
                "home": home,
                "shell": shell,
            }
    return users


def read_host_shadow_hash(username):
    with open(host_path("/etc/shadow"), encoding="utf-8", errors="replace") as shadow_file:
        for line in shadow_file:
            if not line.startswith(f"{username}:"):
                continue
            parts = line.rstrip("\n").split(":")
            if len(parts) >= 2:
                return parts[1]
    return ""


def authenticate(username, password):
    users = read_host_passwd()
    user = users.get(username)
    if not user or user["uid"] < 1000:
        return False

    password_hash = read_host_shadow_hash(username)
    if not password_hash or password_hash in {"!", "*", "x"} or password_hash.startswith("!"):
        return False

    candidate = crypt.crypt(password, password_hash)
    return bool(candidate) and hmac.compare_digest(candidate, password_hash)


def exec_host_shell(username):
    password = os.environ.pop("WEB_TERMINAL_LOGIN_PASSWORD", "")
    if password and ssh_transport_enabled():
        try:
            exec_host_ssh(username, password)
        except OSError:
            pass

    os.execvp(
        "nsenter",
        [
            "nsenter",
            "--target",
            "1",
            "--mount",
            "--uts",
            "--ipc",
            "--net",
            "--pid",
            f"--root={HOST_ROOT}",
            "/bin/su",
            "-",
            username,
        ],
    )


def ssh_transport_enabled():
    return os.getenv("WEB_TERMINAL_HOST_SSH", "true").lower() not in {"0", "false", "no", "off"}


def host_ssh_target():
    configured = os.getenv("WEB_TERMINAL_HOST_SSH_HOST", "").strip()
    if configured:
        return configured
    try:
        socket.getaddrinfo(DEFAULT_HOST_SSH_NAME, 22)
        return DEFAULT_HOST_SSH_NAME
    except socket.gaierror:
        return docker_default_gateway() or DEFAULT_HOST_SSH_NAME


def docker_default_gateway():
    try:
        with open("/proc/net/route", encoding="utf-8") as route_file:
            for line in route_file.readlines()[1:]:
                fields = line.split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    gateway_hex = fields[2]
                    octets = [str(int(gateway_hex[index : index + 2], 16)) for index in range(0, 8, 2)]
                    return ".".join(reversed(octets))
    except OSError:
        return ""
    return ""


def exec_host_ssh(username, password):
    sshpass_bin = shutil.which("sshpass")
    ssh_bin = shutil.which("ssh")
    if not sshpass_bin or not ssh_bin:
        raise OSError("sshpass or ssh is not available.")

    known_hosts = os.getenv("WEB_TERMINAL_SSH_KNOWN_HOSTS", "/app/data/web_terminal_known_hosts")
    env = {
        **os.environ,
        "SSHPASS": password,
    }
    os.execvpe(
        sshpass_bin,
        [
            sshpass_bin,
            "-e",
            ssh_bin,
            "-tt",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            "-o",
            "LogLevel=ERROR",
            f"{username}@{host_ssh_target()}",
        ],
        env,
    )


def main():
    try:
        username = input("login: ").strip()
    except EOFError:
        return 1
    if not username:
        return 1

    try:
        password = getpass.getpass("Password: ")
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n")
        return 1

    try:
        ok = authenticate(username, password)
    except (OSError, ValueError, KeyError):
        ok = False

    if not ok:
        print("Login incorrect")
        return 1

    os.environ["WEB_TERMINAL_LOGIN_PASSWORD"] = password
    exec_host_shell(username)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
