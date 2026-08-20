import json
import time
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone

from .process_control import ProcessControlError, _run_host_command


_OVERVIEW_CACHE = {"timestamp": 0.0, "payload": None}
_OVERVIEW_CACHE_TTL_SECONDS = 5
_DEFAULT_LOG_TAIL = 200
_MAX_LOG_TAIL = 500
_MAX_EXTENDED_LOG_TAIL = 1500


def _docker_command(args, *, timeout_error_context="Docker command failed"):
    try:
        return _run_host_command(["docker", *args])
    except ProcessControlError as exc:
        raise ProcessControlError(f"{timeout_error_context}: {exc}") from exc


def _container_ids():
    result = _docker_command(["ps", "-aq"], timeout_error_context="Failed to list Docker containers")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _inspect_containers(container_ids):
    if not container_ids:
        return []
    result = _docker_command(
        ["container", "inspect", *container_ids],
        timeout_error_context="Failed to inspect Docker containers",
    )
    return json.loads(result.stdout or "[]")


def _list_images():
    result = _docker_command(
        ["image", "ls", "--format", "{{json .}}"],
        timeout_error_context="Failed to list Docker images",
    )
    items = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _normalize_restart_policy(value):
    value = (value or "").strip()
    if not value:
        return "no"
    return value.replace("-", " ")


def _format_ports(port_map):
    if not port_map:
        return []
    rendered = []
    for container_port, bindings in sorted(port_map.items()):
        if not bindings:
            rendered.append(container_port)
            continue
        for binding in bindings:
            host_ip = (binding or {}).get("HostIp", "")
            host_port = (binding or {}).get("HostPort", "")
            if host_ip and host_ip not in {"0.0.0.0", "::"}:
                rendered.append(f"{host_ip}:{host_port}->{container_port}")
            else:
                rendered.append(f"{host_port}->{container_port}")
    return rendered


def _container_command(item):
    path = ((item.get("Path") or "")).strip()
    args = item.get("Args") or []
    preview = " ".join(part for part in [path, *args] if part).strip()
    return preview or "-"


def _image_repo_name(image_name):
    image_ref = (image_name or "").split("@", 1)[0]
    if "/" in image_ref:
        last_segment = image_ref.rsplit("/", 1)[-1]
    else:
        last_segment = image_ref
    if ":" in last_segment:
        image_ref = image_ref.rsplit(":", 1)[0]
    return image_ref.rsplit("/", 1)[-1].strip() or "misc"


def _family_identity(container):
    labels = container["labels"]
    compose_project = (labels.get("com.docker.compose.project") or "").strip()
    if compose_project:
        return {
            "family_key": f"compose:{compose_project}",
            "family_name": compose_project,
            "family_kind": "Compose project",
        }

    image_repo = _image_repo_name(container.get("image_name") or "")
    return {
        "family_key": f"image:{image_repo}",
        "family_name": image_repo,
        "family_kind": "Image family",
    }


