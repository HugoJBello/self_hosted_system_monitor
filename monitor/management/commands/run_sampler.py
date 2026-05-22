import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError

from monitor.models import MonitoringSettings
from monitor.services import collect_snapshot


class Command(BaseCommand):
    help = "Continuously collect system metrics and store them in SQLite."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting system monitor sampler"))
        while True:
            try:
                collect_snapshot()
                interval = MonitoringSettings.load().sample_interval_seconds
            except OperationalError:
                interval = settings.SAMPLER_DEFAULT_INTERVAL
                self.stdout.write("Database not ready yet, retrying soon.")
            except Exception as exc:
                interval = settings.SAMPLER_DEFAULT_INTERVAL
                self.stderr.write(f"Sampler error: {exc}")
            time.sleep(max(interval, 10))

