from django.conf import settings

from .models import MonitoringSettings
from .features import admin_tool_catalog_for_user, feature_catalog_for_user, feature_keys_for_user
from .system_identity import detected_hostname


def app_shell(request):
    user = getattr(request, "user", None)
    monitoring_settings = MonitoringSettings.load()
    return {
        "app_subpath": settings.APP_SUBPATH,
        "monitoring_settings": monitoring_settings,
        "system_name": monitoring_settings.effective_system_name,
        "detected_system_hostname": detected_hostname(),
        "available_features": feature_catalog_for_user(user) if user and user.is_authenticated else [],
        "admin_tools": admin_tool_catalog_for_user(user) if user and user.is_authenticated else [],
        "allowed_feature_keys": feature_keys_for_user(user) if user and user.is_authenticated else frozenset(),
    }
