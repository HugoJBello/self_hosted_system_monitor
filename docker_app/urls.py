from django.urls import path

from .views import DockerActionView, DockerLogsView, DockerOverviewView


urlpatterns = [
    path("docker/", DockerOverviewView.as_view(), name="docker-overview"),
    path("docker/action/", DockerActionView.as_view(), name="docker-action"),
    path("docker/logs/", DockerLogsView.as_view(), name="docker-logs"),
]
