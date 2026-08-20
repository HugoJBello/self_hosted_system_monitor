import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from main_app import terminal_routing


class AppSubpathWebSocketMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        app_subpath = getattr(settings, "APP_SUBPATH", "")
        path = scope.get("path", "")
        while app_subpath and (path == app_subpath or path.startswith(f"{app_subpath}/")):
            path = path[len(app_subpath) :] or "/"
        if path != scope.get("path"):
            scope = {**scope, "path": path}
        return await self.app(scope, receive, send)


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AppSubpathWebSocketMiddleware(
            AllowedHostsOriginValidator(
                AuthMiddlewareStack(
                    URLRouter(terminal_routing.websocket_urlpatterns),
                ),
            ),
        ),
    },
)
