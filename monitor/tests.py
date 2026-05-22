from django.utils import timezone
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from .alerting import ensure_default_alert_rules, evaluate_alerts
from .backups import StreamingCommandResult, _cloudflare_error_hint, _command_env, _normalized_remote_host, _rsync_exit_is_partial_success, mark_stale_running_backups, request_backup_run_stop, run_backup_job
from .models import AlertEvent, AlertRule, BackupJob, BackupRun, MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, SystemSnapshot
from .reporting import generate_report_for_rule
from .services import collect_snapshot


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

    def test_backups_page_loads(self):
        response = self.client.get(self._path("monitor:backups"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configured backup jobs")

    def test_backup_runs_page_loads(self):
        response = self.client.get(self._path("monitor:backup-runs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All backup runs")

    @patch("monitor.views.start_background_backup")
    def test_backup_run_now_starts_background_process(self, mock_start_background):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            position=1,
        )

        response = self.client.post(self._path("monitor:backups"), {"run_now": str(job.id)})
        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        mock_start_background.assert_called_once()

    @patch("monitor.views.start_background_backup")
    def test_backup_run_now_does_not_duplicate_running_job(self, mock_start_background):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            position=1,
        )
        BackupRun.objects.create(
            job=job,
            status="running",
            summary="Already running",
        )

        response = self.client.post(self._path("monitor:backups"), {"run_now": str(job.id)})
        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        mock_start_background.assert_not_called()

    @patch("monitor.views.start_background_backup")
    def test_backup_rerun_starts_background_process(self, mock_start_background):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            position=1,
        )
        backup_run = BackupRun.objects.create(
            job=job,
            status="failed",
            summary="Backup failed",
        )

        response = self.client.post(self._path("monitor:backups"), {"rerun_run": str(backup_run.id)})
        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        mock_start_background.assert_called_once_with(job, launched_by="manual")

    def test_backup_stop_requests_graceful_shutdown(self):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            position=1,
        )
        backup_run = BackupRun.objects.create(
            job=job,
            status="running",
            summary="Running",
        )

        response = self.client.post(self._path("monitor:backups"), {"stop_run": str(backup_run.id)})
        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        backup_run.refresh_from_db()
        self.assertIsNotNone(backup_run.stop_requested_at)

    def test_backup_run_detail_page_loads(self):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            position=1,
        )
        backup_run = BackupRun.objects.create(
            job=job,
            status="success",
            exit_code=0,
            summary="Backup finished",
            log_output="rsync stats",
        )

        response = self.client.get(self._path("monitor:backup-run-detail", args=[backup_run.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Execution log")


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


class BackupHelpersTests(TestCase):
    def _path(self, name, args=None):
        path = reverse(name, args=args or [])
        return path.replace("/system_monitor", "", 1)

    def test_normalized_remote_host_accepts_plain_hostname(self):
        job = BackupJob(remote_host="ssh.example.com", remote_user="backup", remote_dir="/tmp", source_path="/home/test")
        self.assertEqual(_normalized_remote_host(job), "ssh.example.com")

    def test_normalized_remote_host_strips_scheme_from_base_url(self):
        job = BackupJob(remote_host="https://ssh.example.com", remote_user="backup", remote_dir="/tmp", source_path="/home/test")
        self.assertEqual(_normalized_remote_host(job), "ssh.example.com")

    def test_cloudflare_hint_is_exposed_for_bad_handshake(self):
        job = BackupJob(
            remote_host="https://ssh.example.com",
            remote_user="backup",
            remote_dir="/tmp",
            source_path="/home/test",
            connection_mode="cloudflare",
        )
        hint = _cloudflare_error_hint(job, "websocket: bad handshake\nConnection closed by UNKNOWN port 65535")
        self.assertIn("Cloudflare SSH handshake failed", hint)

    def test_cloudflare_mode_requires_service_tokens(self):
        response = self.client.post(
            self._path("monitor:backups"),
            {
                "create_job": "1",
                "new-name": "CF backup",
                "new-description": "",
                "new-enabled": "on",
                "new-source_path": "/home/test/Documents",
                "new-schedule_minutes": "30",
                "new-remote_host": "ssh.example.com",
                "new-remote_user": "backup",
                "new-remote_dir": "/srv/backups/test",
                "new-ssh_port": "22",
                "new-connection_mode": "cloudflare",
                "new-auth_mode": "password_value",
                "new-ssh_password": "secret",
                "new-cloudflare_auth_home": "",
                "new-cloudflare_service_token_id": "",
                "new-cloudflare_service_token_secret": "",
                "new-password_file_path": "",
                "new-public_key_path": "",
                "new-max_size": "100m",
                "new-run_timeout_seconds": "7200",
                "new-idle_timeout_seconds": "900",
                "new-exclude_patterns": "",
                "new-position": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cloudflare mode needs either a host auth home with an existing cloudflared session or a service token pair.")

    def test_cloudflare_mode_accepts_host_auth_home_without_service_tokens(self):
        response = self.client.post(
            self._path("monitor:backups"),
            {
                "create_job": "1",
                "new-name": "CF backup",
                "new-description": "",
                "new-enabled": "on",
                "new-source_path": "/home/test/Documents",
                "new-schedule_minutes": "30",
                "new-remote_host": "ssh.example.com",
                "new-remote_user": "backup",
                "new-remote_dir": "/srv/backups/test",
                "new-ssh_port": "22",
                "new-connection_mode": "cloudflare",
                "new-auth_mode": "password_value",
                "new-ssh_password": "secret",
                "new-cloudflare_auth_home": "/home/goku",
                "new-cloudflare_service_token_id": "",
                "new-cloudflare_service_token_secret": "",
                "new-password_file_path": "",
                "new-public_key_path": "",
                "new-max_size": "100m",
                "new-run_timeout_seconds": "7200",
                "new-idle_timeout_seconds": "900",
                "new-exclude_patterns": "",
                "new-position": "0",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_cloudflare_command_env_maps_host_home(self):
        job = BackupJob(
            remote_host="ssh.example.com",
            remote_user="backup",
            remote_dir="/tmp",
            source_path="/home/test",
            connection_mode="cloudflare",
            cloudflare_auth_home="/home/goku",
        )
        with patch("monitor.backups.os.path.isdir", return_value=True):
            env = _command_env(job)
        self.assertEqual(env["HOME"], "/hostfs/home/goku")

    def test_request_backup_run_stop_marks_stop_requested(self):
        job = BackupJob.objects.create(
            name="Docs",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
        )
        backup_run = BackupRun.objects.create(job=job, status="running", summary="Running")
        self.assertTrue(request_backup_run_stop(backup_run))
        backup_run.refresh_from_db()
        self.assertIsNotNone(backup_run.stop_requested_at)

    def test_mark_stale_running_backups_fails_orphaned_run(self):
        job = BackupJob.objects.create(
            name="Docs",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
        )
        stale_time = timezone.now() - timezone.timedelta(minutes=10)
        backup_run = BackupRun.objects.create(
            job=job,
            status="running",
            summary="Running",
            started_at=stale_time,
            heartbeat_at=stale_time,
            last_output_at=stale_time,
            log_output="still running",
        )

        updated = mark_stale_running_backups(stale_time + timezone.timedelta(minutes=20))
        backup_run.refresh_from_db()
        self.assertEqual(len(updated), 1)
        self.assertEqual(backup_run.status, "failed")
        self.assertIn("heartbeat became stale", backup_run.log_output)

    def test_rsync_partial_transfer_exit_codes_are_treated_as_non_fatal(self):
        self.assertTrue(_rsync_exit_is_partial_success(23))
        self.assertTrue(_rsync_exit_is_partial_success(24))
        self.assertFalse(_rsync_exit_is_partial_success(12))

    @patch("monitor.backups._command_env", return_value={})
    @patch("monitor.backups._run_streaming_command")
    @patch("monitor.backups._rsync_command", return_value=["rsync", "/src/", "host:/dst/"])
    @patch("monitor.backups._key_auth_works", return_value=True)
    @patch("monitor.backups._install_public_key", return_value="")
    @patch("monitor.backups._ensure_remote_directory", return_value=(False, "Remote directory already existed."))
    @patch("monitor.backups._resolve_password", return_value="")
    @patch("monitor.backups._normalized_remote_host", return_value="backup.example.com")
    @patch("monitor.backups._ensure_local_source", return_value="/hostfs/home/test/Documents")
    def test_main_rsync_transfer_does_not_use_output_idle_timeout(
        self,
        mock_ensure_local_source,
        mock_normalized_remote_host,
        mock_resolve_password,
        mock_ensure_remote_directory,
        mock_install_public_key,
        mock_key_auth_works,
        mock_rsync_command,
        mock_run_streaming_command,
        mock_command_env,
    ):
        job = BackupJob.objects.create(
            name="Docs",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            run_timeout_seconds=7200,
            idle_timeout_seconds=900,
        )
        mock_run_streaming_command.return_value = StreamingCommandResult(0, "", "")

        result = run_backup_job(job)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "success")
        self.assertEqual(mock_run_streaming_command.call_args.kwargs["idle_timeout_seconds"], None)


class MonitoringIsolationTests(TestCase):
    @patch("monitor.services.prune_old_snapshots")
    @patch("monitor.services.dispatch_scheduled_backups", side_effect=RuntimeError("backup scheduler exploded"))
    @patch("monitor.services.dispatch_scheduled_reports")
    @patch("monitor.services.evaluate_alerts")
    @patch("monitor.services._process_rows", return_value={"rows": [], "total": 10, "running": 2, "sleeping": 8, "stopped": 0, "zombie": 0, "status_counts": {"running": 2}})
    @patch("monitor.services._disk_devices", return_value=[])
    @patch("monitor.services._network_stats", return_value={"sent_mb": 1, "recv_mb": 2, "sent_rate_kbps": 3, "recv_rate_kbps": 4})
    @patch("monitor.services._safe_load_avg", return_value=(0.1, 0.2, 0.3))
    @patch("monitor.services.psutil.disk_usage")
    @patch("monitor.services.psutil.swap_memory")
    @patch("monitor.services.psutil.virtual_memory")
    @patch("monitor.services.psutil.cpu_count", side_effect=[4, 2])
    @patch("monitor.services.psutil.cpu_percent", side_effect=[12.5, [12.5, 0.0]])
    @patch("monitor.services.psutil.boot_time", return_value=1_700_000_000)
    def test_backup_failures_do_not_break_snapshot_collection(
        self,
        mock_boot_time,
        mock_cpu_percent,
        mock_cpu_count,
        mock_virtual_memory,
        mock_swap_memory,
        mock_disk_usage,
        mock_load_avg,
        mock_network_stats,
        mock_disk_devices,
        mock_process_rows,
        mock_evaluate_alerts,
        mock_dispatch_reports,
        mock_dispatch_backups,
        mock_prune,
    ):
        class _Memory:
            total = 1024 * 1024 * 1024
            used = 512 * 1024 * 1024
            available = 512 * 1024 * 1024
            percent = 50

        class _Swap:
            total = 256 * 1024 * 1024
            used = 64 * 1024 * 1024
            percent = 25

        class _Disk:
            total = 100 * 1024 * 1024 * 1024
            used = 40 * 1024 * 1024 * 1024
            free = 60 * 1024 * 1024 * 1024
            percent = 40

        mock_virtual_memory.return_value = _Memory()
        mock_swap_memory.return_value = _Swap()
        mock_disk_usage.return_value = _Disk()

        snapshot = collect_snapshot()

        self.assertIsNotNone(snapshot.pk)
        mock_evaluate_alerts.assert_called_once()
        mock_dispatch_reports.assert_called_once()
        mock_dispatch_backups.assert_called_once()
        mock_prune.assert_called_once()
