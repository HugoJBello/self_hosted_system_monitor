import mimetypes
from urllib.parse import urlencode

from django.urls import reverse

from volumes_app.path_browser import list_directory_entries


MAX_IMAGE_PREVIEW_BYTES = 15 * 1024 * 1024
MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_VIDEO_PREVIEW_BYTES = 512 * 1024 * 1024

TEXT_CONTENT_TYPES = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-sh",
    "application/x-yaml",
}


def list_file_manager_entries(host_path, *, folders_only=False):
    entries = list_directory_entries(host_path, include_files=not folders_only)
    if folders_only:
        return [entry for entry in entries if entry.get("is_dir")]
    return [enrich_file_entry(entry) for entry in entries]


def enrich_file_entry(entry):
    enriched = dict(entry)
    if enriched.get("is_dir"):
        enriched["content_type"] = ""
        enriched["media_kind"] = ""
        return enriched

    content_type = mimetypes.guess_type(enriched.get("name") or enriched.get("path") or "")[0] or ""
    media_kind = media_kind_for_content_type(content_type)
    enriched["content_type"] = content_type
    enriched["media_kind"] = media_kind
    if preview_is_available(enriched):
        enriched["preview_url"] = f"{reverse('monitor:file-manager-preview')}?{urlencode({'path': enriched['path']})}"
    return enriched


def media_kind_for_content_type(content_type):
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("text/") or content_type in TEXT_CONTENT_TYPES:
        return "text"
    return ""


def preview_is_available(entry):
    size_bytes = entry.get("size_bytes")
    media_kind = entry.get("media_kind") or media_kind_for_content_type(entry.get("content_type") or "")
    if not size_bytes:
        return False
    if media_kind == "image":
        return size_bytes <= MAX_IMAGE_PREVIEW_BYTES
    if media_kind == "text":
        return size_bytes <= MAX_TEXT_PREVIEW_BYTES
    if media_kind == "video":
        return size_bytes <= MAX_VIDEO_PREVIEW_BYTES
    return False
