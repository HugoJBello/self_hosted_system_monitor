from django.utils import timezone
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from .alerting import ensure_default_alert_rules, evaluate_alerts
from .models import AlertEvent, AlertRule, MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, SystemSnapshot
from .reporting import generate_report_for_rule


@override_settings(FORCE_SCRIPT_NAME=None)
class MonitorViewsTests(TestCase):
    def _path(self, name, args=None):
        path = reverse(name, args=args or [])
        return path.replace("/system_monitor", "", 1)

    def _create_snapshot(self, captured_at, **overrides):
        payload = {
            "captured_at": captured_at,
            "hostname": "host",
            "platform_label": "Linux",
            "boot_time": timezone.now(),
            "uptime_seconds": 100,
            "cpu_percent": 50,
            "cpu_count_logical": 4,
            "cpu_count_physical": 2,
            "load_avg_1": 1,
            "load_avg_5": 1,
            "load_avg_15": 1,
            "per_cpu_percent": [50, 50],
            "memory_total_mb": 1000,
            "memory_used_mb": 500,
            "memory_available_mb": 500,
            "memory_percent": 50,
            "swap_total_mb": 100,
            "swap_used_mb": 10,
            "swap_percent": 10,
            "disk_total_gb": 100,
            "disk_used_gb": 50,
            "disk_free_gb": 50,
            "disk_percent": 50,
            "network_sent_mb": 10,
            "network_recv_mb": 10,
            "network_sent_rate_kbps": 10,
            "network_recv_rate_kbps": 10,
            "process_count_total": 100,
            "process_count_running": 10,
            "process_count_sleeping": 80,
            "process_count_stopped": 0,
            "process_count_zombie": 0,
            "process_status_counts": {"running": 10},
            "disk_devices": [],
        }
        payload.update(overrides)
        return SystemSnapshot.objects.create(**payload)

    def test_home_redirects_to_monitor(self):
        response = self.client.get(self._path("monitor:home"))
        self.assertRedirects(response, reverse("monitor:system-monitor"), fetch_redirect_response=False)

    def test_settings_page_uses_singleton(self):
        response = self.client.get(self._path("monitor:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MonitoringSettings.objects.count(), 1)

    def test_settings_update_persists(self):
        response = self.client.post(
            self._path("monitor:settings"),
            {
                "sample_interval_seconds": 120,
                "top_process_limit": 10,
                "history_retention_days": 14,
                "notifications_enabled": "on",
                "notifications_api_url": "http://127.0.0.1:49231/notifications/api/receive/",
                "notifications_api_token": "token-123",
                "notifications_default_channels": "email;telegram",
                "notifications_default_tags": "server;alert",
                "notifications_default_user": "alice",
                "notifications_default_origin": "system-monitor",
                "notifications_default_status": "warning",
                "notifications_default_priority": "high",
                "notifications_default_action": "notify",
                "notifications_timeout_seconds": 15,
            },
        )
        self.assertRedirects(response, reverse("monitor:settings"), fetch_redirect_response=False)
        settings_obj = MonitoringSettings.load()
        self.assertEqual(settings_obj.sample_interval_seconds, 120)
        self.assertEqual(settings_obj.top_process_limit, 10)
        self.assertEqual(settings_obj.history_retention_days, 14)
        self.assertTrue(settings_obj.notifications_enabled)
        self.assertEqual(settings_obj.notifications_default_channels, "email;telegram")

    @patch("monitor.views.send_json_notification")
    def test_settings_can_send_test_notification(self, mock_send_json_notification):
        mock_send_json_notification.return_value = {"ok": True, "status_code": 200, "body": {"ok": True}}
        response = self.client.post(
            self._path("monitor:settings"),
            {
                "sample_interval_seconds": 60,
                "top_process_limit": 8,
                "history_retention_days": 30,
                "notifications_enabled": "on",
                "notifications_api_url": "http://127.0.0.1:49231/notifications/api/receive/",
                "notifications_api_token": "token-123",
                "notifications_default_channels": "email;telegram",
                "notifications_default_tags": "server;alert",
                "notifications_default_user": "alice",
                "notifications_default_origin": "system-monitor",
                "notifications_default_status": "warning",
                "notifications_default_priority": "high",
                "notifications_default_action": "notify",
                "notifications_timeout_seconds": 15,
                "send_test_notification": "1",
            },
        )
        self.assertRedirects(response, reverse("monitor:settings"), fetch_redirect_response=False)
        self.assertTrue(mock_send_json_notification.called)

    def test_alerts_page_loads(self):
        response = self.client.get(self._path("monitor:alerts"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alert configuration")

    def test_alert_detail_page_loads(self):
        rule = AlertRule.objects.create(
            name="CPU hot",
            enabled=True,
            severity="critical",
            metric="cpu_percent",
            evaluation_mode="current",
            comparator="gte",
            threshold=80,
            position=1,
        )
        snapshot = SystemSnapshot.objects.create(
            captured_at=timezone.now(),
            hostname="host",
            platform_label="Linux",
            boot_time=timezone.now(),
            uptime_seconds=100,
            cpu_percent=95,
            cpu_count_logical=4,
            cpu_count_physical=2,
            load_avg_1=2,
            load_avg_5=2,
            load_avg_15=2,
            per_cpu_percent=[95, 94],
            memory_total_mb=1000,
            memory_used_mb=900,
            memory_available_mb=100,
            memory_percent=90,
            swap_total_mb=100,
            swap_used_mb=10,
            swap_percent=10,
            disk_total_gb=100,
            disk_used_gb=50,
            disk_free_gb=50,
            disk_percent=50,
            network_sent_mb=10,
            network_recv_mb=10,
            network_sent_rate_kbps=10,
            network_recv_rate_kbps=10,
            process_count_total=100,
            process_count_running=10,
            process_count_sleeping=80,
            process_count_stopped=0,
            process_count_zombie=0,
            process_status_counts={"running": 10},
            disk_devices=[],
        )
        event = AlertEvent.objects.create(
            rule=rule,
            snapshot=snapshot,
            title="CPU event",
            message="CPU hot",
            severity="critical",
            metric="cpu_percent",
            comparator="gte",
            threshold=80,
            evaluated_value=95,
            matching_count=1,
            sample_count=1,
            window_minutes=1,
        )
        response = self.client.get(self._path("monitor:alert-detail", args=[event.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trigger snapshot")

    def test_history_view_exposes_missing_periods(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.sample_interval_seconds = 60
        settings_obj.save()
        now = timezone.now()
        self._create_snapshot(now - timezone.timedelta(minutes=50), cpu_percent=25)
        self._create_snapshot(now - timezone.timedelta(minutes=10), cpu_percent=75)

        response = self.client.get(self._path("monitor:history"), {"hours": 1})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["chart_data"]["missing_periods"])
        self.assertIn(None, response.context["chart_data"]["cpu"])

    def test_reports_page_loads(self):
        response = self.client.get(self._path("monitor:reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report scheduling")

    def test_report_detail_page_loads(self):
        rule = ReportRule.objects.create(name="Daily summary", period_hours=24, cadence_hours=24, position=1)
        report = ReportRun.objects.create(
            rule=rule,
            title="Daily summary report",
            message="Periodic report",
            window_start=timezone.now() - timezone.timedelta(hours=24),
            window_end=timezone.now(),
            report_data={
                "window_start": "2026-01-01 00:00:00",
                "window_end": "2026-01-02 00:00:00",
                "summary_lines": ["CPU average 42.0%."],
                "aggregates": {"avg_cpu": 42.0, "max_cpu": 80.0, "avg_memory": 38.0, "max_memory": 70.0, "avg_disk": 55.0, "max_disk": 60.0},
                "top_processes": [],
                "chart_data": {"labels": [], "full_labels": [], "has_data": [], "missing_periods": [], "cpu": [], "memory": [], "swap": [], "disk": [], "load": [], "net_sent": [], "net_recv": [], "proc_total": [], "proc_running": []},
                "period_hours": 24,
                "snapshot_count": 10,
            },
        )
        response = self.client.get(self._path("monitor:report-detail", args=[report.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report window")


@override_settings(FORCE_SCRIPT_NAME=None)
class AlertingTests(TestCase):
    def _create_snapshot(self, captured_at, **overrides):
        payload = {
            "captured_at": captured_at,
            "hostname": "host",
            "platform_label": "Linux",
            "boot_time": timezone.now(),
            "uptime_seconds": 100,
            "cpu_percent": 50,
            "cpu_count_logical": 4,
            "cpu_count_physical": 2,
            "load_avg_1": 1,
            "load_avg_5": 1,
            "load_avg_15": 1,
            "per_cpu_percent": [50, 50],
            "memory_total_mb": 1000,
            "memory_used_mb": 500,
            "memory_available_mb": 500,
            "memory_percent": 50,
            "swap_total_mb": 100,
            "swap_used_mb": 10,
            "swap_percent": 10,
            "disk_total_gb": 100,
            "disk_used_gb": 50,
            "disk_free_gb": 50,
            "disk_percent": 50,
            "network_sent_mb": 10,
            "network_recv_mb": 10,
            "network_sent_rate_kbps": 10,
            "network_recv_rate_kbps": 10,
            "process_count_total": 100,
            "process_count_running": 10,
            "process_count_sleeping": 80,
            "process_count_stopped": 0,
            "process_count_zombie": 0,
            "process_status_counts": {"running": 10},
            "disk_devices": [],
        }
        payload.update(overrides)
        return SystemSnapshot.objects.create(**payload)

    def test_default_rules_are_created(self):
        ensure_default_alert_rules()
        self.assertGreater(AlertRule.objects.count(), 0)

    @patch("monitor.alerting.send_json_notification")
    def test_alert_event_created_for_high_cpu(self, mock_send_json_notification):
        mock_send_json_notification.return_value = {"ok": True, "status_code": 200, "body": {"ok": True}}
        settings_obj = MonitoringSettings.load()
        settings_obj.notifications_enabled = True
        settings_obj.notifications_api_url = "http://127.0.0.1:49231/notifications/api/receive/"
        settings_obj.notifications_api_token = "token"
        settings_obj.save()

        rule = AlertRule.objects.create(
            name="CPU hot",
            enabled=True,
            severity="critical",
            metric="cpu_percent",
            evaluation_mode="current",
            comparator="gte",
            threshold=80,
            window_minutes=1,
            min_occurrences=1,
            cooldown_minutes=0,
            notifications_enabled=True,
            position=1,
        )
        snapshot = SystemSnapshot.objects.create(
            captured_at=timezone.now(),
            hostname="host",
            platform_label="Linux",
            boot_time=timezone.now(),
            uptime_seconds=100,
            cpu_percent=95,
            cpu_count_logical=4,
            cpu_count_physical=2,
            load_avg_1=2,
            load_avg_5=2,
            load_avg_15=2,
            per_cpu_percent=[95, 94],
            memory_total_mb=1000,
            memory_used_mb=900,
            memory_available_mb=100,
            memory_percent=90,
            swap_total_mb=100,
            swap_used_mb=10,
            swap_percent=10,
            disk_total_gb=100,
            disk_used_gb=50,
            disk_free_gb=50,
            disk_percent=50,
            network_sent_mb=10,
            network_recv_mb=10,
            network_sent_rate_kbps=10,
            network_recv_rate_kbps=10,
            process_count_total=100,
            process_count_running=10,
            process_count_sleeping=80,
            process_count_stopped=0,
            process_count_zombie=0,
            process_status_counts={"running": 10},
            disk_devices=[],
        )

        evaluate_alerts(snapshot, settings_obj=settings_obj)
        event = AlertEvent.objects.get(rule=rule)
        self.assertTrue(event.is_active)
        self.assertTrue(event.notification_sent)

    def test_active_alert_keeps_original_trigger_snapshot(self):
        settings_obj = MonitoringSettings.load()
        rule = AlertRule.objects.create(
            name="CPU hot",
            enabled=True,
            severity="critical",
            metric="cpu_percent",
            evaluation_mode="current",
            comparator="gte",
            threshold=80,
            cooldown_minutes=0,
            position=1,
        )
        snapshot_one = SystemSnapshot.objects.create(
            captured_at=timezone.now(),
            hostname="host",
            platform_label="Linux",
            boot_time=timezone.now(),
            uptime_seconds=100,
            cpu_percent=95,
            cpu_count_logical=4,
            cpu_count_physical=2,
            load_avg_1=2,
            load_avg_5=2,
            load_avg_15=2,
            per_cpu_percent=[95, 94],
            memory_total_mb=1000,
            memory_used_mb=900,
            memory_available_mb=100,
            memory_percent=90,
            swap_total_mb=100,
            swap_used_mb=10,
            swap_percent=10,
            disk_total_gb=100,
            disk_used_gb=50,
            disk_free_gb=50,
            disk_percent=50,
            network_sent_mb=10,
            network_recv_mb=10,
            network_sent_rate_kbps=10,
            network_recv_rate_kbps=10,
            process_count_total=100,
            process_count_running=10,
            process_count_sleeping=80,
            process_count_stopped=0,
            process_count_zombie=0,
            process_status_counts={"running": 10},
            disk_devices=[],
        )
        evaluate_alerts(snapshot_one, settings_obj=settings_obj)
        event = AlertEvent.objects.get(rule=rule)
        snapshot_two = SystemSnapshot.objects.create(
            captured_at=timezone.now() + timezone.timedelta(minutes=1),
            hostname="host",
            platform_label="Linux",
            boot_time=timezone.now(),
            uptime_seconds=160,
            cpu_percent=96,
            cpu_count_logical=4,
            cpu_count_physical=2,
            load_avg_1=2,
            load_avg_5=2,
            load_avg_15=2,
            per_cpu_percent=[96, 95],
            memory_total_mb=1000,
            memory_used_mb=920,
            memory_available_mb=80,
            memory_percent=92,
            swap_total_mb=100,
            swap_used_mb=10,
            swap_percent=10,
            disk_total_gb=100,
            disk_used_gb=50,
            disk_free_gb=50,
            disk_percent=50,
            network_sent_mb=10,
            network_recv_mb=10,
            network_sent_rate_kbps=10,
            network_recv_rate_kbps=10,
            process_count_total=100,
            process_count_running=10,
            process_count_sleeping=80,
            process_count_stopped=0,
            process_count_zombie=0,
            process_status_counts={"running": 10},
            disk_devices=[],
        )
        evaluate_alerts(snapshot_two, settings_obj=settings_obj)
        event.refresh_from_db()
        self.assertEqual(event.snapshot_id, snapshot_one.id)

    def test_alert_message_includes_top_process_context_for_cpu_metric(self):
        settings_obj = MonitoringSettings.load()
        rule = AlertRule.objects.create(
            name="CPU hot",
            enabled=True,
            severity="critical",
            metric="cpu_percent",
            evaluation_mode="current",
            comparator="gte",
            threshold=80,
            window_minutes=5,
            cooldown_minutes=0,
            position=1,
        )
        snapshot = self._create_snapshot(timezone.now(), cpu_percent=95)
        ProcessSnapshot.objects.create(
            snapshot=snapshot,
            pid=123,
            name="python",
            username="alice",
            status="running",
            cpu_percent=91,
            memory_percent=12,
            memory_rss_mb=256,
            threads=8,
            command="python worker.py",
        )

        evaluate_alerts(snapshot, settings_obj=settings_obj)
        event = AlertEvent.objects.get(rule=rule)
        self.assertIn("Top processes in the evaluation window", event.message)
        self.assertIn("python", event.message)

    @patch("monitor.reporting.send_json_notification")
    def test_generate_report_sends_notification_with_link(self, mock_send_json_notification):
        mock_send_json_notification.return_value = {"ok": True, "status_code": 201, "body": {"ok": True}}
        settings_obj = MonitoringSettings.load()
        settings_obj.notifications_enabled = True
        settings_obj.app_public_base_url = "https://monitor.example.com/system_monitor"
        settings_obj.save()
        rule = ReportRule.objects.create(
            name="Daily summary",
            enabled=True,
            period_hours=24,
            cadence_hours=24,
            send_notifications=True,
            position=1,
        )
        self._create_snapshot(timezone.now(), cpu_percent=55)

        report = generate_report_for_rule(rule, settings_obj=settings_obj, window_end=timezone.now())
        report.refresh_from_db()
        self.assertTrue(report.notification_sent)
        payload = mock_send_json_notification.call_args[0][1]
        self.assertIn("Report link:", payload["message"])
        self.assertIn("/reports/", payload["message"])
