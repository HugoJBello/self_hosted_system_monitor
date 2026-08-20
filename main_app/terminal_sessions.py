import os
import shlex
import signal
import struct
import subprocess
import termios
import threading
import time
import uuid
from collections import deque
from fcntl import ioctl

from django.conf import settings


DEFAULT_ROWS = 24
DEFAULT_COLS = 80
MAX_BUFFER_CHUNKS = 2000


def terminal_command():
    configured = os.getenv("WEB_TERMINAL_COMMAND", "").strip()
    if configured:
        return shlex.split(configured)

    host_root = os.getenv("MONITOR_ROOT_PATH", "/hostfs")
    if os.path.exists(os.path.join(host_root, "etc", "shadow")):
        return ["python", "-m", "main_app.terminal_login"]
    return ["/bin/login"]


def terminal_idle_timeout():
    return max(600, int(getattr(settings, "WEB_TERMINAL_IDLE_TIMEOUT_SECONDS", 600)))


class TerminalSession:
    def __init__(self, *, rows=DEFAULT_ROWS, cols=DEFAULT_COLS):
        self.id = uuid.uuid4().hex
        self.master_fd = None
        self.process = None
        self.last_activity = time.monotonic()
        self.created_at = self.last_activity
        self.closed = False
        self.close_reason = ""
        self._condition = threading.Condition()
        self._chunks = deque(maxlen=MAX_BUFFER_CHUNKS)
        self._next_sequence = 1
        self._reader_thread = None
        self._start(rows, cols)

    def _start(self, rows, cols):
        master_fd, slave_fd = os.openpty()
        self.master_fd = master_fd
        self.resize(rows, cols)

        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LANG": os.getenv("LANG", "C.UTF-8"),
        }

        def prepare_child():
            os.setsid()
            ioctl(slave_fd, termios.TIOCSCTTY, 0)

        try:
            self.process = subprocess.Popen(
                terminal_command(),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=prepare_child,
                close_fds=True,
                env=env,
            )
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

        self._reader_thread = threading.Thread(target=self._reader_loop, name=f"terminal-reader-{self.id}", daemon=True)
        self._reader_thread.start()

    @property
    def alive(self):
        return not self.closed and self.process is not None and self.process.poll() is None

    def touch(self):
        self.last_activity = time.monotonic()

    def read_since(self, cursor, *, timeout=20):
        deadline = time.monotonic() + timeout
        with self._condition:
            while self.alive and not self._has_output_after(cursor):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

            chunks = [(sequence, data) for sequence, data in self._chunks if sequence > cursor]
            next_cursor = chunks[-1][0] if chunks else cursor
            return {
                "output": "".join(data for _, data in chunks),
                "cursor": next_cursor,
                "alive": self.alive,
                "reason": self.close_reason,
            }

    def write(self, data):
        self.touch()
        if self.master_fd is None or not isinstance(data, str):
            return
        try:
            os.write(self.master_fd, data.encode("utf-8", errors="ignore"))
        except OSError:
            self.close("Terminal closed.")

    def resize(self, rows, cols):
        if self.master_fd is None:
            return
        try:
            rows = max(8, min(int(rows), 200))
            cols = max(20, min(int(cols), 400))
        except (TypeError, ValueError):
            rows, cols = DEFAULT_ROWS, DEFAULT_COLS
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            ioctl(self.master_fd, termios.TIOCSWINSZ, packed)
        except OSError:
            pass

    def close(self, reason="Terminal closed."):
        with self._condition:
            if self.closed:
                return
            self.closed = True
            self.close_reason = reason

        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        with self._condition:
            self._condition.notify_all()

    def _reader_loop(self):
        while True:
            try:
                data = os.read(self.master_fd, 4096)
            except OSError:
                data = b""
            if not data:
                self.close("Terminal process exited.")
                return
            text = data.decode("utf-8", errors="replace")
            with self._condition:
                self._chunks.append((self._next_sequence, text))
                self._next_sequence += 1
                self._condition.notify_all()

    def _has_output_after(self, cursor):
        return bool(self._chunks and self._chunks[-1][0] > cursor)


class TerminalSessionRegistry:
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, name="terminal-session-cleanup", daemon=True)
        self._cleanup_thread.start()

    def create(self, *, user_id, rows=DEFAULT_ROWS, cols=DEFAULT_COLS):
        session = TerminalSession(rows=rows, cols=cols)
        with self._lock:
            self._sessions[session.id] = {"session": session, "user_id": user_id}
        return session

    def get(self, session_id, *, user_id):
        with self._lock:
            item = self._sessions.get(session_id)
        if not item or item["user_id"] != user_id:
            return None
        session = item["session"]
        session.touch()
        return session

    def close(self, session_id, *, user_id, reason="Terminal closed."):
        session = self.get(session_id, user_id=user_id)
        if session:
            session.close(reason)
        with self._lock:
            self._sessions.pop(session_id, None)

    def _cleanup_loop(self):
        while True:
            time.sleep(30)
            now = time.monotonic()
            expired = []
            with self._lock:
                for session_id, item in self._sessions.items():
                    session = item["session"]
                    if not session.alive or now - session.last_activity > terminal_idle_timeout():
                        expired.append(session_id)
            for session_id in expired:
                with self._lock:
                    item = self._sessions.pop(session_id, None)
                if item:
                    item["session"].close("Terminal closed after inactivity.")


registry = TerminalSessionRegistry()
