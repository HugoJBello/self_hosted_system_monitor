from .runtime import get_docker_overview
from monitor_app.process_control import ProcessControlError, _run_host_command


_DOCKER_ACTION_TIMEOUT_SECONDS = 120
_DOCKER_COMPOSE_UP_TIMEOUT_SECONDS = 900


def _docker_command(args, *, timeout_seconds, context):
    try:
        return _run_host_command(["docker", *args], timeout_seconds=timeout_seconds)
    except ProcessControlError as exc:
        raise ProcessControlError(f"{context}: {exc}") from exc


def _resolve_family(identifier):
    overview = get_docker_overview(force=True)
    family = next((item for item in overview["families"] if item["key"] == identifier), None)
    if not family:
        raise ProcessControlError("Docker family was not found.")
    return family


def _resolve_image(reference):
    overview = get_docker_overview(force=True)
    image = next((item for item in overview["images"] if item["name"] == reference), None)
    if not image:
        raise ProcessControlError("Docker image was not found.")
    containers = [item for item in overview["containers"] if item["image_name"] == reference]
    return image, containers


def _container_ids(containers):
    ids = [item["id"] for item in containers if item.get("id")]
    if not ids:
        raise ProcessControlError("No matching containers were found for this action.")
    return ids


def _compose_context_from_family(family):
    compose_container = next((item for item in family["containers"] if item.get("compose_project")), None)
    if not compose_container:
        raise ProcessControlError("This family is not backed by Docker Compose metadata.")

    labels = compose_container.get("labels") or {}
    project = (labels.get("com.docker.compose.project") or "").strip()
    working_dir = (labels.get("com.docker.compose.project.working_dir") or "").strip()
    config_files = (labels.get("com.docker.compose.project.config_files") or "").strip()
    if not project or not working_dir or not config_files:
        raise ProcessControlError("Compose project metadata is incomplete for this family.")
    files = [item.strip() for item in config_files.split(",") if item.strip()]
    if not files:
        raise ProcessControlError("Compose config files were not found for this family.")
    return {"project": project, "working_dir": working_dir, "files": files}


def _compose_project_command(compose_ctx, compose_args, *, timeout_seconds, context):
    command = ["compose", "--project-name", compose_ctx["project"], "--project-directory", compose_ctx["working_dir"]]
    for filename in compose_ctx["files"]:
        command.extend(["-f", filename])
    command.extend(compose_args)
    return _docker_command(command, timeout_seconds=timeout_seconds, context=context)


def _docker_batch(action, ids, *, context):
    return _docker_command([action, *ids], timeout_seconds=_DOCKER_ACTION_TIMEOUT_SECONDS, context=context)


def perform_docker_action(scope, identifier, action):
    scope = (scope or "").strip()
    action = (action or "").strip()

    if scope == "family":
        family = _resolve_family(identifier)
        if action == "compose_up_force_recreate":
            compose_ctx = _compose_context_from_family(family)
            _compose_project_command(
                compose_ctx,
                ["up", "-d", "--build", "--force-recreate"],
                timeout_seconds=_DOCKER_COMPOSE_UP_TIMEOUT_SECONDS,
                context=f"Failed to recreate compose project '{family['name']}'",
            )
            return f"Compose project '{family['name']}' recreated with build."
        if action == "compose_restart":
            compose_ctx = _compose_context_from_family(family)
            _compose_project_command(
                compose_ctx,
                ["restart"],
                timeout_seconds=_DOCKER_ACTION_TIMEOUT_SECONDS,
                context=f"Failed to restart compose project '{family['name']}'",
            )
            return f"Compose project '{family['name']}' restarted."
        if action == "compose_stop":
            compose_ctx = _compose_context_from_family(family)
            _compose_project_command(
                compose_ctx,
                ["stop"],
                timeout_seconds=_DOCKER_ACTION_TIMEOUT_SECONDS,
                context=f"Failed to stop compose project '{family['name']}'",
            )
            return f"Compose project '{family['name']}' stopped."
        if action == "compose_start":
            compose_ctx = _compose_context_from_family(family)
            _compose_project_command(
                compose_ctx,
                ["start"],
                timeout_seconds=_DOCKER_ACTION_TIMEOUT_SECONDS,
                context=f"Failed to start compose project '{family['name']}'",
            )
            return f"Compose project '{family['name']}' started."
        if action == "restart_containers":
            ids = _container_ids(family["containers"])
            _docker_batch("restart", ids, context=f"Failed to restart containers in '{family['name']}'")
            return f"Containers in '{family['name']}' restarted."
        if action == "stop_containers":
            ids = _container_ids(family["containers"])
            _docker_batch("stop", ids, context=f"Failed to stop containers in '{family['name']}'")
            return f"Containers in '{family['name']}' stopped."
        if action == "start_containers":
            ids = _container_ids(family["containers"])
            _docker_batch("start", ids, context=f"Failed to start containers in '{family['name']}'")
            return f"Containers in '{family['name']}' started."
        raise ProcessControlError("Unknown Docker family action.")

    if scope == "image":
        image, containers = _resolve_image(identifier)
        if action == "restart_containers":
            ids = _container_ids(containers)
            _docker_batch("restart", ids, context=f"Failed to restart containers using image '{image['name']}'")
            return f"Containers using '{image['name']}' restarted."
        if action == "stop_containers":
            ids = _container_ids(containers)
            _docker_batch("stop", ids, context=f"Failed to stop containers using image '{image['name']}'")
            return f"Containers using '{image['name']}' stopped."
        if action == "start_containers":
            ids = _container_ids(containers)
            _docker_batch("start", ids, context=f"Failed to start containers using image '{image['name']}'")
            return f"Containers using '{image['name']}' started."
        if action == "remove_image":
            if image.get("used_by"):
                raise ProcessControlError("This image is still used by running or known containers.")
            _docker_command(
                ["image", "rm", image["name"]],
                timeout_seconds=_DOCKER_ACTION_TIMEOUT_SECONDS,
                context=f"Failed to remove image '{image['name']}'",
            )
            return f"Image '{image['name']}' removed."
        raise ProcessControlError("Unknown Docker image action.")

    raise ProcessControlError("Unknown Docker action scope.")
