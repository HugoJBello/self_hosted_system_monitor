from django.core.management.base import BaseCommand, CommandError

from file_manager_app.models import FileOperation
from file_manager_app.services import execute_file_operation, finalize_file_operation


class Command(BaseCommand):
    help = "Run a queued file manager operation."

    def add_arguments(self, parser):
        parser.add_argument("operation_id", type=int)

    def handle(self, *args, **options):
        try:
            operation = FileOperation.objects.get(pk=options["operation_id"])
        except FileOperation.DoesNotExist as exc:
            raise CommandError("File operation not found.") from exc
        try:
            execute_file_operation(operation)
        except Exception as exc:
            finalize_file_operation(operation, "failed", f"File operation worker failed: {exc}")
            raise
