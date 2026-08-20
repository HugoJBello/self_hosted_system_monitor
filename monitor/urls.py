from django.urls import include, path

from .views import SettingsView

app_name = "monitor"

urlpatterns = [
    path("", include("monitor_area.urls")),
    path("", include("users.urls")),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("", include("history.urls")),
    path("", include("alerts.urls")),
    path("", include("reports.urls")),
    path("", include("docker_app.urls")),
    path("", include("terminal_app.urls")),
    path("", include("volumes_app.urls")),
    path("", include("jobs.urls")),
    path("", include("backups_app.urls")),
]
