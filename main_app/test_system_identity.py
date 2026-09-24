import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import MonitoringSettings
from .system_identity import detected_hostname, system_display_name


class SystemIdentityTests(TestCase):
    def test_configured_display_name_wins_and_is_normalized(self):
        self.assertEqual(system_display_name("  Office\n server  "), "Office server")

    def test_detected_hostname_uses_explicit_environment_override(self):
        with patch.dict(os.environ, {"SYSTEM_MONITOR_HOSTNAME": "physical-host"}, clear=False):
            self.assertEqual(detected_hostname(), "physical-host")

    def test_detected_hostname_reads_the_mounted_host_in_docker(self):
        with tempfile.TemporaryDirectory() as root:
            hostname_file = Path(root) / "etc" / "hostname"
            hostname_file.parent.mkdir()
            hostname_file.write_text("host-from-mount\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"MONITOR_ROOT_PATH": root},
                clear=False,
            ):
                with patch.dict(os.environ, {"SYSTEM_MONITOR_HOSTNAME": ""}, clear=False):
                    self.assertEqual(detected_hostname(), "host-from-mount")


@override_settings(FORCE_SCRIPT_NAME=None)
class SystemIdentityViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("admin", password="test-pass", is_staff=True)
        self.client.force_login(user)

    def test_custom_name_is_visible_in_shell_home_and_monitor(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.system_name = "Storage Server"
        settings_obj.save()

        for view_name in ("monitor:home", "monitor:system-monitor"):
            response = self.client.get(reverse(view_name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Storage Server")

    def test_settings_exposes_equipment_name_field(self):
        response = self.client.get(reverse("monitor:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="system_name"')
        self.assertContains(response, "detected host name")
