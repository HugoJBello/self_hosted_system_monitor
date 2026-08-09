import json
import os
import tempfile
import time
import gzip
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.utils import timezone
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.error import HTTPError
from unittest.mock import patch

from .alerting import ensure_default_alert_rules, evaluate_alerts
from .backups import BackupExecutionResult, StreamingCommandResult, _cloudflare_error_hint, _command_env, _consume_stream_buffer, _ensure_local_destination, _local_destination_is_available, _mounted_host_paths, _normalized_remote_host, _rsync_command, _rsync_exit_is_partial_success, _start_periodic_heartbeat, _stop_periodic_heartbeat, dispatch_scheduled_backups, finalize_backup_run, mark_stale_running_backups, request_backup_run_stop, run_backup_job
from .docker_runtime import _group_containers_by_family
from .forms import BackupJobForm, ScriptJobForm
from .http_backups import HTTP_GZIP_MIN_BYTES, HttpBackupError, _changed_files, _http_auth_headers, _http_request_timeout, _request_json, _request_remote_compare, _request_remote_file_heads, _request_remote_prune, _request_remote_stats, _source_directory_entries, _temporary_upload_path, _upload_file, sync_http_backup
from .models import AlertEvent, AlertRule, BackupJob, BackupRun, MonitoringSettings, ProcessSnapshot, ReportRule, ReportRun, ScriptJob, ScriptJobRun, SystemSnapshot
from .reporting import generate_report_for_rule
from .script_jobs import SCRIPT_LOG_LIMIT, ScriptExecutionResult, _build_script_command, dispatch_scheduled_script_jobs, finalize_script_run, request_script_run_stop, run_script_job
from .services import collect_snapshot


User = get_user_model()


class FakeHttpResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


