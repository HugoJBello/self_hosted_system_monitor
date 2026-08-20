from django.core.management.base import BaseCommand, CommandError

from volumes_app.models import VolumeOperation
from volumes_app.services import execute_volume_operation


class Command(BaseCommand):
    help = "Run one volume operation in the background."

    def add_arguments(self, parser):
        parser.add_argument("operation_id", type=int)

    def handle(self, *args, **options):
        try:
            operation = VolumeOperation.objects.get(pk=options["operation_id"])
        except VolumeOperation.DoesNotExist as exc:
            raise CommandError(f"Volume operation {options['operation_id']} does not exist.") from exc

        execute_volume_operation(operation)
        self.stdout.write(self.style.SUCCESS(f"Volume operation {operation.id} finished."))
