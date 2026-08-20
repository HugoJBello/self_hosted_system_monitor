import json

from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie

from main_app.models import MonitoringSettings
from .sessions import DEFAULT_COLS, DEFAULT_ROWS, registry


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


@method_decorator(ensure_csrf_cookie, name="dispatch")
class WebTerminalView(StaffRequiredMixin, View):
    template_name = "terminal_app/web_terminal.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "settings_obj": MonitoringSettings.load(),
                "websocket_path": reverse("monitor:terminal-ws"),
                "terminal_api_start_url": reverse("monitor:terminal-api-start"),
                "terminal_api_close_url_template": reverse("monitor:terminal-api-close", args=["__session_id__"]),
            },
        )


def terminal_websocket_http_view(request):
    return JsonResponse({"detail": "WebSocket endpoint only."}, status=426)


class TerminalApiMixin(StaffRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        self.payload = {}
        if request.body:
            try:
                self.payload = json.loads(request.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return JsonResponse({"detail": "Invalid JSON payload."}, status=400)
        return super().dispatch(request, *args, **kwargs)

    def get_session(self, request, session_id):
        session = registry.get(session_id, user_id=request.user.id)
        if not session:
            raise Http404("Terminal session not found.")
        return session


class TerminalSessionStartView(TerminalApiMixin):
    def post(self, request):
        requested_session_id = str(self.payload.get("session_id", "")).strip()
        session = registry.get(requested_session_id, user_id=request.user.id) if requested_session_id else None
        reused = session is not None
        if not session:
            session = registry.create(
                user_id=request.user.id,
                rows=self.payload.get("rows", DEFAULT_ROWS),
                cols=self.payload.get("cols", DEFAULT_COLS),
            )
        return JsonResponse(
            {
                "session_id": session.id,
                "reused": reused,
                "poll_url": reverse("monitor:terminal-api-poll", args=[session.id]),
                "input_url": reverse("monitor:terminal-api-input", args=[session.id]),
                "resize_url": reverse("monitor:terminal-api-resize", args=[session.id]),
                "close_url": reverse("monitor:terminal-api-close", args=[session.id]),
            }
        )


class TerminalSessionPollView(TerminalApiMixin):
    def get(self, request, session_id):
        session = self.get_session(request, session_id)
        try:
            cursor = int(request.GET.get("cursor", "0"))
        except ValueError:
            cursor = 0
        return JsonResponse(session.read_since(cursor))


class TerminalSessionInputView(TerminalApiMixin):
    def post(self, request, session_id):
        session = self.get_session(request, session_id)
        session.write(self.payload.get("data", ""))
        return JsonResponse({"ok": True, "alive": session.alive})


class TerminalSessionResizeView(TerminalApiMixin):
    def post(self, request, session_id):
        session = self.get_session(request, session_id)
        session.resize(self.payload.get("rows"), self.payload.get("cols"))
        return JsonResponse({"ok": True, "alive": session.alive})


class TerminalSessionCloseView(TerminalApiMixin):
    def post(self, request, session_id):
        registry.close(session_id, user_id=request.user.id)
        return JsonResponse({"ok": True})
