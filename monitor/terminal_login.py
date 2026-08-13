import getpass
import hmac
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

import crypt


HOST_ROOT = os.getenv("MONITOR_ROOT_PATH", "/hostfs")


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

    exec_host_shell(username)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
