import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError

from main_app.models import MonitoringSettings
from monitor_app.services import collect_snapshot


class Command(BaseCommand):
    help = "Continuously collect system metrics and store them in SQLite."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting system monitor sampler"))
        while True:
            sleep_seconds = settings.SAMPLER_DEFAULT_INTERVAL
            try:
                collect_snapshot()
                sleep_seconds = max(MonitoringSettings.load().sample_interval_seconds, 10)
            except OperationalError:
                sleep_seconds = 5
                self.stdout.write("Database busy, retrying soon.")
            except Exception as exc:
                sleep_seconds = max(settings.SAMPLER_DEFAULT_INTERVAL, 10)
                self.stderr.write(f"Sampler error: {exc}")
            time.sleep(sleep_seconds)
