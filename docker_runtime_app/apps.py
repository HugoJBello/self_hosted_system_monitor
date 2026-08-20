from django.apps import AppConfig


class DockerAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "docker_runtime_app"
    verbose_name = "Docker"
