import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from file_manager_app.video_preview import _progress_details, probe_video, source_fingerprint, subtitle_artifact


class VideoPreviewTests(SimpleTestCase):
    @patch("file_manager_app.video_preview.subprocess.run")
    def test_probe_identifies_compatible_mp4_and_subtitles(self, run):
        run.return_value.stdout = json.dumps({
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
                {"index": 2, "codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "spa", "title": "Español"}},
            ],
        })

        metadata = probe_video("/video.mp4")

        self.assertTrue(metadata["directly_compatible"])
        self.assertEqual(metadata["subtitles"][0], {"index": 2, "language": "spa", "label": "Español", "codec": "subrip"})

    @patch("file_manager_app.video_preview.subprocess.run")
    def test_probe_marks_matroska_for_compatibility_conversion(self, run):
        run.return_value.stdout = json.dumps({
            "format": {"format_name": "matroska,webm"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "hevc"}],
        })

        self.assertFalse(probe_video("/video.mkv")["directly_compatible"])

    def test_fingerprint_changes_when_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mkv"
            source.write_bytes(b"first")
            first = source_fingerprint(str(source))
            source.write_bytes(b"second version")
            self.assertNotEqual(first, source_fingerprint(str(source)))

    def test_subtitle_artifact_rejects_unlisted_stream(self):
        with tempfile.TemporaryDirectory() as directory, patch("file_manager_app.video_preview.VIDEO_CACHE_DIR", Path(directory)):
            source = Path(directory) / "video.mkv"
            source.write_bytes(b"video")
            self.assertIsNone(subtitle_artifact(str(source), 99))

    def test_progress_reports_percentage_speed_and_eta(self):
        with tempfile.TemporaryDirectory() as directory:
            progress = Path(directory) / "progress.txt"
            progress.write_text("out_time_us=30000000\nspeed=2.0x\nprogress=continue\n", encoding="utf-8")

            details = _progress_details(progress, 120)

            self.assertEqual(details["progress_percent"], 25)
            self.assertEqual(details["eta_seconds"], 45)
            self.assertEqual(details["speed"], "2.0x")
