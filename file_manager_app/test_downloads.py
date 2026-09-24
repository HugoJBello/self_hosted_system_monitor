import tempfile
from pathlib import Path

from django.test import RequestFactory, SimpleTestCase

from .downloads import DOWNLOAD_CHUNK_SIZE, MANAGED_DOWNLOAD_THRESHOLD, resumable_download_response


class ResumableDownloadResponseTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name, "example.bin")
        self.path.write_bytes(b"0123456789")
        self.requests = RequestFactory()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def body(response):
        return b"".join(response.streaming_content)

    def test_full_download_advertises_range_and_managed_download_metadata(self):
        response = resumable_download_response(self.requests.get("/download"), self.path, "example.bin")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(response["Content-Length"], "10")
        self.assertEqual(response["X-Download-Chunk-Size"], str(DOWNLOAD_CHUNK_SIZE))
        self.assertEqual(response["X-Managed-Download-Threshold"], str(MANAGED_DOWNLOAD_THRESHOLD))
        self.assertEqual(response["X-Accel-Buffering"], "no")
        self.assertIn("no-transform", response["Cache-Control"])
        self.assertEqual(self.body(response), b"0123456789")

    def test_byte_range_returns_only_requested_chunk(self):
        response = resumable_download_response(
            self.requests.get("/download", HTTP_RANGE="bytes=2-5"),
            self.path,
            "example.bin",
        )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 2-5/10")
        self.assertEqual(response["Content-Length"], "4")
        self.assertEqual(self.body(response), b"2345")

    def test_suffix_range_and_unsatisfiable_range(self):
        suffix = resumable_download_response(
            self.requests.get("/download", HTTP_RANGE="bytes=-3"), self.path, "example.bin"
        )
        invalid = resumable_download_response(
            self.requests.get("/download", HTTP_RANGE="bytes=99-100"), self.path, "example.bin"
        )

        self.assertEqual(suffix["Content-Range"], "bytes 7-9/10")
        self.assertEqual(self.body(suffix), b"789")
        self.assertEqual(invalid.status_code, 416)
        self.assertEqual(invalid["Content-Range"], "bytes */10")

    def test_if_range_mismatch_safely_returns_full_file(self):
        first = resumable_download_response(self.requests.get("/download"), self.path, "example.bin")
        response = resumable_download_response(
            self.requests.get("/download", HTTP_RANGE="bytes=5-9", HTTP_IF_RANGE='"stale"'),
            self.path,
            "example.bin",
        )

        self.assertTrue(first["ETag"])
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Range", response)
        self.assertEqual(self.body(response), b"0123456789")

    def test_head_returns_headers_without_opening_a_response_body(self):
        response = resumable_download_response(self.requests.head("/download"), self.path, "example.bin")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Length"], "10")
        self.assertEqual(self.body(response), b"")
