from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import render

from main_app.features import ALWAYS_AVAILABLE_URL_NAMES, URL_FEATURES, user_has_feature


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


class FeatureAccessMiddleware:
    """Enforce module grants at the resolved-view boundary, including API routes."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or user.is_staff:
            return None
        match = request.resolver_match
        url_name = match.url_name if match else ""
        if url_name in ALWAYS_AVAILABLE_URL_NAMES:
            return None
        feature = URL_FEATURES.get(url_name, "other")
        if user_has_feature(user, feature):
            return None
        return render(request, "main_app/feature_forbidden.html", {"required_feature": feature}, status=403)
