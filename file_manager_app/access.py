import os

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from file_manager_app.models import UserFileAccess
from volumes_app.path_browser import normalize_host_path


def configured_access_roots(user):
    if user.is_staff or user.is_superuser:
        return ["/"]
    roots = []
    active_share = Q(source_share__revoked_at__isnull=True) & (Q(source_share__expires_at__isnull=True) | Q(source_share__expires_at__gt=timezone.now()))
    queryset = UserFileAccess.objects.filter(user=user).filter(Q(source_share__isnull=True) | active_share)
    for path in queryset.values_list("path", flat=True):
        normalized = normalize_host_path(path)
        if not any(normalized == root or normalized.startswith(root.rstrip("/") + "/") for root in roots):
            roots.append(normalized)
    return roots


def access_roots(user):
    """No configured roots intentionally means unrestricted once Files is enabled."""
    if not (user.is_staff or user.is_superuser) and not user.feature_accesses.filter(feature="files").exists():
        return []
    roots = configured_access_roots(user)
    return roots or ["/"]


def has_full_file_access(user):
    return "/" in access_roots(user)


def user_can_access_path(user, path):
    normalized = normalize_host_path(path)
    return any(root == "/" or normalized == root or normalized.startswith(root.rstrip("/") + "/") for root in access_roots(user))


def require_path_access(user, path):
    normalized = normalize_host_path(path)
    if not user_can_access_path(user, normalized):
        raise PermissionDenied("You do not have access to this file location.")
    return normalized


def closest_allowed_parent(user, path):
    normalized = normalize_host_path(path)
    if user.is_staff or user.is_superuser:
        return os.path.dirname(normalized.rstrip("/")) or "/" if normalized != "/" else ""
    roots = access_roots(user)
    matching = [root for root in roots if normalized == root or normalized.startswith(root.rstrip("/") + "/")]
    if not matching:
        return ""
    root = max(matching, key=len)
    if normalized == root:
        return ""
    parent = os.path.dirname(normalized.rstrip("/")) or "/"
    return parent if user_can_access_path(user, parent) else ""
