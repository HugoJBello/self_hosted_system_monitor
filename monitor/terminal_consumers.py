import asyncio
import json
import time
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer

from .terminal_sessions import DEFAULT_COLS, DEFAULT_ROWS, registry, terminal_idle_timeout


class WebTerminalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not user.is_staff:
            await self.close(code=4403)
            return

        self.user = user
        self.session = None
        self.cursor = 0
        self.last_activity = time.monotonic()
        self.idle_task = None
        self.output_task = None
        await self.accept()
        await self._attach_terminal()

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
            if self.session:
                self.session.write(message.get("data", ""))
        elif message_type == "resize":
            if self.session:
                self.session.resize(message.get("rows"), message.get("cols"))
        elif message_type == "ping":
            if self.session:
                self.session.touch()
            await self._send_json({"type": "pong"})

    async def _attach_terminal(self):
        params = parse_qs(self.scope.get("query_string", b"").decode("utf-8", errors="ignore"))
        requested_session_id = (params.get("session_id") or [""])[0]
        try:
            self.cursor = max(0, int((params.get("cursor") or ["0"])[0]))
        except ValueError:
            self.cursor = 0

        if requested_session_id:
            self.session = registry.get(requested_session_id, user_id=self.user.id)
        reused = self.session is not None
        if not self.session:
            self.session = registry.create(user_id=self.user.id, rows=DEFAULT_ROWS, cols=DEFAULT_COLS)
            self.cursor = 0

        await self._send_json(
            {
                "type": "session",
                "session_id": self.session.id,
                "cursor": self.cursor,
                "reused": reused,
                "idle_timeout_seconds": terminal_idle_timeout(),
            }
        )
        self.idle_task = asyncio.create_task(self._idle_watchdog())
        self.output_task = asyncio.create_task(self._output_loop())
        if reused:
            await self._send_status("Terminal restored.", level="success")
        elif requested_session_id:
            await self._send_status("Previous terminal expired. Started a new login.", level="warning")
        else:
            await self._send_status("Terminal connected. Use the Linux login prompt to continue.")

    async def _output_loop(self):
        while self.session and self.session.alive:
            payload = await asyncio.to_thread(self.session.read_since, self.cursor, timeout=2)
            self.cursor = payload.get("cursor", self.cursor)
            if payload.get("output"):
                await self._send_json({"type": "output", "data": payload["output"], "cursor": self.cursor})
            if not payload.get("alive", False):
                await self._send_status(payload.get("reason") or "Terminal process exited.", level="warning")
                await self.close(code=1000)
                return

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
        if self.output_task:
            self.output_task.cancel()
            self.output_task = None
        self.session = None
