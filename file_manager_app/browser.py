import mimetypes
from urllib.parse import urlencode

from django.urls import reverse

from volumes_app.path_browser import entry_metadata_for_path, list_directory_entries
from .sorting import sort_entries


MAX_IMAGE_PREVIEW_BYTES = 15 * 1024 * 1024
MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_VIDEO_PREVIEW_BYTES = 512 * 1024 * 1024
MAX_AUDIO_PREVIEW_BYTES = 512 * 1024 * 1024
MAX_PDF_PREVIEW_BYTES = 100 * 1024 * 1024

PREVIEW_SIZE_LIMITS = {
    "image": MAX_IMAGE_PREVIEW_BYTES,
    "text": MAX_TEXT_PREVIEW_BYTES,
    "video": MAX_VIDEO_PREVIEW_BYTES,
    "audio": MAX_AUDIO_PREVIEW_BYTES,
    "pdf": MAX_PDF_PREVIEW_BYTES,
}
PREVIEWABLE_MEDIA_KINDS = frozenset(PREVIEW_SIZE_LIMITS)

TEXT_CONTENT_TYPES = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-sh",
    "application/x-yaml",
}


def list_file_manager_entries(host_path, *, folders_only=False, sort_field="name", sort_direction="asc"):
    entries = list_directory_entries(host_path, include_files=not folders_only)
    if folders_only:
        entries = [entry for entry in entries if entry.get("is_dir")]
        return sort_entries(entries, sort_field, sort_direction)
    return sort_entries([enrich_file_entry(entry) for entry in entries], sort_field, sort_direction)


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


def file_entry_for_path(host_path):
    entry = entry_metadata_for_path(host_path)
    return enrich_file_entry(entry) if entry else None


def media_kind_for_content_type(content_type):
    if content_type == "application/pdf":
        return "pdf"
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("text/") or content_type in TEXT_CONTENT_TYPES:
        return "text"
    return ""


def preview_size_limit(media_kind):
    return PREVIEW_SIZE_LIMITS.get(media_kind or "")


def preview_is_available(entry):
    size_bytes = entry.get("size_bytes")
    media_kind = entry.get("media_kind") or media_kind_for_content_type(entry.get("content_type") or "")
    limit = preview_size_limit(media_kind)
    if size_bytes is None or limit is None:
        return False
    return size_bytes <= limit
