"""Safe extraction of embedded media artwork for the file information view."""

import mimetypes
import subprocess

from file_manager_app.file_metadata import _tool_command


MAX_EMBEDDED_IMAGE_BYTES = 8 * 1024 * 1024
_EMBEDDED_IMAGE_TAGS = ("Picture", "CoverArt", "PreviewImage", "ThumbnailImage")


def has_embedded_thumbnail(path):
    """Return whether exiftool can extract an embedded image without decoding it."""
    command = _tool_command("exiftool")
    if not command:
        return False
    try:
        result = subprocess.run(
            [*command, "-s3", *[f"-{tag}" for tag in _EMBEDDED_IMAGE_TAGS], "--", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return bool(result.stdout and len(result.stdout) <= MAX_EMBEDDED_IMAGE_BYTES)
    except (OSError, subprocess.TimeoutExpired):
        return False


def extract_embedded_thumbnail(path):
    """Return ``(content, content_type)`` for the first usable embedded image."""
    command = _tool_command("exiftool")
    if not command:
        return None
    for tag in _EMBEDDED_IMAGE_TAGS:
        try:
            result = subprocess.run(
                [*command, "-b", f"-{tag}", "--", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        content = result.stdout or b""
        if not content or len(content) > MAX_EMBEDDED_IMAGE_BYTES:
            continue
        content_type = _image_content_type(content)
        if content_type:
            return content, content_type
    return None


def _image_content_type(content):
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return ""