@override_settings(FORCE_SCRIPT_NAME=None)
class MonitorViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("admin", password="test-pass", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _path(self, name, args=None):
        path = reverse(name, args=args or [])
        return path.replace(settings.APP_SUBPATH, "", 1)

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

    def test_healthz_endpoint_is_public_and_lightweight(self):
        self.client.logout()
        response = self.client.get(self._path("monitor:healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True})

    def test_app_subpath_prefix_is_accepted_without_proxy_rewrite(self):
        self.client.logout()

        app_subpath = settings.APP_SUBPATH

        health_response = self.client.get(f"{app_subpath}/healthz/")
        self.assertEqual(health_response.status_code, 200)
        self.assertJSONEqual(health_response.content, {"ok": True})

        monitor_response = self.client.get(f"{app_subpath}/monitor/")
        self.assertEqual(monitor_response.status_code, 302)
        self.assertIn(f"{app_subpath}/login/", monitor_response["Location"])
        self.assertNotIn(f"{app_subpath}{app_subpath}/", monitor_response["Location"])

        duplicate_prefix_response = self.client.get(f"{app_subpath}{app_subpath}/")
        self.assertEqual(duplicate_prefix_response.status_code, 302)
        self.assertIn(f"{app_subpath}/login/", duplicate_prefix_response["Location"])

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(self._path("monitor:backups"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("monitor:login"), response["Location"])

    def test_normal_user_cannot_open_settings(self):
        self.client.logout()
        normal = User.objects.create_user("normal", password="test-pass")
        self.client.force_login(normal)
        response = self.client.get(self._path("monitor:settings"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_open_users_page(self):
        response = self.client.get(self._path("monitor:users"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create user")

    def test_system_monitor_page_supports_process_sort_and_pagination(self):
        snapshot = self._create_snapshot(timezone.now(), platform_label="Arch Linux")
        ProcessSnapshot.objects.create(
            snapshot=snapshot,
            pid=100,
            name="zeta",
            username="alice",
            status="running",
            cpu_percent=10,
            memory_percent=1,
            memory_rss_mb=10,
            threads=1,
            command="zeta",
        )
        ProcessSnapshot.objects.create(
            snapshot=snapshot,
            pid=200,
            name="alpha",
            username="bob",
            status="sleeping",
            cpu_percent=20,
            memory_percent=2,
            memory_rss_mb=20,
            threads=2,
            command="alpha",
        )

        response = self.client.get(self._path("monitor:system-monitor"), {"sort": "name", "dir": "asc", "per_page": "25", "auto_refresh": "30"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Autorefresh")
        self.assertContains(response, "Arch Linux")

    def test_process_action_requires_confirmation(self):
        response = self.client.post(
            self._path("monitor:process-action"),
            {"action": "terminate", "pid": "123"},
        )
        self.assertRedirects(response, reverse("monitor:system-monitor"), fetch_redirect_response=False)
        messages_list = list(response.wsgi_request._messages)
        self.assertTrue(any("not confirmed" in str(message) for message in messages_list))

    @patch("monitor.views.terminate_process")
    @patch("monitor.views.validate_process_identity")
    def test_process_action_terminates_valid_live_process(self, mock_validate_process_identity, mock_terminate_process):
        class Current:
            name = "worker"
            container_id = ""
            container_name = ""

        mock_validate_process_identity.return_value = Current()
        response = self.client.post(
            self._path("monitor:process-action"),
            {
                "action": "terminate",
                "confirmed": "yes",
                "pid": "123",
                "expected_name": "worker",
                "expected_username": "root",
                "expected_command": "worker --loop",
            },
        )
        self.assertRedirects(response, reverse("monitor:system-monitor"), fetch_redirect_response=False)
        mock_validate_process_identity.assert_called_once_with(
            123,
            expected_name="worker",
            expected_username="root",
            expected_command="worker --loop",
            observed_at=None,
        )
        mock_terminate_process.assert_called_once_with(123)

    @patch("monitor.views.kill_process")
    @patch("monitor.views.validate_process_identity")
    def test_process_action_validates_historical_snapshot_before_kill(self, mock_validate_process_identity, mock_kill_process):
        class Current:
            name = "old-worker"
            container_id = ""
            container_name = ""

        mock_validate_process_identity.return_value = Current()
        snapshot = self._create_snapshot(timezone.now())
        process = ProcessSnapshot.objects.create(
            snapshot=snapshot,
            pid=321,
            name="old-worker",
            username="root",
            status="sleeping",
            cpu_percent=1,
            memory_percent=1,
            memory_rss_mb=10,
            threads=1,
            command="old-worker --loop",
        )
        response = self.client.post(
            self._path("monitor:process-action"),
            {
                "action": "kill",
                "confirmed": "yes",
                "pid": "321",
                "process_snapshot_id": str(process.id),
            },
        )
        self.assertRedirects(response, reverse("monitor:system-monitor"), fetch_redirect_response=False)
        mock_validate_process_identity.assert_called_once_with(
            321,
            expected_name="old-worker",
            expected_username="root",
            expected_command="old-worker --loop",
            observed_at=snapshot.captured_at,
        )
        mock_kill_process.assert_called_once_with(321)

    @patch("monitor.views.docker_container_action")
    @patch("monitor.views.validate_process_identity")
    def test_process_action_restarts_docker_container_for_container_process(self, mock_validate_process_identity, mock_docker_container_action):
        class Current:
            name = "python"
            container_id = "a" * 64
            container_name = "app-worker"

        mock_validate_process_identity.return_value = Current()
        response = self.client.post(
            self._path("monitor:process-action"),
            {
                "action": "restart",
                "confirmed": "yes",
                "pid": "456",
                "expected_name": "python",
            },
        )
        self.assertRedirects(response, reverse("monitor:system-monitor"), fetch_redirect_response=False)
        mock_docker_container_action.assert_called_once_with("a" * 64, "restart")

    @patch("monitor.views.reboot_host")
    def test_process_action_can_request_reboot(self, mock_reboot_host):
        response = self.client.post(
            self._path("monitor:process-action"),
            {"action": "reboot", "confirmed": "yes"},
        )
        self.assertRedirects(response, reverse("monitor:system-monitor"), fetch_redirect_response=False)
        mock_reboot_host.assert_called_once_with()

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
                "display_time_mode": "fixed",
                "display_timezone": "Europe/Madrid",
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
                "http_backup_token": "http-token",
            },
        )
        self.assertRedirects(response, reverse("monitor:settings"), fetch_redirect_response=False)
        settings_obj = MonitoringSettings.load()
        self.assertEqual(settings_obj.sample_interval_seconds, 120)
        self.assertEqual(settings_obj.top_process_limit, 10)
        self.assertEqual(settings_obj.history_retention_days, 14)
        self.assertEqual(settings_obj.display_time_mode, "fixed")
        self.assertEqual(settings_obj.display_timezone, "Europe/Madrid")
        self.assertTrue(settings_obj.notifications_enabled)
        self.assertEqual(settings_obj.notifications_default_channels, "email;telegram")
        self.assertEqual(settings_obj.http_backup_token, "http-token")

    @patch("monitor.views.send_json_notification")
    def test_settings_can_send_test_notification(self, mock_send_json_notification):
        mock_send_json_notification.return_value = {"ok": True, "status_code": 200, "body": {"ok": True}}
        response = self.client.post(
            self._path("monitor:settings"),
            {
                "sample_interval_seconds": 60,
                "top_process_limit": 8,
                "history_retention_days": 30,
                "display_time_mode": "browser",
                "display_timezone": "Europe/Madrid",
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
                "http_backup_token": "http-token",
                "send_test_notification": "1",
            },
        )
        self.assertRedirects(response, reverse("monitor:settings"), fetch_redirect_response=False)
        self.assertTrue(mock_send_json_notification.called)

    def test_settings_page_exposes_global_time_display_controls(self):
        response = self.client.get(self._path("monitor:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Date and Time Display")
        self.assertContains(response, "Fixed timezone")

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

    def test_script_jobs_page_loads(self):
        response = self.client.get(self._path("monitor:script-jobs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Script jobs")

    @patch("monitor.docker_views.get_docker_overview")
    def test_docker_overview_page_loads(self, mock_get_docker_overview):
        family = {
            "key": "compose:test",
            "name": "test",
            "kind": "Compose project",
            "running_count": 1,
            "container_count": 1,
            "containers": [
                {
                    "id": "abc",
                    "name": "test-web",
                    "image_name": "nginx:latest",
                    "compose_service": "web",
                    "running": True,
                    "health": "healthy",
                    "networks": ["default"],
                    "ports": ["8012->8000/tcp"],
                    "restart_policy": "unless stopped",
                    "status_text": "running",
                }
            ],
            "images": ["nginx:latest"],
        }
        mock_get_docker_overview.return_value = {
            "families": [family],
            "running_families": [family],
            "stopped_families": [],
            "images": [{"name": "nginx:latest", "repository": "nginx", "tag": "latest", "image_id": "123456789abc", "size": "188MB", "created_since": "2 days ago", "used_by": 1}],
            "running_containers_count": 1,
            "stopped_containers_count": 0,
            "family_count": 1,
            "image_count": 1,
        }

        response = self.client.get(self._path("monitor:docker-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Docker runtime")
        self.assertContains(response, "test-web")
        self.assertContains(response, "nginx:latest")

    @patch("monitor.docker_views.get_container_logs")
    def test_docker_logs_view_returns_container_logs(self, mock_get_container_logs):
        mock_get_container_logs.return_value = {
            "tail": 200,
            "content": "2026-07-12T12:00:00Z hello from docker",
            "entries": [
                {
                    "source": "test-web",
                    "source_key": "abc123",
                    "timestamp": "2026-07-12T12:00:00Z",
                    "message": "hello from docker",
                }
            ],
        }

        response = self.client.get(self._path("monitor:docker-logs"), {"scope": "container", "id": "abc123"})

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "scope": "container",
                "id": "abc123",
                "tail": 200,
                "content": "2026-07-12T12:00:00Z hello from docker",
                "entries": [
                    {
                        "source": "test-web",
                        "source_key": "abc123",
                        "timestamp": "2026-07-12T12:00:00Z",
                        "message": "hello from docker",
                    }
                ],
            },
        )

    @patch("monitor.docker_views.perform_docker_action")
    def test_docker_action_view_dispatches_compose_recreate(self, mock_perform_docker_action):
        mock_perform_docker_action.return_value = "Compose project recreated."

        response = self.client.post(
            self._path("monitor:docker-action"),
            {
                "scope": "family",
                "id": "compose:self_hosted_system_monitor",
                "docker_action": "compose_up_force_recreate",
                "next": reverse("monitor:docker-overview"),
            },
        )

        self.assertRedirects(response, reverse("monitor:docker-overview"), fetch_redirect_response=False)
        mock_perform_docker_action.assert_called_once_with(
            "family",
            "compose:self_hosted_system_monitor",
            "compose_up_force_recreate",
        )

    def test_backup_runs_page_loads(self):
        response = self.client.get(self._path("monitor:backup-runs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All backup runs")

    @patch("monitor.views.start_background_script_job")
    def test_script_job_run_now_starts_background_process(self, mock_start_background):
        job = ScriptJob.objects.create(
            name="APT update",
            schedule_mode="manual",
            schedule_minutes=30,
            script_body="echo ok",
            position=1,
        )

        response = self.client.post(self._path("monitor:script-jobs"), {"run_now": str(job.id)})
        self.assertRedirects(response, reverse("monitor:script-jobs"), fetch_redirect_response=False)
        mock_start_background.assert_called_once()

    def test_script_job_run_detail_shows_script_arguments(self):
        job = ScriptJob.objects.create(
            name="Arguments",
            schedule_mode="manual",
            script_body='echo "$1"',
            script_arguments={
                "positionals": [{"value": "alpha"}],
                "flags": [{"flag": "--mode", "value": "fast"}],
            },
        )
        script_run = ScriptJobRun.objects.create(job=job, status="success", summary="Done")

        response = self.client.get(self._path("monitor:script-job-run-detail", args=[script_run.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1: alpha")
        self.assertContains(response, "--mode fast")

    def test_script_job_edit_preserves_day_schedule_value(self):
        job = ScriptJob.objects.create(
            name="Daily script",
            description="",
            enabled=True,
            schedule_mode="interval",
            schedule_minutes=7,
            schedule_unit="days",
            working_directory="/",
            script_body="echo ok",
            run_timeout_seconds=120,
            idle_timeout_seconds=60,
        )

        response = self.client.post(
            self._path("monitor:script-jobs"),
            {
                "save_job": str(job.id),
                f"job-{job.id}-name": "Daily script",
                f"job-{job.id}-description": "",
                f"job-{job.id}-enabled": "on",
                f"job-{job.id}-schedule_mode": "interval",
                f"job-{job.id}-schedule_minutes": "7",
                f"job-{job.id}-schedule_unit": "days",
                f"job-{job.id}-scheduled_for": "",
                f"job-{job.id}-working_directory": "/",
                f"job-{job.id}-script_body": "echo ok",
                f"job-{job.id}-script_arguments": '{"positionals":[],"flags":[]}',
                f"job-{job.id}-run_as_sudo": "",
                f"job-{job.id}-sudo_password": "",
                f"job-{job.id}-run_timeout_seconds": "120",
                f"job-{job.id}-idle_timeout_seconds": "60",
            },
        )

        self.assertRedirects(response, reverse("monitor:script-jobs"), fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertEqual(job.schedule_minutes, 7)
        self.assertEqual(job.schedule_unit, "days")

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
    def test_manual_backup_run_now_starts_background_process(self, mock_start_background):
        job = BackupJob.objects.create(
            name="Manual documents backup",
            schedule_mode="manual",
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

    def test_manual_backup_job_is_not_scheduled_automatically(self):
        job = BackupJob.objects.create(
            name="Manual backup",
            schedule_mode="manual",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            position=1,
        )

        self.assertIsNone(job.next_run_at)
        self.assertEqual(job.schedule_label, "Run only on demand")

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
    def test_backup_run_now_does_not_start_disabled_job(self, mock_start_background):
        job = BackupJob.objects.create(
            name="Disabled backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            enabled=False,
        )

        response = self.client.post(self._path("monitor:backups"), {"run_now": str(job.id)})

        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        mock_start_background.assert_not_called()

    def test_backup_toggle_disables_and_reactivates_job(self):
        job = BackupJob.objects.create(
            name="Toggle backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
        )
        self.assertTrue(job.enabled)
        self.assertIsNotNone(job.next_run_at)

        response = self.client.post(self._path("monitor:backups"), {"toggle_job": str(job.id)})
        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertFalse(job.enabled)
        self.assertIsNone(job.next_run_at)

        response = self.client.post(self._path("monitor:backups"), {"toggle_job": str(job.id)})
        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertTrue(job.enabled)
        self.assertIsNotNone(job.next_run_at)

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

    @patch("monitor.views.start_background_backup")
    def test_backup_rerun_does_not_start_disabled_job(self, mock_start_background):
        job = BackupJob.objects.create(
            name="Disabled backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            enabled=False,
        )
        backup_run = BackupRun.objects.create(
            job=job,
            status="failed",
            summary="Backup failed",
        )

        response = self.client.post(self._path("monitor:backups"), {"rerun_run": str(backup_run.id)})

        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        mock_start_background.assert_not_called()

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

    def test_backup_job_edit_does_not_require_hidden_position_field(self):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            connection_mode="direct",
            auth_mode="key",
            position=7,
        )

        response = self.client.post(
            self._path("monitor:backups"),
            {
                "save_job": str(job.id),
                f"job-{job.id}-name": job.name,
                f"job-{job.id}-description": job.description,
                f"job-{job.id}-enabled": "on",
                f"job-{job.id}-source_path": "/home/test/NewDocuments",
                f"job-{job.id}-schedule_minutes": "30",
                f"job-{job.id}-remote_host": job.remote_host,
                f"job-{job.id}-remote_user": job.remote_user,
                f"job-{job.id}-remote_dir": job.remote_dir,
                f"job-{job.id}-ssh_port": "22",
                f"job-{job.id}-connection_mode": "direct",
                f"job-{job.id}-cloudflare_auth_home": "",
                f"job-{job.id}-cloudflare_service_token_id": "",
                f"job-{job.id}-cloudflare_service_token_secret": "",
                f"job-{job.id}-auth_mode": "key",
                f"job-{job.id}-password_file_path": "",
                f"job-{job.id}-ssh_password": "",
                f"job-{job.id}-public_key_path": "",
                f"job-{job.id}-max_size": "100m",
                f"job-{job.id}-run_timeout_seconds": "7200",
                f"job-{job.id}-idle_timeout_seconds": "900",
                f"job-{job.id}-exclude_patterns": "",
            },
        )

        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertEqual(job.source_path, "/home/test/NewDocuments")
        self.assertEqual(job.position, 7)

    def test_backup_job_edit_can_set_manual_schedule(self):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            connection_mode="direct",
            auth_mode="key",
            position=7,
        )

        response = self.client.post(
            self._path("monitor:backups"),
            {
                "save_job": str(job.id),
                f"job-{job.id}-name": job.name,
                f"job-{job.id}-description": job.description,
                f"job-{job.id}-enabled": "on",
                f"job-{job.id}-backup_type": "remote",
                f"job-{job.id}-source_path": "/home/test/Documents",
                f"job-{job.id}-schedule_mode": "manual",
                f"job-{job.id}-schedule_minutes": "30",
                f"job-{job.id}-remote_host": job.remote_host,
                f"job-{job.id}-remote_user": job.remote_user,
                f"job-{job.id}-remote_dir": job.remote_dir,
                f"job-{job.id}-ssh_port": "22",
                f"job-{job.id}-connection_mode": "direct",
                f"job-{job.id}-cloudflare_auth_home": "",
                f"job-{job.id}-cloudflare_service_token_id": "",
                f"job-{job.id}-cloudflare_service_token_secret": "",
                f"job-{job.id}-auth_mode": "key",
                f"job-{job.id}-password_file_path": "",
                f"job-{job.id}-ssh_password": "",
                f"job-{job.id}-public_key_path": "",
                f"job-{job.id}-max_size": "100m",
                f"job-{job.id}-run_timeout_seconds": "7200",
                f"job-{job.id}-idle_timeout_seconds": "900",
                f"job-{job.id}-exclude_patterns": "",
            },
        )

        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertEqual(job.schedule_mode, "manual")
        self.assertIsNone(job.next_run_at)

    def test_backup_job_edit_preserves_saved_cloudflare_and_password_values(self):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="ssh.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            connection_mode="cloudflare",
            cloudflare_auth_home="/home/android18",
            cloudflare_service_token_id="token-id",
            cloudflare_service_token_secret="token-secret",
            auth_mode="password_value",
            ssh_password="secret",
            position=3,
        )

        response = self.client.post(
            self._path("monitor:backups"),
            {
                "save_job": str(job.id),
                f"job-{job.id}-name": job.name,
                f"job-{job.id}-description": job.description,
                f"job-{job.id}-enabled": "on",
                f"job-{job.id}-source_path": "/home/test/UpdatedDocuments",
                f"job-{job.id}-schedule_minutes": "30",
                f"job-{job.id}-remote_host": job.remote_host,
                f"job-{job.id}-remote_user": job.remote_user,
                f"job-{job.id}-remote_dir": job.remote_dir,
                f"job-{job.id}-ssh_port": "22",
                f"job-{job.id}-connection_mode": "cloudflare",
                f"job-{job.id}-cloudflare_auth_home": "/home/android18",
                f"job-{job.id}-cloudflare_service_token_id": "token-id",
                f"job-{job.id}-cloudflare_service_token_secret": "",
                f"job-{job.id}-auth_mode": "password_value",
                f"job-{job.id}-password_file_path": "",
                f"job-{job.id}-ssh_password": "",
                f"job-{job.id}-public_key_path": "",
                f"job-{job.id}-max_size": "100m",
                f"job-{job.id}-run_timeout_seconds": "7200",
                f"job-{job.id}-idle_timeout_seconds": "900",
                f"job-{job.id}-exclude_patterns": "",
            },
        )

        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertEqual(job.source_path, "/home/test/UpdatedDocuments")
        self.assertEqual(job.ssh_password, "secret")
        self.assertEqual(job.cloudflare_service_token_secret, "token-secret")

    def test_backup_job_edit_supports_local_backup_fields(self):
        job = BackupJob.objects.create(
            name="USB clone",
            backup_type="local",
            source_path="/home/test/Documents",
            local_dest_path="/media/usb/docs",
            verify_mounted_device=False,
            trigger_on_mount=False,
            schedule_minutes=30,
        )

        response = self.client.post(
            self._path("monitor:backups"),
            {
                "save_job": str(job.id),
                f"job-{job.id}-name": job.name,
                f"job-{job.id}-description": job.description,
                f"job-{job.id}-enabled": "on",
                f"job-{job.id}-backup_type": "local",
                f"job-{job.id}-source_path": "/home/test/UpdatedDocuments",
                f"job-{job.id}-local_dest_path": "/media/usb/updated-docs",
                f"job-{job.id}-verify_mounted_device": "on",
                f"job-{job.id}-trigger_on_mount": "on",
                f"job-{job.id}-schedule_minutes": "30",
                f"job-{job.id}-remote_host": "",
                f"job-{job.id}-remote_user": "",
                f"job-{job.id}-remote_dir": "",
                f"job-{job.id}-ssh_port": "22",
                f"job-{job.id}-connection_mode": "direct",
                f"job-{job.id}-cloudflare_auth_home": "",
                f"job-{job.id}-cloudflare_service_token_id": "",
                f"job-{job.id}-cloudflare_service_token_secret": "",
                f"job-{job.id}-auth_mode": "key",
                f"job-{job.id}-password_file_path": "",
                f"job-{job.id}-ssh_password": "",
                f"job-{job.id}-public_key_path": "",
                f"job-{job.id}-max_size": "100m",
                f"job-{job.id}-run_timeout_seconds": "7200",
                f"job-{job.id}-idle_timeout_seconds": "900",
                f"job-{job.id}-exclude_patterns": "",
            },
        )

        self.assertRedirects(response, reverse("monitor:backups"), fetch_redirect_response=False)
        job.refresh_from_db()
        self.assertEqual(job.backup_type, "local")
        self.assertEqual(job.local_dest_path, "/media/usb/updated-docs")
        self.assertTrue(job.verify_mounted_device)
        self.assertTrue(job.trigger_on_mount)

    def test_backup_run_status_prefers_runtime_state_for_running_job(self):
        job = BackupJob.objects.create(
            name="Documents backup",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
        )
        backup_run = BackupRun.objects.create(
            job=job,
            status="running",
            summary="DB summary",
            log_output="DB log",
        )
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"DJANGO_DB_PATH": f"{tmpdir}/db.sqlite3"}):
            runtime_root = os.path.join(tmpdir, "backup_runtime")
            os.makedirs(runtime_root, exist_ok=True)
            runtime_file = os.path.join(runtime_root, f"run_{backup_run.id}.json")
            with open(runtime_file, "w", encoding="utf-8") as handle:
                handle.write(
                    '{"status":"running","status_label":"Running","summary":"Runtime summary","log_output":"Runtime log","process_pid":123,'
                    '"runner_label":"worker-1","heartbeat_at":"2026-05-23T10:00:00+00:00","last_output_at":"2026-05-23T10:00:00+00:00"}'
                )
            response = self.client.get(self._path("monitor:backup-run-status", args=[backup_run.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"], "Runtime summary")
        self.assertEqual(payload["log_output"], "Runtime log")
        self.assertEqual(payload["process_pid"], 123)

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
    def setUp(self):
        self.user = User.objects.create_user("admin", password="test-pass", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _path(self, name, args=None):
        path = reverse(name, args=args or [])
        return path.replace(settings.APP_SUBPATH, "", 1)

    def test_group_containers_by_family_prefers_compose_project(self):
        containers = [
            {
                "family_key": "compose:alpha",
                "family_name": "alpha",
                "family_kind": "Compose project",
                "name": "alpha-web",
                "image_name": "nginx:latest",
                "compose_service": "web",
                "running": True,
            },
            {
                "family_key": "compose:alpha",
                "family_name": "alpha",
                "family_kind": "Compose project",
                "name": "alpha-worker",
                "image_name": "python:3.12",
                "compose_service": "worker",
                "running": False,
            },
        ]

        families = _group_containers_by_family(containers)

        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["name"], "alpha")
        self.assertEqual(families[0]["running_count"], 1)
        self.assertEqual(families[0]["container_count"], 2)

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

    @patch("monitor.backups.shutil_which", return_value="/usr/bin/rsync")
    def test_remote_rsync_command_defaults_to_local_to_remote_push(self, mock_shutil_which):
        job = BackupJob(
            remote_host="ssh.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            source_path="/home/test/Documents",
            delete_enabled=True,
        )

        command = _rsync_command(job, "/hostfs/home/test/Documents", "", use_key_auth=True)

        self.assertIn("--delete", command)
        self.assertEqual(command[-2:], ["/hostfs/home/test/Documents/", "backup@ssh.example.com:/srv/backups/test/"])

    @patch("monitor.backups.shutil_which", return_value="/usr/bin/rsync")
    def test_remote_rsync_pull_command_uses_remote_as_source_and_local_as_destination(self, mock_shutil_which):
        job = BackupJob(
            remote_host="ssh.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
            remote_direction="pull",
            source_path="/home/test/Documents",
            delete_enabled=True,
        )

        command = _rsync_command(job, "/hostfs/home/test/Documents", "", use_key_auth=True)

        self.assertIn("--delete", command)
        self.assertEqual(command[-2:], ["backup@ssh.example.com:/srv/backups/test/", "/hostfs/home/test/Documents/"])

    def test_backup_job_form_defaults_remote_direction_to_push(self):
        form = BackupJobForm(
            data={
                "name": "Docs",
                "description": "",
                "enabled": "on",
                "backup_type": "remote",
                "source_path": "/home/test/Documents",
                "local_dest_path": "",
                "schedule_mode": "interval",
                "schedule_minutes": "30",
                "remote_host": "ssh.example.com",
                "remote_user": "backup",
                "remote_dir": "/srv/backups/test",
                "ssh_port": "22",
                "connection_mode": "direct",
                "auth_mode": "key",
                "password_file_path": "",
                "ssh_password": "",
                "public_key_path": "",
                "max_size": "100m",
                "run_timeout_seconds": "7200",
                "idle_timeout_seconds": "900",
                "exclude_patterns": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["remote_direction"], "push")

    def test_cloudflare_mode_allows_blank_auth_home_and_blank_service_tokens(self):
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
                "new-remote_direction": "push",
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
        self.assertEqual(response.status_code, 302)

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

    def test_stream_buffer_consumes_carriage_return_progress(self):
        collected = []
        buffer = "29.37K   0%    0.00kB/s    0:00:00  \r        10.94M   0%   10.41MB/s    5:04:38  \rfinal line\ntrailing"

        remaining = _consume_stream_buffer(buffer, collected, None)

        self.assertEqual(remaining, "trailing")
        self.assertEqual(
            collected,
            [
                "29.37K   0%    0.00kB/s    0:00:00  ",
                "        10.94M   0%   10.41MB/s    5:04:38  ",
                "final line",
            ],
        )

    def test_build_script_command_uses_sudo_with_password_when_configured(self):
        job = ScriptJob(
            name="APT update",
            schedule_mode="interval",
            schedule_minutes=30,
            script_body="apt-get update",
            working_directory="/root",
            script_arguments={
                "positionals": [{"value": "stable"}],
                "flags": [{"flag": "--assume-yes", "value": ""}, {"flag": "-o", "value": "Debug::NoLocking=1"}],
            },
            run_as_sudo=True,
            sudo_password="secret",
        )

        command, stdin_text = _build_script_command(job)
        self.assertIn("sudo", command)
        self.assertIn("-S", command)
        self.assertEqual(stdin_text, "secret\n")
        bash_index = command.index("/bin/bash")
        self.assertEqual(command[bash_index:bash_index + 2], ["/bin/bash", "-lc"])
        self.assertIn("cd /root && apt-get update", command[bash_index + 2])
        self.assertEqual(command[bash_index + 3:], ["script-job", "stable", "--assume-yes", "-o", "Debug::NoLocking=1"])

    def test_script_job_arguments_are_added_after_bash_command_name(self):
        job = ScriptJob(
            name="Arguments",
            schedule_mode="manual",
            script_body='printf "%s" "$1"',
            script_arguments={
                "positionals": [{"value": "first value"}],
                "flags": [{"flag": "--mode", "value": "fast"}],
            },
        )

        command, stdin_text = _build_script_command(job)

        self.assertIsNone(stdin_text)
        self.assertEqual(command[-5:], ['printf "%s" "$1"', "script-job", "first value", "--mode", "fast"])

    def test_script_job_form_normalizes_script_arguments(self):
        form = ScriptJobForm(
            data={
                "name": "Arguments",
                "description": "",
                "enabled": "on",
                "schedule_mode": "manual",
                "schedule_minutes": "5",
                "schedule_unit": "days",
                "scheduled_for": "",
                "working_directory": "",
                "script_body": 'echo "$1"',
                "script_arguments": json.dumps(
                    {
                        "positionals": [{"value": "  alpha  "}, {"value": ""}],
                        "flags": [{"flag": " --mode ", "value": " fast "}],
                    }
                ),
                "run_timeout_seconds": "120",
                "idle_timeout_seconds": "60",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        job = form.save(commit=False)
        self.assertEqual(
            job.script_arguments,
            {"positionals": [{"value": "alpha"}], "flags": [{"flag": "--mode", "value": "fast"}]},
        )

    def test_script_job_form_serializes_initial_arguments_for_editor(self):
        job = ScriptJob.objects.create(
            name="Arguments",
            schedule_mode="manual",
            script_body='echo "$1"',
            script_arguments={
                "positionals": [{"value": "alpha"}],
                "flags": [{"flag": "--mode", "value": "fast"}],
            },
        )

        form = ScriptJobForm(instance=job, prefix=f"job-{job.id}")
        payload = json.loads(form["script_arguments"].value())

        self.assertEqual(
            payload,
            {"positionals": [{"value": "alpha"}], "flags": [{"flag": "--mode", "value": "fast"}]},
        )

    def test_script_job_form_allows_recurring_schedule_under_five_days(self):
        form = ScriptJobForm(
            data={
                "name": "Three day job",
                "description": "",
                "enabled": "on",
                "schedule_mode": "interval",
                "schedule_minutes": "3",
                "schedule_unit": "days",
                "scheduled_for": "",
                "working_directory": "",
                "script_body": "echo ok",
                "script_arguments": '{"positionals":[],"flags":[]}',
                "run_timeout_seconds": "120",
                "idle_timeout_seconds": "60",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        job = form.save(commit=False)
        self.assertEqual(job.schedule_minutes, 3)
        self.assertEqual(job.schedule_unit, "days")

    def test_script_job_form_rejects_recurring_schedule_under_five_minutes(self):
        form = ScriptJobForm(
            data={
                "name": "Three minute job",
                "description": "",
                "enabled": "on",
                "schedule_mode": "interval",
                "schedule_minutes": "3",
                "schedule_unit": "minutes",
                "scheduled_for": "",
                "working_directory": "",
                "script_body": "echo ok",
                "script_arguments": '{"positionals":[],"flags":[]}',
                "run_timeout_seconds": "120",
                "idle_timeout_seconds": "60",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Recurring jobs need at least 5 minute.", form.errors["schedule_minutes"])

    def test_script_job_form_rejects_invalid_flag_parameter(self):
        form = ScriptJobForm(
            data={
                "name": "Arguments",
                "description": "",
                "enabled": "on",
                "schedule_mode": "manual",
                "schedule_minutes": "5",
                "schedule_unit": "days",
                "scheduled_for": "",
                "working_directory": "",
                "script_body": "echo ok",
                "script_arguments": json.dumps({"positionals": [], "flags": [{"flag": "mode with space", "value": "fast"}]}),
                "run_timeout_seconds": "120",
                "idle_timeout_seconds": "60",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("script_arguments", form.errors)

    @patch("monitor.script_jobs.host_namespace_prefix", return_value=["nsenter", "--target", "1"])
    @patch("monitor.script_jobs._run_streaming_command")
    def test_run_script_job_reports_success(self, mock_run_streaming_command, _mock_prefix):
        mock_run_streaming_command.return_value = StreamingCommandResult(0, "done", "")
        job = ScriptJob.objects.create(
            name="APT update",
            schedule_mode="interval",
            schedule_minutes=30,
            script_body="echo done",
            position=1,
        )

        result = run_script_job(job)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "success")
        self.assertIn("Script content:", result.log_output)

    @patch("monitor.script_jobs.start_background_script_job")
    def test_dispatch_scheduled_script_jobs_starts_due_job(self, mock_start_background):
        job = ScriptJob.objects.create(
            name="APT update",
            schedule_mode="interval",
            schedule_minutes=30,
            schedule_unit="minutes",
            script_body="echo done",
            enabled=True,
            next_run_at=timezone.now() - timezone.timedelta(minutes=1),
            position=1,
        )

        dispatch_scheduled_script_jobs(timezone.now())
        mock_start_background.assert_called_once_with(job, launched_by="scheduler")

    def test_request_script_run_stop_marks_running_run(self):
        job = ScriptJob.objects.create(
            name="APT update",
            schedule_mode="interval",
            schedule_minutes=30,
            script_body="echo done",
            position=1,
        )
        run = ScriptJobRun.objects.create(job=job, status="running", summary="Running")

        self.assertTrue(request_script_run_stop(run))
        run.refresh_from_db()
        self.assertIsNotNone(run.stop_requested_at)

    def test_finalize_script_run_keeps_log_tail(self):
        job = ScriptJob.objects.create(
            name="Long output",
            schedule_mode="manual",
            script_body="echo done",
        )
        script_run = ScriptJobRun.objects.create(job=job, status="running", summary="Running")
        result = ScriptExecutionResult(
            False,
            18,
            "failed",
            "Script job failed with exit code 18.",
            "x" * (SCRIPT_LOG_LIMIT + 100) + "final zip open error",
        )

        finalize_script_run(script_run, result)

        script_run.refresh_from_db()
        self.assertLessEqual(len(script_run.log_output), SCRIPT_LOG_LIMIT)
        self.assertTrue(script_run.log_output.endswith("final zip open error"))

    @patch("monitor.script_jobs.start_background_script_job")
    def test_dispatch_scheduled_script_jobs_skips_manual_jobs(self, mock_start_background):
        ScriptJob.objects.create(
            name="Manual only",
            schedule_mode="manual",
            schedule_minutes=1,
            schedule_unit="days",
            script_body="echo done",
            enabled=True,
            position=1,
        )

        dispatch_scheduled_script_jobs(timezone.now())
        mock_start_background.assert_not_called()

    def test_cloudflare_mode_rejects_partial_service_token_pair(self):
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
                "new-cloudflare_service_token_id": "token-id",
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
        self.assertContains(response, "If you use Cloudflare service tokens, fill both the ID and the secret.")

    def test_http_backup_job_requires_remote_token(self):
        response = self.client.post(
            self._path("monitor:backups"),
            {
                "create_job": "1",
                "new-name": "HTTP backup",
                "new-description": "",
                "new-enabled": "on",
                "new-backup_type": "http",
                "new-source_path": "/home/test/Documents",
                "new-local_dest_path": "",
                "new-trigger_on_mount": "",
                "new-schedule_minutes": "30",
                "new-http_remote_url": "https://remote.example.com/system_monitor",
                "new-http_remote_token": "",
                "new-http_remote_path": "/srv/backups/test",
                "new-http_direction": "push",
                "new-remote_host": "",
                "new-remote_user": "",
                "new-remote_dir": "",
                "new-ssh_port": "22",
                "new-connection_mode": "direct",
                "new-auth_mode": "key",
                "new-cloudflare_auth_home": "",
                "new-cloudflare_service_token_id": "",
                "new-cloudflare_service_token_secret": "",
                "new-password_file_path": "",
                "new-public_key_path": "",
                "new-max_size": "100m",
                "new-run_timeout_seconds": "7200",
                "new-idle_timeout_seconds": "900",
                "new-exclude_patterns": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HTTP backups need the remote server Bearer token.")

    def test_http_backup_job_accepts_push_fields(self):
        response = self.client.post(
            self._path("monitor:backups"),
            {
                "create_job": "1",
                "new-name": "HTTP backup",
                "new-description": "",
                "new-enabled": "on",
                "new-backup_type": "http",
                "new-source_path": "/home/test/Documents",
                "new-local_dest_path": "",
                "new-trigger_on_mount": "",
                "new-schedule_minutes": "30",
                "new-http_remote_url": "https://remote.example.com/system_monitor",
                "new-http_remote_token": "token-123",
                "new-http_remote_path": "/srv/backups/test",
                "new-http_direction": "push",
                "new-remote_host": "",
                "new-remote_user": "",
                "new-remote_dir": "",
                "new-ssh_port": "22",
                "new-connection_mode": "direct",
                "new-auth_mode": "key",
                "new-cloudflare_auth_home": "",
                "new-cloudflare_service_token_id": "",
                "new-cloudflare_service_token_secret": "",
                "new-password_file_path": "",
                "new-public_key_path": "",
                "new-max_size": "100m",
                "new-run_timeout_seconds": "7200",
                "new-idle_timeout_seconds": "900",
                "new-exclude_patterns": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        job = BackupJob.objects.get(name="HTTP backup")
        self.assertEqual(job.backup_type, "http")
        self.assertEqual(job.http_direction, "push")
        self.assertEqual(job.http_remote_token, "token-123")

    def test_http_backup_job_accepts_pull_fields(self):
        response = self.client.post(
            self._path("monitor:backups"),
            {
                "create_job": "1",
                "new-name": "HTTP pull backup",
                "new-description": "",
                "new-enabled": "on",
                "new-backup_type": "http",
                "new-source_path": "",
                "new-local_dest_path": "/home/test/RestoredDocuments",
                "new-trigger_on_mount": "",
                "new-schedule_minutes": "30",
                "new-http_remote_url": "https://remote.example.com/system_monitor",
                "new-http_remote_token": "token-123",
                "new-http_remote_path": "/srv/backups/test",
                "new-http_direction": "pull",
                "new-remote_host": "",
                "new-remote_user": "",
                "new-remote_dir": "",
                "new-ssh_port": "22",
                "new-connection_mode": "direct",
                "new-auth_mode": "key",
                "new-cloudflare_auth_home": "",
                "new-cloudflare_service_token_id": "",
                "new-cloudflare_service_token_secret": "",
                "new-password_file_path": "",
                "new-public_key_path": "",
                "new-max_size": "100m",
                "new-run_timeout_seconds": "7200",
                "new-idle_timeout_seconds": "900",
                "new-exclude_patterns": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        job = BackupJob.objects.get(name="HTTP pull backup")
        self.assertEqual(job.backup_type, "http")
        self.assertEqual(job.http_direction, "pull")
        self.assertEqual(job.local_dest_path, "/home/test/RestoredDocuments")

    @patch("monitor.backups._run_streaming_command")
    @patch("monitor.backups._ensure_local_destination", return_value="/hostfs/media/usb/docs")
    @patch("monitor.backups._ensure_local_source", return_value="/hostfs/home/test/Documents")
    def test_local_backup_job_uses_local_rsync_target(
        self,
        mock_ensure_local_source,
        mock_ensure_local_destination,
        mock_run_streaming_command,
    ):
        job = BackupJob.objects.create(
            name="USB clone",
            backup_type="local",
            source_path="/home/test/Documents",
            local_dest_path="/media/usb/docs",
            schedule_minutes=30,
        )
        mock_run_streaming_command.return_value = StreamingCommandResult(0, "", "")

        result = run_backup_job(job)

        self.assertTrue(result.ok)
        command = mock_run_streaming_command.call_args.args[0]
        self.assertIn("/hostfs/home/test/Documents/", command)
        self.assertIn("/hostfs/media/usb/docs/", command)

    @patch("monitor.backups._mounted_host_paths", return_value=set())
    def test_local_backup_job_without_mount_verification_allows_unmounted_destination(
        self,
        mock_mounted_paths,
    ):
        job = BackupJob.objects.create(
            name="USB clone",
            backup_type="local",
            source_path="/home/test/Documents",
            local_dest_path="/media/usb/docs",
            verify_mounted_device=False,
            trigger_on_mount=False,
            schedule_minutes=30,
        )

        with patch("monitor.backups.os.makedirs") as mock_makedirs, patch("monitor.backups.os.path.isdir", return_value=True):
            destination = _ensure_local_destination(job)

        self.assertEqual(destination, "/hostfs/media/usb/docs")
        mock_makedirs.assert_called_once_with("/hostfs/media/usb/docs", exist_ok=True)

    @patch("monitor.backups._mounted_host_paths", return_value={"/media/disk_usb_backups"})
    def test_local_backup_job_mount_verification_accepts_parent_mount(
        self,
        mock_mounted_paths,
    ):
        job = BackupJob(
            backup_type="local",
            local_dest_path="/media/disk_usb_backups/backups/android18",
            verify_mounted_device=True,
        )

        self.assertTrue(_local_destination_is_available(job))

    def test_mounted_host_paths_strips_hostfs_prefix_from_mountpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc_dir = Path(tmpdir) / "proc"
            proc_dir.mkdir(parents=True, exist_ok=True)
            (proc_dir / "mounts").write_text(
                "/dev/sdd1 /hostfs/media/disk_usb_backups ext4 rw,relatime 0 0\n"
                "proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MONITOR_PROCFS_PATH": str(proc_dir)}):
                mounts = _mounted_host_paths()

        self.assertIn("/media/disk_usb_backups", mounts)

    @patch("monitor.http_backups._upload_file")
    @patch("monitor.http_backups._request_json")
    @patch("monitor.http_backups._read_local_file", return_value=b"new")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "keep.txt": {"size": 3, "mtime_ns": 1, "sha256": "same"},
                "new.txt": {"size": 3, "mtime_ns": 2, "sha256": "new"},
            },
            "skipped": [],
        },
    )
    def test_http_push_uploads_changed_files_from_remote_compare(
        self,
        mock_build_manifest,
        mock_read_local_file,
        mock_request_json,
        mock_upload_file,
    ):
        job = BackupJob.objects.create(
            name="HTTP push",
            backup_type="http",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="push",
            delete_enabled=False,
        )
        mock_request_json.side_effect = [
            {
                "ok": True,
                "changed": ["new.txt"],
                "missing": ["new.txt"],
                "skipped": [],
            },
        ]

        stats = sync_http_backup(job)

        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["deleted"], 0)
        mock_upload_file.assert_called_once()
        self.assertEqual(mock_upload_file.call_args.args[3], "new.txt")
        self.assertEqual(mock_request_json.call_args.args[1], "compare")

    @patch("monitor.http_backups._upload_file")
    @patch("monitor.http_backups._request_json")
    @patch("monitor.http_backups._read_local_file", return_value=b"new")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "bad:name.txt": {"size": 3, "mtime_ns": 1, "sha256": "bad"},
                "good.txt": {"size": 3, "mtime_ns": 2, "sha256": "good"},
            },
            "skipped": [],
        },
    )
    def test_http_push_continues_after_one_upload_fails(
        self,
        mock_build_manifest,
        mock_read_local_file,
        mock_request_json,
        mock_upload_file,
    ):
        job = BackupJob.objects.create(
            name="HTTP push partial",
            backup_type="http",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="push",
            delete_enabled=False,
        )
        mock_request_json.return_value = {
            "ok": True,
            "changed": ["bad:name.txt", "good.txt"],
            "missing": ["bad:name.txt", "good.txt"],
            "skipped": [],
        }
        mock_upload_file.side_effect = [HttpBackupError("invalid filename"), None]
        logs = []

        stats = sync_http_backup(job, log_callback=logs.append)

        self.assertEqual(stats["changed"], 2)
        self.assertEqual(stats["transferred"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(mock_upload_file.call_count, 2)
        self.assertEqual([call.args[3] for call in mock_upload_file.call_args_list], ["bad:name.txt", "good.txt"])
        self.assertTrue(any("Failed to push 1/2 bad:name.txt" in line for line in logs))
        self.assertTrue(any("Pushed 2/2 good.txt" in line for line in logs))

    @patch(
        "monitor.backups.sync_http_backup",
        return_value={"changed": 2, "transferred": 1, "failed": 1, "deleted": 0, "skipped": 0},
    )
    def test_http_backup_result_is_failed_when_file_errors_occur(self, mock_sync_http_backup):
        job = BackupJob.objects.create(
            name="HTTP push partial result",
            backup_type="http",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="push",
            delete_enabled=False,
        )

        result = run_backup_job(job)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("1/2 transferred, 1 failed", result.summary)

    @patch("monitor.http_backups._upload_file")
    @patch("monitor.http_backups._request_json")
    @patch("monitor.http_backups._read_local_file", return_value=b"new")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "keep.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
                "new.txt": {"size": 3, "mtime": 2, "mtime_ns": 2_000_000_000},
            },
            "skipped": [],
        },
    )
    def test_http_push_with_delete_uses_remote_compare_and_prunes_remote(
        self,
        mock_build_manifest,
        mock_read_local_file,
        mock_request_json,
        mock_upload_file,
    ):
        job = BackupJob.objects.create(
            name="HTTP push delete",
            backup_type="http",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="push",
            delete_enabled=True,
        )
        mock_request_json.side_effect = [
            {
                "ok": True,
                "changed": ["new.txt"],
                "missing": ["new.txt"],
                "skipped": [],
            },
            {"ok": True, "deleted": ["old.txt"], "skipped": []},
        ]
        logs = []

        stats = sync_http_backup(job, log_callback=logs.append)

        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["deleted"], 1)
        mock_upload_file.assert_called_once()
        self.assertEqual([call.args[1] for call in mock_request_json.call_args_list], ["compare", "prune"])
        self.assertTrue(any("Remote prune: deleted 1" in line for line in logs))

    @patch("monitor.http_backups._upload_file")
    @patch("monitor.http_backups._request_json")
    @patch("monitor.http_backups._read_local_file", return_value=b"new")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "keep.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
                "new.txt": {"size": 3, "mtime": 2, "mtime_ns": 2_000_000_000},
            },
            "skipped": [],
        },
    )
    def test_http_push_with_delete_does_not_list_destination_tree(
        self,
        mock_build_manifest,
        mock_read_local_file,
        mock_request_json,
        mock_upload_file,
    ):
        job = BackupJob.objects.create(
            name="HTTP push delete stat fallback",
            backup_type="http",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="push",
            delete_enabled=True,
        )
        mock_request_json.side_effect = [
            HttpBackupError("HTTP 404 from compare: Page not found"),
            {
                "ok": True,
                "files": {
                    "keep.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
                },
                "skipped": [],
            },
            {"ok": True, "deleted": ["old.txt"], "skipped": []},
        ]
        logs = []

        stats = sync_http_backup(job, log_callback=logs.append)

        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual([call.args[1] for call in mock_request_json.call_args_list], ["compare", "stat", "prune"])
        self.assertNotIn("list", [call.args[1] for call in mock_request_json.call_args_list])
        mock_upload_file.assert_called_once()
        self.assertTrue(any("Remote prune: deleted 1" in line for line in logs))

    @patch("monitor.http_backups._head_remote_file")
    @patch("monitor.http_backups._request_json")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "keep.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
            },
            "skipped": [],
        },
    )
    def test_http_push_with_old_receiver_uses_file_head_fallback(
        self,
        mock_build_manifest,
        mock_request_json,
        mock_head_remote_file,
    ):
        job = BackupJob.objects.create(
            name="HTTP push old receiver",
            backup_type="http",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="push",
            delete_enabled=True,
        )
        mock_request_json.side_effect = [
            HttpBackupError("HTTP 404 from compare: Page not found"),
            HttpBackupError("HTTP 404 from stat: Page not found"),
            HttpBackupError("HTTP 404 from prune: Page not found"),
        ]
        mock_head_remote_file.return_value = {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000}
        logs = []

        stats = sync_http_backup(job, log_callback=logs.append)

        self.assertEqual(stats["changed"], 0)
        self.assertEqual(stats["deleted"], 0)
        self.assertEqual([call.args[1] for call in mock_request_json.call_args_list], ["compare", "stat", "prune"])
        mock_head_remote_file.assert_called_once()
        self.assertTrue(any("Remote HEAD checks" in line for line in logs))

    @patch("monitor.http_backups._upload_file")
    @patch("monitor.http_backups._head_remote_file")
    @patch("monitor.http_backups._request_json")
    @patch("monitor.http_backups._read_local_file", return_value=b"new")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "keep.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
                "new.txt": {"size": 3, "mtime": 2, "mtime_ns": 2_000_000_000},
            },
            "skipped": [],
        },
    )
    def test_http_push_without_delete_uses_file_head_when_stat_is_missing(
        self,
        mock_build_manifest,
        mock_read_local_file,
        mock_request_json,
        mock_head_remote_file,
        mock_upload_file,
    ):
        job = BackupJob.objects.create(
            name="HTTP push head fallback",
            backup_type="http",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="push",
            delete_enabled=False,
        )
        mock_request_json.side_effect = [
            HttpBackupError("HTTP 404 from compare: Page not found"),
            HttpBackupError("HTTP 404 from stat: Page not found"),
        ]
        mock_head_remote_file.side_effect = [
            {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
            None,
        ]

        stats = sync_http_backup(job)

        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["deleted"], 0)
        self.assertEqual(mock_head_remote_file.call_count, 2)
        mock_upload_file.assert_called_once()
        self.assertEqual(mock_upload_file.call_args.args[3], "new.txt")

    @patch("monitor.http_backups._delete_local_files")
    @patch("monitor.http_backups._write_local_file")
    @patch("monitor.http_backups._download_file", return_value=b"remote")
    @patch("monitor.http_backups._request_json")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "keep.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
                "old-local.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
            },
            "skipped": [],
        },
    )
    def test_http_pull_downloads_changed_files_and_deletes_local_extras(
        self,
        mock_build_manifest,
        mock_request_json,
        mock_download_file,
        mock_write_local_file,
        mock_delete_local_files,
    ):
        job = BackupJob.objects.create(
            name="HTTP pull",
            backup_type="http",
            source_path="",
            local_dest_path="/home/test/RestoredDocuments",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="pull",
            delete_enabled=True,
        )
        mock_request_json.return_value = {
            "ok": True,
            "files": {
                "keep.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
                "new.txt": {"size": 4, "mtime": 2, "mtime_ns": 2_000_000_000},
            },
            "skipped": [],
        }
        mock_delete_local_files.return_value = ["old-local.txt"]
        logs = []

        stats = sync_http_backup(job, log_callback=logs.append)

        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["transferred"], 1)
        self.assertEqual(stats["deleted"], 1)
        mock_request_json.assert_called_once()
        self.assertEqual(mock_request_json.call_args.args[1], "manifest")
        mock_download_file.assert_called_once_with(
            "https://remote.example.com/system_monitor",
            "token-123",
            "/srv/backups/test",
            "new.txt",
            900,
            job,
        )
        mock_write_local_file.assert_called_once_with(
            "/home/test/RestoredDocuments",
            "new.txt",
            {"size": 4, "mtime": 2, "mtime_ns": 2_000_000_000},
            b"remote",
        )
        mock_delete_local_files.assert_called_once_with("/home/test/RestoredDocuments", ["old-local.txt"])
        self.assertTrue(any("Deleted 1 local files missing on remote." in line for line in logs))

    @patch("monitor.http_backups._delete_local_files")
    @patch("monitor.http_backups._write_local_file")
    @patch("monitor.http_backups._download_file", return_value=b"remote")
    @patch("monitor.http_backups._request_json")
    @patch(
        "monitor.http_backups.build_manifest",
        return_value={
            "files": {
                "old-local.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000},
            },
            "skipped": [],
        },
    )
    def test_http_pull_without_delete_keeps_local_extras(
        self,
        mock_build_manifest,
        mock_request_json,
        mock_download_file,
        mock_write_local_file,
        mock_delete_local_files,
    ):
        job = BackupJob.objects.create(
            name="HTTP pull no delete",
            backup_type="http",
            local_dest_path="/home/test/RestoredDocuments",
            schedule_minutes=30,
            http_remote_url="https://remote.example.com/system_monitor",
            http_remote_token="token-123",
            http_remote_path="/srv/backups/test",
            http_direction="pull",
            delete_enabled=False,
        )
        mock_request_json.return_value = {
            "ok": True,
            "files": {
                "new.txt": {"size": 4, "mtime": 2, "mtime_ns": 2_000_000_000},
            },
            "skipped": [],
        }

        stats = sync_http_backup(job)

        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["deleted"], 0)
        mock_download_file.assert_called_once()
        mock_write_local_file.assert_called_once()
        mock_delete_local_files.assert_not_called()

    @patch("monitor.http_backups._request_json")
    def test_http_stat_batches_report_progress_for_heartbeat(self, mock_request_json):
        mock_request_json.return_value = {"ok": True, "files": {}, "skipped": []}
        progress_calls = []

        _request_remote_stats(
            "https://remote.example.com/system_monitor",
            "token-123",
            "/srv/backups/test",
            [f"file-{index}.txt" for index in range(1001)],
            60,
            progress_callback=progress_calls.append,
        )

        self.assertEqual(mock_request_json.call_count, 2)
        self.assertEqual(len(progress_calls), 2)
        self.assertIsNone(progress_calls[0])
        self.assertIn("1001/1001", progress_calls[1])

    @patch("monitor.http_backups._request_json")
    def test_http_compare_batches_report_progress_for_heartbeat(self, mock_request_json):
        mock_request_json.return_value = {"ok": True, "changed": [], "missing": [], "skipped": []}
        progress_calls = []
        source_files = {
            f"file-{index}.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000}
            for index in range(5001)
        }

        result = _request_remote_compare(
            "https://remote.example.com/system_monitor",
            "token-123",
            "/srv/backups/test",
            source_files,
            60,
            progress_callback=progress_calls.append,
        )

        self.assertEqual(result["changed"], [])
        self.assertEqual(mock_request_json.call_count, 2)
        self.assertEqual(len(progress_calls), 2)
        self.assertIsNone(progress_calls[0])
        self.assertIn("5001/5001", progress_calls[1])

    def test_http_source_directory_entries_include_parent_children(self):
        entries = _source_directory_entries({
            "top.txt": {"size": 1},
            "folder/nested/photo.jpg": {"size": 2},
        })

        self.assertEqual(entries[""]["top.txt"], "file")
        self.assertEqual(entries[""]["folder"], "dir")
        self.assertEqual(entries["folder"]["nested"], "dir")
        self.assertEqual(entries["folder/nested"]["photo.jpg"], "file")

    @patch("monitor.http_backups._request_json")
    def test_http_prune_batches_report_progress_for_heartbeat(self, mock_request_json):
        mock_request_json.return_value = {"ok": True, "deleted": [], "skipped": []}
        progress_calls = []
        source_files = {
            f"folder-{index}/file.txt": {"size": 3, "mtime": 1, "mtime_ns": 1_000_000_000}
            for index in range(501)
        }

        result = _request_remote_prune(
            "https://remote.example.com/system_monitor",
            "token-123",
            "/srv/backups/test",
            source_files,
            [],
            60,
            progress_callback=progress_calls.append,
        )

        self.assertEqual(result["deleted"], [])
        self.assertEqual(mock_request_json.call_count, 2)
        self.assertEqual(len(progress_calls), 2)
        self.assertIsNone(progress_calls[0])
        self.assertIn("502/502", progress_calls[1])

    @patch("monitor.http_backups._head_remote_file", return_value=None)
    def test_http_head_fallback_reports_progress_for_heartbeat(self, mock_head_remote_file):
        progress_calls = []

        _request_remote_file_heads(
            "https://remote.example.com/system_monitor",
            "token-123",
            "/srv/backups/test",
            [f"file-{index}.txt" for index in range(101)],
            60,
            progress_callback=progress_calls.append,
        )

        self.assertEqual(mock_head_remote_file.call_count, 101)
        self.assertEqual(len(progress_calls), 101)
        self.assertIn("100/101", progress_calls[99])
        self.assertIn("101/101", progress_calls[100])

    def test_http_stat_endpoint_returns_file_metadata_for_requested_paths(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.http_backup_token = "receiver-token"
        settings_obj.save()
        with tempfile.TemporaryDirectory(dir="/hostfs/tmp") as hostfs_root:
            host_root = hostfs_root.replace("/hostfs", "", 1)
            file_path = os.path.join(hostfs_root, "folder", "camera.jpg")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as handle:
                handle.write(b"image-data")
            os.utime(file_path, ns=(1_765_000_000_123_456_789, 1_765_000_000_123_456_789))

            response = self.client.post(
                self._path("monitor:backup-http-stat"),
                data=json.dumps({
                    "root_path": host_root,
                    "relative_paths": ["folder/camera.jpg", "missing.jpg"],
                }),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer receiver-token",
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["files"]["folder/camera.jpg"]["size"], 10)
            self.assertEqual(payload["files"]["folder/camera.jpg"]["mtime"], 1_765_000_000)
            self.assertEqual(payload["missing"], ["missing.jpg"])

    def test_http_compare_endpoint_returns_changed_paths(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.http_backup_token = "receiver-token"
        settings_obj.save()
        with tempfile.TemporaryDirectory(dir="/hostfs/tmp") as hostfs_root:
            host_root = hostfs_root.replace("/hostfs", "", 1)
            same_path = os.path.join(hostfs_root, "same.txt")
            changed_path = os.path.join(hostfs_root, "changed.txt")
            with open(same_path, "wb") as handle:
                handle.write(b"same")
            with open(changed_path, "wb") as handle:
                handle.write(b"old")
            os.utime(same_path, ns=(1_765_000_000_000_000_000, 1_765_000_000_000_000_000))
            os.utime(changed_path, ns=(1_765_000_000_000_000_000, 1_765_000_000_000_000_000))

            response = self.client.post(
                self._path("monitor:backup-http-compare"),
                data=json.dumps({
                    "root_path": host_root,
                    "files": {
                        "same.txt": {"size": 4, "mtime": 1_765_000_000, "mtime_ns": 1_765_000_000_000_000_000},
                        "changed.txt": {"size": 3, "mtime": 1_765_000_001, "mtime_ns": 1_765_000_001_000_000_000},
                        "missing.txt": {"size": 7, "mtime": 1_765_000_000, "mtime_ns": 1_765_000_000_000_000_000},
                    },
                }),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer receiver-token",
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["changed"], ["changed.txt", "missing.txt"])
            self.assertEqual(payload["missing"], ["missing.txt"])

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=16)
    def test_http_json_endpoint_reads_gzip_body_past_django_memory_limit(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.http_backup_token = "receiver-token"
        settings_obj.save()
        with tempfile.TemporaryDirectory(dir="/hostfs/tmp") as hostfs_root:
            host_root = hostfs_root.replace("/hostfs", "", 1)
            payload = {
                "root_path": host_root,
                "files": {
                    f"missing-{index}.txt": {"size": index, "mtime": 1_765_000_000 + index}
                    for index in range(100)
                },
            }
            body = gzip.compress(json.dumps(payload).encode("utf-8"))
            self.assertGreater(len(body), 16)

            response = self.client.post(
                self._path("monitor:backup-http-compare"),
                data=body,
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer receiver-token",
                HTTP_CONTENT_ENCODING="gzip",
            )

            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["changed"]), 100)

    def test_http_prune_endpoint_deletes_entries_missing_locally(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.http_backup_token = "receiver-token"
        settings_obj.save()
        with tempfile.TemporaryDirectory(dir="/hostfs/tmp") as hostfs_root:
            host_root = hostfs_root.replace("/hostfs", "", 1)
            os.makedirs(os.path.join(hostfs_root, "keep-dir"), exist_ok=True)
            os.makedirs(os.path.join(hostfs_root, "old-dir", "nested"), exist_ok=True)
            with open(os.path.join(hostfs_root, "keep.txt"), "wb") as handle:
                handle.write(b"keep")
            with open(os.path.join(hostfs_root, "old.txt"), "wb") as handle:
                handle.write(b"old")
            with open(os.path.join(hostfs_root, "old-dir", "nested", "old.txt"), "wb") as handle:
                handle.write(b"old")

            response = self.client.post(
                self._path("monitor:backup-http-prune"),
                data=json.dumps({
                    "root_path": host_root,
                    "directories": {
                        "": {
                            "keep.txt": "file",
                            "keep-dir": "dir",
                        },
                    },
                    "exclude_patterns": [],
                }),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer receiver-token",
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(sorted(payload["deleted"]), ["old-dir", "old.txt"])
            self.assertTrue(os.path.exists(os.path.join(hostfs_root, "keep.txt")))
            self.assertTrue(os.path.isdir(os.path.join(hostfs_root, "keep-dir")))
            self.assertFalse(os.path.exists(os.path.join(hostfs_root, "old.txt")))
            self.assertFalse(os.path.exists(os.path.join(hostfs_root, "old-dir")))

    def test_http_file_head_returns_metadata_headers(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.http_backup_token = "receiver-token"
        settings_obj.save()
        with tempfile.TemporaryDirectory(dir="/hostfs/tmp") as hostfs_root:
            host_root = hostfs_root.replace("/hostfs", "", 1)
            file_path = os.path.join(hostfs_root, "camera.jpg")
            with open(file_path, "wb") as handle:
                handle.write(b"image-data")
            os.utime(file_path, ns=(1_765_000_000_123_456_789, 1_765_000_000_123_456_789))

            response = self.client.head(
                self._path("monitor:backup-http-file"),
                HTTP_AUTHORIZATION="Bearer receiver-token",
                QUERY_STRING=f"root_path={host_root}&relative_path=camera.jpg",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Backup-Size"], "10")
            self.assertEqual(response.headers["X-Backup-Mtime"], "1765000000")
            self.assertEqual(response.headers["X-Backup-Mtime-Ns"], "1765000000123456789")

    def test_http_list_endpoint_returns_one_directory_metadata(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.http_backup_token = "receiver-token"
        settings_obj.save()
        with tempfile.TemporaryDirectory(dir="/hostfs/tmp") as hostfs_root:
            host_root = hostfs_root.replace("/hostfs", "", 1)
            os.makedirs(os.path.join(hostfs_root, "folder", "nested"), exist_ok=True)
            file_path = os.path.join(hostfs_root, "folder", "camera.jpg")
            with open(file_path, "wb") as handle:
                handle.write(b"image-data")

            response = self.client.post(
                self._path("monitor:backup-http-list"),
                data=json.dumps({
                    "root_path": host_root,
                    "relative_dir": "folder",
                    "exclude_patterns": [],
                    "max_size_bytes": 100,
                }),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer receiver-token",
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["dirs"], ["folder/nested"])
            self.assertEqual(payload["files"]["folder/camera.jpg"]["size"], 10)

    def test_http_auth_headers_include_stable_user_agent(self):
        job = BackupJob()

        headers = _http_auth_headers("receiver-token", job, "application/json")

        self.assertEqual(headers["Authorization"], "Bearer receiver-token")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["User-Agent"], "system-monitor-http-backup/1.0")

    def test_http_request_timeout_uses_job_idle_timeout(self):
        job = BackupJob(idle_timeout_seconds=900)

        self.assertEqual(_http_request_timeout(job), 900)

    @patch("monitor.http_backups.urlopen")
    def test_http_json_requests_gzip_large_payloads(self, mock_urlopen):
        mock_urlopen.return_value = FakeHttpResponse(b'{"ok": true}')
        payload = {"files": {"large.txt": {"name": "x" * HTTP_GZIP_MIN_BYTES}}}

        _request_json("https://remote.example.com/system_monitor", "prune", "token-123", payload, 60, BackupJob())

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.headers["Content-encoding"], "gzip")
        self.assertLess(len(request.data), len(json.dumps(payload).encode("utf-8")))
        self.assertEqual(json.loads(gzip.decompress(request.data).decode("utf-8")), payload)

    def test_http_changed_files_can_compare_size_and_mtime_without_hashes(self):
        source_files = {
            "same.jpg": {"size": 10, "mtime": 1, "mtime_ns": 1_100_000_000},
            "new.jpg": {"size": 20, "mtime": 2, "mtime_ns": 2_000_000_000},
            "changed.jpg": {"size": 30, "mtime": 3, "mtime_ns": 3_100_000_000},
        }
        dest_files = {
            "same.jpg": {"size": 10, "mtime": 1, "mtime_ns": 1_900_000_000},
            "changed.jpg": {"size": 30, "mtime": 4, "mtime_ns": 4_000_000_000},
        }

        self.assertEqual(_changed_files(source_files, dest_files), ["changed.jpg", "new.jpg"])

    def test_http_changed_files_tolerates_destination_mtime_nanosecond_rounding(self):
        source_files = {
            "camera.jpg": {"size": 10, "mtime_ns": 1_765_000_000_123_456_789},
        }
        dest_files = {
            "camera.jpg": {"size": 10, "mtime_ns": 1_765_000_000_000_000_000},
        }

        self.assertEqual(_changed_files(source_files, dest_files), [])

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=16)
    def test_http_file_upload_streams_past_django_memory_limit(self):
        settings_obj = MonitoringSettings.load()
        settings_obj.http_backup_token = "receiver-token"
        settings_obj.save()
        payload = b"x" * 1024
        with tempfile.TemporaryDirectory(dir="/hostfs/tmp") as hostfs_root:
            host_root = hostfs_root.replace("/hostfs", "", 1)
            response = self.client.post(
                self._path("monitor:backup-http-file"),
                data=payload,
                content_type="application/octet-stream",
                HTTP_AUTHORIZATION="Bearer receiver-token",
                QUERY_STRING=f"root_path={host_root}&relative_path=large.bin&mtime_ns=123456789",
            )

            self.assertEqual(response.status_code, 200)
            written_path = os.path.join(hostfs_root, "large.bin")
            with open(written_path, "rb") as handle:
                self.assertEqual(handle.read(), payload)

    def test_http_upload_temp_paths_are_unique(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "camera.jpg")
            first = _temporary_upload_path(Path(target))
            second = _temporary_upload_path(Path(target))
            try:
                self.assertNotEqual(first, second)
                self.assertEqual(first.parent, Path(tmpdir))
                self.assertEqual(second.parent, Path(tmpdir))
                self.assertTrue(first.name.startswith(".camera.jpg.http-sync."))
                self.assertTrue(second.name.startswith(".camera.jpg.http-sync."))
            finally:
                first.unlink(missing_ok=True)
                second.unlink(missing_ok=True)

    @patch("monitor.http_backups.time.sleep", return_value=None)
    @patch("monitor.http_backups.urlopen")
    def test_http_upload_retries_transient_server_errors(self, mock_urlopen, mock_sleep):
        server_error = HTTPError(
            "https://remote.example.com/system_monitor/backups/http/file/",
            500,
            "Internal Server Error",
            hdrs=None,
            fp=BytesIO(b"<html>nginx 500</html>"),
        )
        mock_urlopen.side_effect = [server_error, FakeHttpResponse(b'{"ok": true}')]

        _upload_file(
            "https://remote.example.com/system_monitor",
            "token-123",
            "/srv/backups/test",
            "file.txt",
            {"mtime_ns": 123},
            b"content",
            60,
            BackupJob(),
        )

        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("monitor.http_backups.time.sleep", return_value=None)
    @patch("monitor.http_backups.urlopen")
    def test_http_upload_does_not_retry_bad_request(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = HTTPError(
            "https://remote.example.com/system_monitor/backups/http/file/",
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"ok": false, "error": "bad path"}'),
        )

        with self.assertRaisesRegex(Exception, "HTTP 400 while uploading"):
            _upload_file(
                "https://remote.example.com/system_monitor",
                "token-123",
                "/srv/backups/test",
                "file.txt",
                {"mtime_ns": 123},
                b"content",
                60,
                BackupJob(),
            )

        self.assertEqual(mock_urlopen.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("monitor.backups.start_background_backup")
    @patch("monitor.backups._local_destination_is_available", return_value=False)
    @patch("monitor.backups.mark_stale_running_backups", return_value=[])
    def test_dispatch_scheduled_backups_skips_unmounted_local_jobs(
        self,
        mock_mark_stale,
        mock_destination_available,
        mock_start_background,
    ):
        job = BackupJob.objects.create(
            name="USB clone",
            backup_type="local",
            source_path="/home/test/Documents",
            local_dest_path="/media/usb/docs",
            verify_mounted_device=True,
            schedule_minutes=30,
            next_run_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        dispatch_scheduled_backups(timezone.now())

        job.refresh_from_db()
        self.assertGreater(job.next_run_at, timezone.now() - timezone.timedelta(seconds=1))
        mock_start_background.assert_not_called()

    @patch("monitor.backups.start_background_backup")
    @patch("monitor.backups._local_destination_is_available", return_value=True)
    @patch("monitor.backups._mounted_host_paths", return_value={"/media/usb"})
    @patch("monitor.backups.mark_stale_running_backups", return_value=[])
    def test_dispatch_scheduled_backups_triggers_local_job_when_mount_appears(
        self,
        mock_mark_stale,
        mock_mounted_paths,
        mock_destination_available,
        mock_start_background,
    ):
        job = BackupJob.objects.create(
            name="USB clone",
            backup_type="local",
            source_path="/home/test/Documents",
            local_dest_path="/media/usb/docs",
            trigger_on_mount=True,
            last_mount_was_available=False,
            schedule_minutes=30,
            next_run_at=timezone.now() + timezone.timedelta(minutes=20),
        )

        dispatch_scheduled_backups(timezone.now())

        job.refresh_from_db()
        self.assertTrue(job.last_mount_was_available)
        mock_start_background.assert_called_once_with(job, launched_by="scheduler")

    @patch("monitor.backups.start_background_backup")
    @patch("monitor.backups._local_destination_is_available", return_value=True)
    @patch("monitor.backups._mounted_host_paths", return_value={"/media/usb"})
    @patch("monitor.backups.mark_stale_running_backups", return_value=[])
    def test_dispatch_scheduled_backups_does_not_trigger_manual_local_job_when_mount_appears(
        self,
        mock_mark_stale,
        mock_mounted_paths,
        mock_destination_available,
        mock_start_background,
    ):
        job = BackupJob.objects.create(
            name="Manual USB clone",
            backup_type="local",
            schedule_mode="manual",
            source_path="/home/test/Documents",
            local_dest_path="/media/usb/docs",
            trigger_on_mount=True,
            last_mount_was_available=False,
            schedule_minutes=30,
        )

        dispatch_scheduled_backups(timezone.now())

        job.refresh_from_db()
        self.assertFalse(job.last_mount_was_available)
        mock_start_background.assert_not_called()

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
        backup_run = BackupRun.objects.create(job=job, status="running", summary="Running", process_pid=123)
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"DJANGO_DB_PATH": f"{tmpdir}/db.sqlite3"}):
            self.assertTrue(request_backup_run_stop(backup_run))
            backup_run.refresh_from_db()
            self.assertIsNotNone(backup_run.stop_requested_at)
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "backup_runtime", f"run_{backup_run.id}.stop")))

    @patch("monitor.backups.time.sleep", return_value=None)
    @patch("monitor.backups._remove_runtime_files")
    @patch("monitor.backups._write_runtime_state")
    def test_finalize_backup_run_falls_back_to_direct_update(
        self,
        mock_write_runtime_state,
        mock_remove_runtime_files,
        mock_sleep,
    ):
        job = BackupJob.objects.create(
            name="Docs",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
        )
        backup_run = BackupRun.objects.create(job=job, status="running", summary="Running", log_output="still running")
        result = BackupExecutionResult(True, 0, "success", "Backup finished", "done", command_line="rsync /src /dst")

        with patch.object(BackupRun, "save", side_effect=OperationalError("database is locked")) as mock_save:
            finalize_backup_run(backup_run, result, finished_at=timezone.now())

        backup_run.refresh_from_db()
        self.assertEqual(backup_run.status, "success")
        self.assertEqual(backup_run.exit_code, 0)
        self.assertEqual(backup_run.summary, "Backup finished")
        self.assertEqual(backup_run.log_output, "done")
        mock_write_runtime_state.assert_called_once()
        mock_remove_runtime_files.assert_called_once()
        self.assertTrue(mock_save.called)
        self.assertTrue(mock_sleep.called)

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

    @patch("monitor.backups._runner_label", return_value="runner-a")
    @patch("monitor.backups._process_cmdline", return_value="/usr/local/bin/python manage.py run_backup_job 7 --run-id 123")
    @patch("monitor.backups._pid_is_alive", return_value=True)
    def test_mark_stale_running_backups_keeps_live_worker_running(self, mock_pid_is_alive, mock_process_cmdline, mock_runner_label):
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
            process_pid=12345,
            runner_label="runner-a",
            log_output="still running",
        )
        mock_process_cmdline.return_value = f"/usr/local/bin/python manage.py run_backup_job {job.id} --run-id {backup_run.id}"

        updated = mark_stale_running_backups(stale_time + timezone.timedelta(minutes=20))

        backup_run.refresh_from_db()
        self.assertEqual(updated, [])
        self.assertEqual(backup_run.status, "running")
        self.assertNotIn("heartbeat became stale", backup_run.log_output)
        mock_pid_is_alive.assert_called_with(12345)
        mock_process_cmdline.assert_called_with(12345)
        mock_runner_label.assert_called_once()

    @patch("monitor.backups._runner_label", return_value="runner-b")
    @patch("monitor.backups._process_cmdline", return_value="/usr/local/bin/python manage.py run_backup_job 7 --run-id 123")
    @patch("monitor.backups._pid_is_alive", return_value=True)
    def test_mark_stale_running_backups_reconciles_runner_mismatch(self, mock_pid_is_alive, mock_process_cmdline, mock_runner_label):
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
            process_pid=12345,
            runner_label="runner-a",
            log_output="still running",
        )

        updated = mark_stale_running_backups(stale_time + timezone.timedelta(minutes=20))

        backup_run.refresh_from_db()
        self.assertEqual(len(updated), 1)
        self.assertEqual(backup_run.status, "failed")
        self.assertIn("heartbeat became stale", backup_run.log_output)
        mock_pid_is_alive.assert_not_called()
        mock_process_cmdline.assert_not_called()
        mock_runner_label.assert_called_once()

    @patch("monitor.backups._runner_label", return_value="runner-a")
    @patch("monitor.backups._process_cmdline", return_value="/usr/bin/sleep 9999")
    @patch("monitor.backups._pid_is_alive", return_value=True)
    def test_request_backup_run_stop_cancels_when_pid_reused(self, mock_pid_is_alive, mock_process_cmdline, mock_runner_label):
        job = BackupJob.objects.create(
            name="Docs",
            source_path="/home/test/Documents",
            schedule_minutes=30,
            remote_host="backup.example.com",
            remote_user="backup",
            remote_dir="/srv/backups/test",
        )
        backup_run = BackupRun.objects.create(
            job=job,
            status="running",
            summary="Running",
            process_pid=12345,
            runner_label="runner-a",
            log_output="still running",
        )

        self.assertTrue(request_backup_run_stop(backup_run))
        backup_run.refresh_from_db()
        self.assertEqual(backup_run.status, "cancelled")
        self.assertIsNotNone(backup_run.finished_at)
        mock_pid_is_alive.assert_called_with(12345)
        mock_process_cmdline.assert_called_with(12345)
        mock_runner_label.assert_called_once()

    def test_periodic_heartbeat_runs_until_stopped(self):
        calls = []
        with patch("monitor.backups.BACKUP_HEARTBEAT_INTERVAL_SECONDS", 0.01):
            stop_event, thread = _start_periodic_heartbeat(lambda force=False: calls.append(force))
            deadline = time.monotonic() + 0.5
            while not calls and time.monotonic() < deadline:
                time.sleep(0.01)
            _stop_periodic_heartbeat(stop_event, thread)

        self.assertIn(True, calls)
        self.assertFalse(thread.is_alive())

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
        self.assertEqual(mock_run_streaming_command.call_args.kwargs["timeout_seconds"], 7200)
        self.assertEqual(mock_run_streaming_command.call_args.kwargs["idle_timeout_seconds"], None)

    @patch("monitor.backups._command_env", return_value={})
    @patch("monitor.backups._run_streaming_command")
    @patch("monitor.backups._rsync_command", return_value=["rsync", "/src/", "host:/dst/"])
    @patch("monitor.backups._ensure_local_source", return_value="/hostfs/home/test/Documents")
    def test_local_rsync_transfer_has_no_hard_timeout(
        self,
        mock_ensure_local_source,
        mock_rsync_command,
        mock_run_streaming_command,
        mock_command_env,
    ):
        job = BackupJob.objects.create(
            name="USB clone",
            backup_type="local",
            source_path="/home/test/Documents",
            local_dest_path="/media/usb/docs",
            schedule_minutes=30,
        )
        mock_run_streaming_command.return_value = StreamingCommandResult(0, "", "")

        result = run_backup_job(job)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "success")
        self.assertIsNone(mock_run_streaming_command.call_args.kwargs["timeout_seconds"])
        self.assertEqual(mock_run_streaming_command.call_args.kwargs["idle_timeout_seconds"], None)


class MonitoringIsolationTests(TestCase):
    @patch("monitor.services.prune_old_snapshots")
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
    def test_post_collection_failures_do_not_break_snapshot_collection(
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
        mock_prune.assert_called_once()