def _summarize_container(item):
    state = item.get("State") or {}
    labels = (item.get("Config") or {}).get("Labels") or {}
    health = (state.get("Health") or {}).get("Status", "")
    name = (item.get("Name") or "").lstrip("/") or item.get("Id", "")[:12]
    image_name = ((item.get("Config") or {}).get("Image") or "").strip() or "-"
    container = {
        "id": item.get("Id", ""),
        "short_id": (item.get("Id") or "")[:12],
        "name": name,
        "image_name": image_name,
        "image_repo": _image_repo_name(image_name) if image_name and image_name != "-" else "-",
        "state": (state.get("Status") or "unknown").strip(),
        "health": health.strip(),
        "status_text": (state.get("Status") or "unknown").strip().replace("_", " "),
        "running": bool(state.get("Running")),
        "started_at": state.get("StartedAt") or "",
        "finished_at": state.get("FinishedAt") or "",
        "created_at": item.get("Created") or "",
        "command": _container_command(item),
        "ports": _format_ports(((item.get("NetworkSettings") or {}).get("Ports") or {})),
        "networks": sorted((((item.get("NetworkSettings") or {}).get("Networks") or {}).keys())),
        "restart_policy": _normalize_restart_policy((((item.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name"))),
        "labels": labels,
        "compose_project": (labels.get("com.docker.compose.project") or "").strip(),
        "compose_service": (labels.get("com.docker.compose.service") or "").strip(),
    }
    container.update(_family_identity(container))
    return container


def _group_containers_by_family(containers):
    families = defaultdict(list)
    for container in containers:
        families[container["family_key"]].append(container)

    grouped = []
    for family_key, family_containers in families.items():
        ordered = sorted(
            family_containers,
            key=lambda item: (not item["running"], item["compose_service"] or item["name"], item["name"]),
        )
        running_count = sum(1 for item in ordered if item["running"])
        grouped.append(
            {
                "key": family_key,
                "name": ordered[0]["family_name"],
                "kind": ordered[0]["family_kind"],
                "running_count": running_count,
                "container_count": len(ordered),
                "status": "running" if running_count else "stopped",
                "containers": ordered,
                "images": sorted({item["image_name"] for item in ordered if item["image_name"]}),
            }
        )

    grouped.sort(
        key=lambda item: (
            item["running_count"] == 0,
            -item["running_count"],
            item["name"].lower(),
        )
    )
    return grouped


def get_docker_overview(*, force=False):
    now = time.monotonic()
    cached = _OVERVIEW_CACHE.get("payload")
    if not force and cached and now - _OVERVIEW_CACHE["timestamp"] < _OVERVIEW_CACHE_TTL_SECONDS:
        return cached

    containers = [_summarize_container(item) for item in _inspect_containers(_container_ids())]
    families = _group_containers_by_family(containers)

    image_usage = defaultdict(int)
    for container in containers:
        image_usage[container["image_name"]] += 1

    images = []
    for image in _list_images():
        repository = (image.get("Repository") or "<none>").strip()
        tag = (image.get("Tag") or "<none>").strip()
        name = f"{repository}:{tag}"
        images.append(
            {
                "name": name,
                "repository": repository,
                "tag": tag,
                "image_id": (image.get("ID") or "").replace("sha256:", "")[:12],
                "size": image.get("Size") or "-",
                "created_since": image.get("CreatedSince") or "-",
                "used_by": image_usage.get(name, 0),
            }
        )
    images.sort(key=lambda item: (-item["used_by"], item["repository"], item["tag"]))

    payload = {
        "containers": containers,
        "families": families,
        "running_families": [item for item in families if item["running_count"]],
        "stopped_families": [item for item in families if not item["running_count"]],
        "images": images,
        "running_containers_count": sum(1 for item in containers if item["running"]),
        "stopped_containers_count": sum(1 for item in containers if not item["running"]),
        "family_count": len(families),
        "image_count": len(images),
    }
    _OVERVIEW_CACHE.update({"timestamp": now, "payload": payload})
    return payload


def _normalize_log_tail(tail):
    raw = str(tail or _DEFAULT_LOG_TAIL).strip().lower()
    if raw == "all":
        return "all"
    try:
        tail_value = int(raw)
    except (TypeError, ValueError):
        tail_value = _DEFAULT_LOG_TAIL
    return max(20, min(tail_value, _MAX_EXTENDED_LOG_TAIL))


def _parse_log_timestamp(value):
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def _log_entries_from_content(content, *, source_name, source_key):
    entries = []
    for index, line in enumerate((content or "").splitlines()):
        raw_line = line.rstrip("\n")
        if not raw_line:
            continue
        timestamp_text = ""
        message = raw_line
        parts = raw_line.split(" ", 1)
        if len(parts) == 2 and _parse_log_timestamp(parts[0]) is not None:
            timestamp_text = parts[0]
            message = parts[1]
        entries.append(
            {
                "source": source_name,
                "source_key": source_key,
                "timestamp": timestamp_text,
                "message": message,
                "sort_key": _parse_log_timestamp(timestamp_text).isoformat() if timestamp_text else "",
                "sequence": index,
            }
        )
    return entries


def get_container_logs(container_id, *, tail=_DEFAULT_LOG_TAIL):
    tail_value = _normalize_log_tail(tail)
    result = _docker_command(
        ["logs", "--timestamps", "--tail", str(tail_value), container_id],
        timeout_error_context="Failed to read Docker container logs",
    )
    content = result.stdout or ""
    return {
        "tail": tail_value,
        "content": content,
        "entries": _log_entries_from_content(content, source_name=container_id[:12], source_key=container_id[:12]),
    }


def get_family_logs(family_key, *, tail=_DEFAULT_LOG_TAIL):
    overview = get_docker_overview()
    family = next((item for item in overview["families"] if item["key"] == family_key), None)
    if not family:
        raise ProcessControlError("Docker family was not found.")

    chunks = []
    entries = []
    tail_value = _normalize_log_tail(tail)
    for container in family["containers"]:
        logs = get_container_logs(container["id"], tail=tail_value)
        chunks.append(f"===== {container['name']} =====\n{logs['content'].rstrip()}\n")
        for entry in _log_entries_from_content(
            logs["content"],
            source_name=container["name"],
            source_key=container["id"][:12],
        ):
            entries.append(entry)
    entries.sort(key=lambda item: (item["sort_key"], item["source"], item["sequence"]))
    return {
        "tail": tail_value,
        "content": "\n".join(chunk.rstrip() for chunk in chunks if chunk.strip()).strip(),
        "entries": entries,
        "family": family,
    }
