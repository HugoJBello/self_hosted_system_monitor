from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from main_app.features import FEATURE_KEYS
from main_app.models import UserFeatureAccess


class FeatureAccessTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("feature-admin", password="pass", is_staff=True)
        self.member = get_user_model().objects.create_user("feature-member", password="pass")

    def url(self, name, args=None):
        return reverse(name, args=args or []).replace("/system_monitor", "", 1)

    def test_new_non_admin_starts_without_application_access(self):
        self.assertFalse(UserFeatureAccess.objects.filter(user=self.member).exists())
        self.client.force_login(self.member)
        response = self.client.get(self.url("monitor:access-home"))
        self.assertContains(response, "No applications assigned yet")
        self.assertNotContains(response, 'href="/system_monitor/history/"')

    def test_direct_module_and_api_access_are_denied_without_grant(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url("monitor:history")).status_code, 403)
        self.assertEqual(self.client.get(self.url("monitor:file-manager-list"), {"path": "/"}).status_code, 403)

    def test_one_grant_exposes_only_its_module(self):
        UserFeatureAccess.objects.create(user=self.member, feature="history")
        self.client.force_login(self.member)
        home = self.client.get(self.url("monitor:access-home"))
        self.assertContains(home, "History")
        self.assertNotContains(home, "System monitor")
        self.assertEqual(self.client.get(self.url("monitor:history")).status_code, 200)
        self.assertEqual(self.client.get(self.url("monitor:alerts")).status_code, 403)

    def test_admin_has_every_feature_without_rows(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url("monitor:access-home"))
        for label in ("System monitor", "Files", "Backups"):
            self.assertContains(response, label)
        self.assertEqual(len(FEATURE_KEYS), 9)

    def test_admin_can_update_member_features(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("monitor:users"), {
            "user_id": self.member.pk, "save_feature_access": "1", "features": ["files", "reports", "invalid"],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(UserFeatureAccess.objects.filter(user=self.member).values_list("feature", flat=True)), {"files", "reports"})
