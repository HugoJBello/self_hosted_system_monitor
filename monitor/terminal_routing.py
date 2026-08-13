from django.urls import path

from .terminal_consumers import WebTerminalConsumer


websocket_urlpatterns = [
    path("ws/terminal/", WebTerminalConsumer.as_asgi(), name="terminal-ws"),
]
