from django.conf import settings

from .models import MonitoringSettings


def app_shell(request):
    return {
        "app_subpath": settings.APP_SUBPATH,
        "monitoring_settings": MonitoringSettings.load(),
    }
