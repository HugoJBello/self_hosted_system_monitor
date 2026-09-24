from django.urls import include, path
from django.views.generic import RedirectView

from .views import HomeView, SettingsView

app_name = "monitor"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("access/", RedirectView.as_view(pattern_name="monitor:home", permanent=False), name="access-home"),
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
