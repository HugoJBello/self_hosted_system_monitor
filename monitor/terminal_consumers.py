import asyncio
import json
import os
import signal
import struct
import subprocess
import termios
import time
from fcntl import ioctl

from channels.generic.websocket import AsyncWebsocketConsumer

from .terminal_sessions import terminal_command, terminal_idle_timeout


DEFAULT_ROWS = 24
DEFAULT_COLS = 80


class WebTerminalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not user.is_staff:
            await self.close(code=4403)
            return

        self.master_fd = None
        self.process = None
        self.reader_attached = False
        self.last_activity = time.monotonic()
        self.idle_task = None
        await self.accept()
        await self._start_terminal(DEFAULT_ROWS, DEFAULT_COLS)

    async def disconnect(self, close_code):
        await self._cleanup()

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        self.last_activity = time.monotonic()
        try:
            message = json.loads(text_data)
        except json.JSONDecodeError:
            await self._send_status("Invalid terminal message.", level="error")
            return

        message_type = message.get("type")
        if message_type == "input":
            self._write_to_pty(message.get("data", ""))
        elif message_type == "resize":
            self._resize_pty(message.get("rows"), message.get("cols"))
        elif message_type == "ping":
            await self._send_json({"type": "pong"})

    async def _start_terminal(self, rows, cols):
        master_fd, slave_fd = os.openpty()
        self.master_fd = master_fd
        self._resize_pty(rows, cols)

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
        except OSError as exc:
            os.close(slave_fd)
            await self._send_status(f"Unable to start login terminal: {exc}", level="error")
            await self.close(code=1011)
            return
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

        loop = asyncio.get_running_loop()
        loop.add_reader(self.master_fd, self._read_from_pty)
        self.reader_attached = True
        self.idle_task = asyncio.create_task(self._idle_watchdog())
        await self._send_status("Terminal connected. Use the Linux login prompt to continue.")

    def _read_from_pty(self):
        try:
            data = os.read(self.master_fd, 4096)
        except OSError:
            data = b""
        if not data:
            asyncio.create_task(self.close(code=1000))
            return
        asyncio.create_task(self._send_json({"type": "output", "data": data.decode("utf-8", errors="replace")}))

    def _write_to_pty(self, data):
        if self.master_fd is None or not isinstance(data, str):
            return
        try:
            os.write(self.master_fd, data.encode("utf-8", errors="ignore"))
        except OSError:
            asyncio.create_task(self.close(code=1000))

    def _resize_pty(self, rows, cols):
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

    async def _idle_watchdog(self):
        timeout = terminal_idle_timeout()
        while True:
            await asyncio.sleep(30)
            if time.monotonic() - self.last_activity > timeout:
                await self._send_status("Terminal closed after inactivity.", level="warning")
                await self.close(code=4000)
                return

    async def _send_status(self, message, *, level="info"):
        await self._send_json({"type": "status", "level": level, "message": message})

    async def _send_json(self, payload):
        await self.send(text_data=json.dumps(payload))

    async def _cleanup(self):
        if self.idle_task:
            self.idle_task.cancel()
            self.idle_task = None

        if self.reader_attached and self.master_fd is not None:
            try:
                asyncio.get_running_loop().remove_reader(self.master_fd)
            except (OSError, RuntimeError, ValueError):
                pass
            self.reader_attached = False

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
        self.process = None

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
