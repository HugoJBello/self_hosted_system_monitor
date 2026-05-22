import json
from urllib import error, request


DEFAULT_USER_AGENT = "SystemMonitor/1.0"


def build_test_payload(settings_obj, snapshot=None):
    payload = {
        "origin": settings_obj.notifications_default_origin or "system-monitor",
        "status": settings_obj.notifications_default_status or "warning",
        "priority": settings_obj.notifications_default_priority or "high",
        "action": settings_obj.notifications_default_action or "notify",
        "title": "System Monitor test notification",
        "message": "This is a test notification sent from the Django system monitor settings page.",
        "channels": settings_obj.notifications_channels_list or ["email"],
    }

    if settings_obj.notifications_tags_list:
        payload["tags"] = settings_obj.notifications_tags_list
    if settings_obj.notifications_default_user:
        payload["user"] = settings_obj.notifications_default_user
    if snapshot:
        payload["message"] += (
            f" Latest snapshot: CPU {snapshot.cpu_percent}%, memory {snapshot.memory_percent}%, "
            f"disk {snapshot.disk_percent}%, processes {snapshot.process_count_total}."
        )

    return payload


def send_json_notification(settings_obj, payload):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        settings_obj.notifications_api_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {settings_obj.notifications_api_token}",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )

    try:
        with request.urlopen(req, timeout=settings_obj.notifications_timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            try:
                parsed_body = json.loads(raw_body) if raw_body else {}
            except json.JSONDecodeError:
                parsed_body = {"raw": raw_body}
            return {
                "ok": 200 <= response.status < 300,
                "status_code": response.status,
                "body": parsed_body,
            }
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "body": raw_body,
        }
    except error.URLError as exc:
        return {
            "ok": False,
            "status_code": None,
            "body": str(exc.reason),
        }
