from django.apps import AppConfig


class MainAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "main_app"
    label = "monitor"
    verbose_name = "Main app"

    def ready(self):
        from .db import register_sqlite_pragmas

        register_sqlite_pragmas()
