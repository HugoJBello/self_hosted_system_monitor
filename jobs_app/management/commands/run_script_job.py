from django.core.management.base import BaseCommand, CommandError

from jobs_app.models import ScriptJob, ScriptJobRun
from jobs_app.services import execute_script_job


class Command(BaseCommand):
    help = "Run one script job in the background."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int)
        parser.add_argument("--run-id", type=int, default=None)

    def handle(self, *args, **options):
        try:
            job = ScriptJob.objects.get(pk=options["job_id"])
        except ScriptJob.DoesNotExist as exc:
            raise CommandError(f"Script job {options['job_id']} does not exist.") from exc

        script_run = None
        run_id = options.get("run_id")
        if run_id is not None:
            try:
                script_run = ScriptJobRun.objects.get(pk=run_id, job=job)
            except ScriptJobRun.DoesNotExist as exc:
                raise CommandError(f"Script run {run_id} does not exist for job {job.id}.") from exc

        execute_script_job(job, script_run=script_run)
        self.stdout.write(self.style.SUCCESS(f"Script job {job.id} finished."))
