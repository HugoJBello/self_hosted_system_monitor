import time

from django.conf import settings
from django.core.management.base import BaseCommand

from monitor.backups import dispatch_scheduled_backups
from monitor.script_jobs import dispatch_scheduled_script_jobs


class Command(BaseCommand):
    help = "Continuously dispatch scheduled backup and script jobs outside the sampler process."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting backup and script job scheduler"))
        poll_seconds = max(int(getattr(settings, "BACKUP_SCHEDULER_POLL_SECONDS", 15)), 5)
        while True:
            try:
                dispatch_scheduled_backups()
                dispatch_scheduled_script_jobs()
            except Exception as exc:
                self.stderr.write(f"Backup scheduler error: {exc}")
            time.sleep(poll_seconds)
