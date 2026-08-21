from django.urls import include, path

from .views import SettingsView

app_name = "monitor"

urlpatterns = [
    path("", include("monitor_app.urls")),
    path("", include("users_app.urls")),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("", include("history_app.urls")),
    path("", include("alerts_app.urls")),
    path("", include("reports_app.urls")),
    path("", include("docker_runtime_app.urls")),
    path("", include("terminal_app.urls")),
    path("", include("file_manager_app.urls")),
    path("", include("volumes_app.urls")),
    path("", include("jobs_app.urls")),
    path("", include("backups_app.urls")),
]
