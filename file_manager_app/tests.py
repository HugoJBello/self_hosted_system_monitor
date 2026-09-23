import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from file_manager_app.access import access_roots, user_can_access_path
from file_manager_app.models import FileShare, FileShareAccessEvent, UserFileAccess


class FileSharingTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("admin-share", password="pass", is_staff=True)
        self.member = get_user_model().objects.create_user("member-share", password="pass")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.host_root = Path(self.temp_dir.name)
        (self.host_root / "shared" / "nested").mkdir(parents=True)
        (self.host_root / "private").mkdir()
        (self.host_root / "shared" / "hello.txt").write_text("hello", encoding="utf-8")
        self.host_patch = patch("volumes_app.path_browser.HOST_ROOT_PATH", str(self.host_root))
        self.host_patch.start()

    def tearDown(self):
        self.host_patch.stop()
        self.temp_dir.cleanup()

    def url(self, name, args=None):
        return reverse(name, args=args or []).replace("/system_monitor", "", 1)

    def test_admin_share_for_user_grants_and_revokes_restricted_access(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("monitor:file-share-create"), {
            "selected_paths": ["/shared"], "name": "Documents", "recipient": self.member.pk,
            "save_share": "1",
        })
        self.assertEqual(response.status_code, 302)
        share = FileShare.objects.get()
        self.assertFalse(share.public_link)
        self.assertTrue(user_can_access_path(self.member, "/shared/nested"))
        self.client.post(self.url("monitor:file-share-detail", [share.pk]), {"revoke": "1"})
        self.assertFalse(user_can_access_path(self.member, "/shared/nested"))

    def test_non_admin_cannot_create_share(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url("monitor:file-share-create"), {"selected_paths": ["/shared"]})
        self.assertEqual(response.status_code, 403)

    def test_public_link_download_is_scoped_and_private_share_requires_user(self):
        share = FileShare.objects.create(created_by=self.admin, paths=["/shared"], public_link=True)
        response = self.client.get(self.url("monitor:file-share-download", [share.token]), {"path": "0/hello.txt"})
        self.assertEqual(response.status_code, 200)
        event = FileShareAccessEvent.objects.get(action="download")
        self.assertEqual(event.path, "0/hello.txt")
        self.assertIsNone(event.user)
        response = self.client.get(self.url("monitor:file-share-download", [share.token]), {"path": "0/../private/missing.txt"})
        self.assertEqual(response.status_code, 404)
        share.public_link = False
        share.recipient = self.member
        share.save()
        self.client.logout()
        self.assertEqual(self.client.get(self.url("monitor:file-share-public", [share.token])).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url("monitor:file-share-public", [share.token])).status_code, 200)
        self.assertTrue(FileShareAccessEvent.objects.filter(share=share, action="view", user=self.member).exists())

    def test_restricted_file_manager_rejects_paths_outside_roots(self):
        UserFileAccess.objects.create(user=self.member, path="/shared", granted_by=self.admin)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url("monitor:file-manager"), {"path": "/shared"}).status_code, 200)
        self.assertEqual(self.client.get(self.url("monitor:file-manager"), {"path": "/private"}).status_code, 403)
        self.assertEqual(access_roots(self.member), ["/shared"])
