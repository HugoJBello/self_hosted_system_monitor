from django.core.management.base import BaseCommand, CommandError

from backups_app.services import execute_backup_job
from backups_app.models import BackupJob, BackupRun


class Command(BaseCommand):
    help = "Run one backup job in the background."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int)
        parser.add_argument("--run-id", type=int, default=None)

    def handle(self, *args, **options):
        try:
            job = BackupJob.objects.get(pk=options["job_id"])
        except BackupJob.DoesNotExist as exc:
            raise CommandError(f"Backup job {options['job_id']} does not exist.") from exc

        backup_run = None
        run_id = options.get("run_id")
        if run_id is not None:
            try:
                backup_run = BackupRun.objects.get(pk=run_id, job=job)
            except BackupRun.DoesNotExist as exc:
                raise CommandError(f"Backup run {run_id} does not exist for job {job.id}.") from exc

        execute_backup_job(job, backup_run=backup_run)
        self.stdout.write(self.style.SUCCESS(f"Backup job {job.id} finished."))
