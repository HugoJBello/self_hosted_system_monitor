from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .sessions import registry, terminal_idle_timeout


class TerminalSessionRegistryTests(SimpleTestCase):
    def test_dead_session_is_not_reported_as_restored(self):
        dead_session = Mock(alive=False)
        item = {"session": dead_session, "user_id": 42}
        with patch.object(registry, "_sessions", {"dead-id": item}):
            self.assertIsNone(registry.get("dead-id", user_id=42))
            self.assertNotIn("dead-id", registry._sessions)
        dead_session.touch.assert_not_called()

    @override_settings(WEB_TERMINAL_IDLE_TIMEOUT_SECONDS=600)
    @patch("main_app.models.MonitoringSettings.load")
    def test_persisted_idle_timeout_overrides_environment_default(self, load_settings):
        load_settings.return_value.terminal_idle_timeout_seconds = 7200
        self.assertEqual(terminal_idle_timeout(), 7200)

    @override_settings(WEB_TERMINAL_IDLE_TIMEOUT_SECONDS=120)
    @patch("main_app.models.MonitoringSettings.load")
    def test_idle_timeout_keeps_safe_minimum(self, load_settings):
        load_settings.return_value.terminal_idle_timeout_seconds = 120
        self.assertEqual(terminal_idle_timeout(), 600)
