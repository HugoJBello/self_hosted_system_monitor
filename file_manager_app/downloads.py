import hashlib
import os
from email.utils import formatdate

from django.http import HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header


MANAGED_DOWNLOAD_THRESHOLD = 100 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
STREAM_READ_SIZE = 1024 * 1024
INLINE_MEDIA_MAX_RANGE_BYTES = 8 * 1024 * 1024


def _parse_range(value, size):
    if not value:
        return None
    units, separator, requested = value.partition("=")
    if separator != "=" or units.strip().lower() != "bytes" or "," in requested:
        raise ValueError("Unsupported byte range")
    start_text, separator, end_text = requested.strip().partition("-")
    if separator != "-":
        raise ValueError("Invalid byte range")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        elif end_text:
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError("Invalid suffix range")
            start = max(size - suffix, 0)
            end = size - 1
        else:
            raise ValueError("Empty byte range")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid byte range") from exc
    if start < 0 or start >= size or end < start:
        raise ValueError("Unsatisfiable byte range")
    return start, min(end, size - 1)


def _file_chunks(path, start, length):
    with open(path, "rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining:
            chunk = handle.read(min(STREAM_READ_SIZE, remaining))
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk


def _etag(stat_result):
    identity = f"{stat_result.st_ino}:{stat_result.st_size}:{stat_result.st_mtime_ns}".encode()
    return f'"{hashlib.sha256(identity).hexdigest()[:24]}"'


def resumable_download_response(
    request,
    path,
    filename,
    content_type=None,
    *,
    as_attachment=True,
    max_range_bytes=None,
):
    """Serve one local file with standards-compliant single byte range support."""
    path = os.fspath(path)
    stat_result = os.stat(path)
    size = stat_result.st_size
    etag = _etag(stat_result)
    range_header = request.headers.get("Range")
    if range_header and request.headers.get("If-Range") not in (None, "", etag):
        range_header = None
    try:
        byte_range = _parse_range(range_header, size)
    except ValueError:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        response["Accept-Ranges"] = "bytes"
        response["ETag"] = etag
        return response

    if max_range_bytes and size > max_range_bytes:
        if byte_range is None:
            byte_range = (0, max_range_bytes - 1)
        elif byte_range[1] - byte_range[0] + 1 > max_range_bytes:
            byte_range = (byte_range[0], byte_range[0] + max_range_bytes - 1)
    start, end = byte_range if byte_range is not None else (0, max(size - 1, 0))
    length = max(end - start + 1, 0)
    response = StreamingHttpResponse(
        () if request.method == "HEAD" else _file_chunks(path, start, length),
        status=206 if byte_range is not None else 200,
        content_type=content_type or "application/octet-stream",
    )
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = str(length)
    response["Content-Disposition"] = content_disposition_header(as_attachment, filename)
    response["ETag"] = etag
    response["Last-Modified"] = formatdate(stat_result.st_mtime, usegmt=True)
    response["Cache-Control"] = "private, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["X-Download-Size"] = str(size)
    response["X-Download-Chunk-Size"] = str(DOWNLOAD_CHUNK_SIZE)
    response["X-Managed-Download-Threshold"] = str(MANAGED_DOWNLOAD_THRESHOLD)
    if byte_range is not None:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response
