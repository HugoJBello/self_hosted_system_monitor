from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware


class AppSubpathMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        app_subpath = getattr(settings, "APP_SUBPATH", "")
        path_info = request.path_info
        stripped_prefix = False
        while app_subpath and (path_info == app_subpath or path_info.startswith(f"{app_subpath}/")):
            path_info = path_info[len(app_subpath) :] or "/"
            stripped_prefix = True
        if stripped_prefix:
            request.path_info = path_info
            request.META["PATH_INFO"] = request.path_info
            request.path = f"{app_subpath}{request.path_info}"
        return self.get_response(request)


class RelaxedCsrfViewMiddleware(CsrfViewMiddleware):
    def _origin_verified(self, request):
        if getattr(settings, "CSRF_TRUST_ANY_ORIGIN", False):
            return True
        return super()._origin_verified(request)
