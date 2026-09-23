import os
from datetime import datetime
from urllib.parse import quote

from django.urls import reverse
from django.utils import timezone
from django.conf import settings

from file_manager_app.browser import list_file_manager_entries
from file_manager_app.models import FileShareAccessEvent
from volumes_app.path_browser import hostfs_path, normalize_host_path


def validate_shared_paths(paths):
    result = []
    for raw_path in paths:
        path = normalize_host_path(raw_path)
        absolute = hostfs_path(path)
        if not os.path.exists(absolute):
            raise ValueError(f"Path does not exist: {path}")
        if path not in result:
            result.append(path)
    if not result:
        raise ValueError("Select at least one item to share.")
    return result


def parse_expiry(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Enter a valid expiry date and time.") from exc
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    if parsed <= timezone.now():
        raise ValueError("Expiry must be in the future.")
    return parsed


def can_access_share(share, user, token_present=False):
    if not share.is_active:
        return False
    if user.is_authenticated and (user.pk == share.created_by_id or user.pk == share.recipient_id):
        return True
    return bool(share.public_link and token_present)


def resolve_share_path(share, relative_path=""):
    try:
        index_text, _, child = (relative_path or "").partition("/")
        index = int(index_text)
        root = normalize_host_path(share.paths[index])
    except (ValueError, IndexError):
        raise ValueError("Invalid shared path.")
    candidate = normalize_host_path(os.path.join(root, child)) if child else root
    if candidate != root and not candidate.startswith(root.rstrip("/") + "/"):
        raise ValueError("Invalid shared path.")
    absolute = hostfs_path(candidate)
    root_absolute = hostfs_path(root)
    if candidate != root:
        try:
            if os.path.commonpath([os.path.realpath(absolute), os.path.realpath(root_absolute)]) != os.path.realpath(root_absolute):
                raise ValueError("Shared path leaves the allowed folder.")
        except ValueError as exc:
            raise ValueError("Invalid shared path.") from exc
    if not os.path.exists(absolute):
        raise ValueError("The shared item no longer exists.")
    return candidate, absolute


def shared_entries(share, relative_path=""):
    if not relative_path:
        entries = []
        for index, path in enumerate(share.paths):
            absolute = hostfs_path(path)
            entries.append({
                "name": os.path.basename(path.rstrip("/")) or "/",
                "relative_path": str(index),
                "is_dir": os.path.isdir(absolute),
                "size_bytes": None if os.path.isdir(absolute) else os.path.getsize(absolute),
            })
        return entries, ""
    path, absolute = resolve_share_path(share, relative_path)
    if not os.path.isdir(absolute):
        raise ValueError("This shared item is not a folder.")
    prefix = relative_path.rstrip("/")
    entries = list_file_manager_entries(path)
    for entry in entries:
        child = os.path.relpath(entry["path"], path).replace(os.sep, "/")
        entry["relative_path"] = f"{prefix}/{child}"
    parent = prefix.rpartition("/")[0]
    return entries, parent


def public_share_url(request, share, settings_obj):
    path = reverse("monitor:file-share-public", args=[share.token])
    base = settings_obj.normalized_app_public_base_url
    app_subpath = (getattr(settings, "APP_SUBPATH", "") or "").rstrip("/")
    if base and app_subpath and base.endswith(app_subpath) and path.startswith(app_subpath + "/"):
        path = path[len(app_subpath):]
    return f"{base}{path}" if base else request.build_absolute_uri(path)


def record_share_access(request, share, action, path=""):
    """Record an access without trusting proxy-supplied identity headers."""
    return FileShareAccessEvent.objects.create(
        share=share,
        user=request.user if request.user.is_authenticated else None,
        action=action,
        path=(path or "")[:500],
        remote_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )


def record_share_view_once(request, share):
    session_key = f"file_share_viewed_{share.pk}"
    now = timezone.now().timestamp()
    last_seen = request.session.get(session_key)
    if last_seen and now - float(last_seen) < 30 * 60:
        return
    record_share_access(request, share, "view")
    request.session[session_key] = now
