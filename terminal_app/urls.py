from django.urls import path

from .views import (
    TerminalSessionCloseView,
    TerminalSessionInputView,
    TerminalSessionPollView,
    TerminalSessionResizeView,
    TerminalSessionStartView,
    WebTerminalView,
    terminal_websocket_http_view,
)


urlpatterns = [
    path("terminal/", WebTerminalView.as_view(), name="web-terminal"),
    path("ws/terminal/", terminal_websocket_http_view, name="terminal-ws"),
    path("terminal/api/start/", TerminalSessionStartView.as_view(), name="terminal-api-start"),
    path("terminal/api/<str:session_id>/poll/", TerminalSessionPollView.as_view(), name="terminal-api-poll"),
    path("terminal/api/<str:session_id>/input/", TerminalSessionInputView.as_view(), name="terminal-api-input"),
    path("terminal/api/<str:session_id>/resize/", TerminalSessionResizeView.as_view(), name="terminal-api-resize"),
    path("terminal/api/<str:session_id>/close/", TerminalSessionCloseView.as_view(), name="terminal-api-close"),
]
