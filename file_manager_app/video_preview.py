"""FFmpeg-backed compatibility previews and subtitle extraction.

Original media is never modified. Generated artifacts live in the application
data directory and are addressed by a fingerprint of the source file.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings


PROBE_TIMEOUT_SECONDS = 30
VIDEO_CACHE_DIR = Path(settings.BASE_DIR) / "data" / "video_previews"
VIDEO_CACHE_MAX_BYTES = int(os.getenv("VIDEO_PREVIEW_CACHE_MAX_BYTES", str(20 * 1024**3)))
WEBVTT_SUBTITLE_CODECS = frozenset({"ass", "ssa", "subrip", "text", "webvtt", "mov_text"})


def source_fingerprint(path: str) -> str:
    stat = os.stat(path)
    value = f"{os.path.realpath(path)}\0{stat.st_size}\0{stat.st_mtime_ns}"
    return hashlib.sha256(value.encode()).hexdigest()


def artifact_directory(path: str) -> Path:
    return VIDEO_CACHE_DIR / source_fingerprint(path)


def probe_video(path: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=index,codec_type,codec_name:stream_tags=language,title", "-of", "json", path],
        capture_output=True, check=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = [item for item in streams if item.get("codec_type") == "audio"]
    subtitles = [item for item in streams if item.get("codec_type") == "subtitle"]
    format_names = set((payload.get("format", {}).get("format_name") or "").split(","))
    directly_compatible = bool(
        video.get("codec_name") == "h264"
        and format_names.intersection({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
        and all(item.get("codec_name") in {"aac", "mp3"} for item in audio)
    )
    return {
        "directly_compatible": directly_compatible,
        "duration_seconds": _float_or_zero(payload.get("format", {}).get("duration")),
        "video_codec": video.get("codec_name") or "unknown",
        "audio_codecs": [item.get("codec_name") or "unknown" for item in audio],
        "subtitles": [_subtitle_description(item) for item in subtitles],
    }


def _subtitle_description(stream: dict) -> dict:
    tags = stream.get("tags") or {}
    language = tags.get("language") or "und"
    label = tags.get("title") or (language.upper() if language != "und" else "Subtitles")
    return {"index": int(stream["index"]), "language": language, "label": label, "codec": stream.get("codec_name") or "unknown"}


def state_for(path: str, *, start: bool = True) -> dict:
    directory = artifact_directory(path)
    state_path = directory / "state.json"
    state = _read_json(state_path)
    if state.get("status") == "ready" and not (directory / "preview.mp4").is_file():
        state = {}
    if state.get("status") == "preparing" and not state.get("duration_seconds"):
        state.update(probe_video(path))
        _write_json(state_path, state)
    if not state and start:
        metadata = probe_video(path)
        needs_work = bool(metadata["subtitles"] or not metadata["directly_compatible"])
        state = {**metadata, "status": "preparing" if needs_work else "direct", "subtitles_ready": []}
        directory.mkdir(parents=True, exist_ok=True)
        _write_json(state_path, state)
        if needs_work:
            _start_job(path, directory)
    elif start and state.get("status") == "preparing":
        _start_job(path, directory)
    return _public_state(state, directory)


def _start_job(path: str, directory: Path) -> None:
    marker = directory / "running"
    try:
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if _marker_process_is_alive(marker) or time.time() - marker.stat().st_mtime < 10:
            return
        marker.unlink(missing_ok=True)
        return _start_job(path, directory)
    try:
        process = subprocess.Popen(
            [sys.executable, "manage.py", "prepare_video_preview", path], cwd=settings.BASE_DIR,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        os.write(descriptor, str(process.pid).encode("ascii"))
    finally:
        os.close(descriptor)


def _marker_process_is_alive(marker: Path) -> bool:
    try:
        pid = int(marker.read_text(encoding="ascii"))
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def prepare_video(path: str) -> None:
    directory = artifact_directory(path)
    state_path = directory / "state.json"
    state = _read_json(state_path) or {**probe_video(path), "status": "preparing", "subtitles_ready": []}
    try:
        if state.get("directly_compatible"):
            state["status"] = "direct"
            state["stage"] = "complete"
        else:
            state["stage"] = "remuxing" if state.get("video_codec") == "h264" else "transcoding"
            _write_json(state_path, state)
            temporary_video = directory / "preview.tmp.mp4"
            progress_path = directory / "progress.txt"
            progress_path.unlink(missing_ok=True)
            video_options = ["-c:v", "copy"] if state.get("video_codec") == "h264" else [
                "-c:v", "libx264", "-preset", "superfast", "-crf", "24",
            ]
            audio_options = ["-c:a", "copy"] if all(codec in {"aac", "mp3"} for codec in state.get("audio_codecs", [])) else [
                "-c:a", "aac", "-b:a", "160k",
            ]
            result = subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", path,
                "-map", "0:v:0", "-map", "0:a:0?", "-sn", *video_options, *audio_options,
                "-movflags", "+faststart", "-progress", str(progress_path), "-stats_period", "1",
                "-f", "mp4", str(temporary_video),
            ])
            if result.returncode != 0 or not temporary_video.is_file() or not temporary_video.stat().st_size:
                raise RuntimeError("FFmpeg could not create a compatible preview")
            temporary_video.replace(directory / "preview.mp4")
            state["status"] = "ready"
            state["stage"] = "complete"
        _write_json(state_path, state)
        try:
            _prepare_subtitles(path, directory, state_path, state)
        except Exception as exc:
            state.update(subtitle_status="failed", subtitle_error=str(exc)[:300])
            _write_json(state_path, state)
        _trim_cache(keep=directory)
    except Exception as exc:
        state.update(status="failed", error=str(exc)[:300])
        _write_json(state_path, state)
        raise
    finally:
        (directory / "running").unlink(missing_ok=True)


def _prepare_subtitles(path: str, directory: Path, state_path: Path, state: dict) -> None:
    supported = [item for item in state.get("subtitles", []) if item.get("codec") in WEBVTT_SUBTITLE_CODECS]
    state["subtitle_status"] = "preparing" if supported else "complete"
    state["unsupported_subtitle_count"] = len(state.get("subtitles", [])) - len(supported)
    _write_json(state_path, state)
    ready_subtitles = []
    for subtitle in supported:
        target = directory / f"subtitle-{subtitle['index']}.vtt"
        temporary = directory / f"subtitle-{subtitle['index']}.tmp.vtt"
        try:
            result = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", path, "-map", f"0:{subtitle['index']}", "-f", "webvtt", str(temporary)],
                timeout=15 * 60,
            )
        except subprocess.TimeoutExpired:
            result = None
        if result is not None and result.returncode == 0 and temporary.is_file() and temporary.stat().st_size:
            temporary.replace(target)
            ready_subtitles.append(subtitle)
            state["subtitles_ready"] = ready_subtitles
            _write_json(state_path, state)
        else:
            temporary.unlink(missing_ok=True)
    state["subtitles_ready"] = ready_subtitles
    state["subtitle_status"] = "complete"
    _write_json(state_path, state)


def video_artifact(path: str) -> Path:
    return artifact_directory(path) / "preview.mp4"


def subtitle_artifact(path: str, stream_index: int) -> Path | None:
    directory = artifact_directory(path)
    state = _read_json(directory / "state.json")
    valid = {item["index"] for item in state.get("subtitles_ready", [])}
    candidate = directory / f"subtitle-{stream_index}.vtt"
    return candidate if stream_index in valid and candidate.is_file() else None


def _public_state(state: dict, directory: Path) -> dict:
    keys = ("status", "stage", "subtitle_status", "unsupported_subtitle_count", "directly_compatible", "duration_seconds", "video_codec", "audio_codecs", "subtitles_ready", "error")
    payload = {key: state.get(key) for key in keys if key in state}
    if state.get("status") == "preparing":
        payload.update(_progress_details(directory / "progress.txt", state.get("duration_seconds") or 0))
    return payload


def _progress_details(path: Path, duration_seconds: float) -> dict:
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
    except OSError:
        return {"progress_percent": 0, "eta_seconds": None, "speed": ""}
    processed = _float_or_zero(values.get("out_time_us")) / 1_000_000
    speed_label = values.get("speed") or ""
    speed = _float_or_zero(speed_label.rstrip("x"))
    percent = min(99, max(0, round(processed * 100 / duration_seconds))) if duration_seconds else 0
    eta = round(max(0, duration_seconds - processed) / speed) if speed > 0 and duration_seconds else None
    return {"progress_percent": percent, "eta_seconds": eta, "speed": speed_label}


def _float_or_zero(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _trim_cache(*, keep: Path) -> None:
    """Keep the cache bounded, removing the least recently used completed jobs."""
    if VIDEO_CACHE_MAX_BYTES <= 0 or not VIDEO_CACHE_DIR.is_dir():
        return
    entries = []
    total = 0
    for directory in VIDEO_CACHE_DIR.iterdir():
        if not directory.is_dir():
            continue
        size = sum(item.stat().st_size for item in directory.iterdir() if item.is_file())
        total += size
        if directory != keep and not (directory / "running").exists():
            entries.append((directory.stat().st_mtime, size, directory))
    for _, size, directory in sorted(entries):
        if total <= VIDEO_CACHE_MAX_BYTES:
            break
        for item in directory.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            continue
        total -= size
