from django.core.management.base import BaseCommand

from file_manager_app.video_preview import prepare_video


class Command(BaseCommand):
    help = "Prepare a browser-compatible video preview and WebVTT subtitles."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **options):
        prepare_video(options["path"])
