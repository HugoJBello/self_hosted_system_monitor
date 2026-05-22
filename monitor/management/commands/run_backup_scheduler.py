import time

from django.conf import settings
from django.core.management.base import BaseCommand

from monitor.backups import dispatch_scheduled_backups


class Command(BaseCommand):
    help = "Continuously dispatch scheduled backup jobs outside the sampler process."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting backup scheduler"))
        poll_seconds = max(int(getattr(settings, "BACKUP_SCHEDULER_POLL_SECONDS", 15)), 5)
        while True:
            try:
                dispatch_scheduled_backups()
            except Exception as exc:
                self.stderr.write(f"Backup scheduler error: {exc}")
            time.sleep(poll_seconds)
