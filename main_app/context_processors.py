from django.conf import settings

from .models import MonitoringSettings
from .features import admin_tool_catalog_for_user, feature_catalog_for_user, feature_keys_for_user


def app_shell(request):
    user = getattr(request, "user", None)
    return {
        "app_subpath": settings.APP_SUBPATH,
        "monitoring_settings": MonitoringSettings.load(),
        "available_features": feature_catalog_for_user(user) if user and user.is_authenticated else [],
        "admin_tools": admin_tool_catalog_for_user(user) if user and user.is_authenticated else [],
        "allowed_feature_keys": feature_keys_for_user(user) if user and user.is_authenticated else frozenset(),
    }
