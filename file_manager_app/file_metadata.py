"""Best-effort rich metadata extraction for file-manager information views."""

import json
import os
import shutil
import subprocess


_TOOL_TIMEOUT_SECONDS = 4
_EXIFTOOL_TAGS = (
    "FileType",
    "MIMEType",
    "Title",
    "Artist",
    "Album",
    "AlbumArtist",
    "Genre",
    "TrackNumber",
    "DiscNumber",
    "Duration",
    "BitRate",
    "SampleRate",
    "AudioChannels",
    "VideoFrameRate",
    "ImageWidth",
    "ImageHeight",
    "Orientation",
    "DateTimeOriginal",
    "CreateDate",
    "ModifyDate",
    "Make",
    "Model",
    "GPSLatitude",
    "GPSLongitude",
    "PageCount",
    "Author",
    "Creator",
    "Producer",
    "Subject",
    "Keywords",
    "Comment",
    "Description",
    "Copyright",
    "PictureType",
)

_EXIFTOOL_FIELDS = {
    "Title": ("Tags", "Title"),
    "Artist": ("Tags", "Artist"),
    "Album": ("Tags", "Album"),
    "AlbumArtist": ("Tags", "Album artist"),
    "Genre": ("Tags", "Genre"),
    "TrackNumber": ("Tags", "Track"),
    "DiscNumber": ("Tags", "Disc"),
    "Duration": ("Media", "Duration"),
    "BitRate": ("Media", "Bit rate"),
    "SampleRate": ("Media", "Sample rate"),
    "AudioChannels": ("Media", "Audio channels"),
    "VideoFrameRate": ("Media", "Frame rate"),
    "ImageWidth": ("Image", "Width"),
    "ImageHeight": ("Image", "Height"),
    "Orientation": ("Image", "Orientation"),
    "DateTimeOriginal": ("Image", "Taken"),
    "CreateDate": ("Media", "Created"),
    "ModifyDate": ("Media", "Modified"),
    "Make": ("Image", "Camera make"),
    "Model": ("Image", "Camera model"),
    "GPSLatitude": ("Image", "Latitude"),
    "GPSLongitude": ("Image", "Longitude"),
    "PageCount": ("Document", "Pages"),
    "Author": ("Document", "Author"),
    "Creator": ("Document", "Creator"),
    "Producer": ("Document", "Producer"),
    "Subject": ("Document", "Subject"),
    "Keywords": ("Document", "Keywords"),
    "Comment": ("Tags", "Comment"),
    "Description": ("Image", "Description"),
    "Copyright": ("Tags", "Copyright"),
}


def extract_file_metadata(path):
    """Return grouped, display-ready metadata without failing the information scan."""
    try:
        if not os.path.isfile(path):
            return []

        raw = _extract_with_exiftool(path)
        return _group_fields(raw)
    except Exception:
        # Rich metadata is optional; a corrupt or unusual file must not break
        # the basic Information response.
        return []


def _extract_with_exiftool(path):
    command = _tool_command("exiftool")
    if not command:
        return {}
    try:
        completed = subprocess.run(
            [*command, "-j", "-n", "-s", *[f"-{tag}" for tag in _EXIFTOOL_TAGS], "--", path],
            capture_output=True,
            text=True,
            timeout=_TOOL_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            return {}
        payload = json.loads(completed.stdout or "[]")
        return payload[0] if payload and isinstance(payload[0], dict) else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def _tool_command(name):
    executable = shutil.which(name)
    return [executable] if executable else []


def _group_fields(raw):
    groups = {}
    for tag, value in raw.items():
        mapping = _EXIFTOOL_FIELDS.get(tag)
        if not mapping or not _has_value(value):
            continue
        group, label = mapping
        groups.setdefault(group, []).append({"label": label, "value": _display_value(value)})
    if _has_value(raw.get("PictureType")):
        groups.setdefault("Media", []).append({"label": "Embedded image", "value": _display_value(raw["PictureType"])})
    return [{"label": label, "fields": fields} for label, fields in groups.items() if fields]


def _has_value(value):
    return value is not None and str(value).strip() != ""


def _display_value(value):
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if _has_value(item))
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items() if _has_value(item))
    return str(value).strip()
