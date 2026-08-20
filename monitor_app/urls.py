from django.urls import path

from .views import ProcessActionView, RedirectHomeView, SystemMonitorView, healthz_view


urlpatterns = [
    path("healthz/", healthz_view, name="healthz"),
    path("", RedirectHomeView.as_view(), name="home"),
    path("process-action/", ProcessActionView.as_view(), name="process-action"),
    path("monitor/", SystemMonitorView.as_view(), name="system-monitor"),
]
