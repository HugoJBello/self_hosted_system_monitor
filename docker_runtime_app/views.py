from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.contrib.auth.mixins import UserPassesTestMixin

from .control import perform_docker_action
from .runtime import get_container_logs, get_docker_overview, get_family_logs
from main_app.models import MonitoringSettings
from monitor_app.process_control import ProcessControlError


class DockerAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class DockerOverviewView(LoginRequiredMixin, View):
    template_name = "monitor/docker_runtime.html"

    def get(self, request):
        try:
            overview = get_docker_overview(force=request.GET.get("refresh") == "1")
            error_message = ""
        except ProcessControlError as exc:
            overview = {
                "families": [],
                "running_families": [],
                "stopped_families": [],
                "images": [],
                "running_containers_count": 0,
                "stopped_containers_count": 0,
                "family_count": 0,
                "image_count": 0,
            }
            error_message = str(exc)

        context = {
            **overview,
            "docker_error": error_message,
            "settings_obj": MonitoringSettings.load(),
        }
        return render(request, self.template_name, context)


class DockerActionView(DockerAdminRequiredMixin, View):
    def post(self, request):
        scope = request.POST.get("scope", "")
        identifier = request.POST.get("id", "")
        action = request.POST.get("docker_action", "")
        next_url = request.POST.get("next") or "monitor:docker-overview"
        try:
            summary = perform_docker_action(scope, identifier, action)
        except ProcessControlError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, summary)
        return redirect(next_url)


class DockerLogsView(LoginRequiredMixin, View):
    @staticmethod
    def _public_entries(entries):
        public = []
        for entry in entries or []:
            public.append(
                {
                    "source": entry.get("source", ""),
                    "source_key": entry.get("source_key", ""),
                    "timestamp": entry.get("timestamp", ""),
                    "message": entry.get("message", ""),
                }
            )
        return public

    def get(self, request):
        scope = (request.GET.get("scope") or "").strip()
        identifier = (request.GET.get("id") or "").strip()
        tail = request.GET.get("tail")

        if scope == "container":
            try:
                logs = get_container_logs(identifier, tail=tail)
            except ProcessControlError as exc:
                return JsonResponse({"error": str(exc)}, status=400)
            return JsonResponse(
                {
                    "scope": "container",
                    "id": identifier,
                    "tail": logs["tail"],
                    "content": logs["content"],
                    "entries": self._public_entries(logs["entries"]),
                }
            )

        if scope == "family":
            try:
                logs = get_family_logs(identifier, tail=tail)
            except ProcessControlError as exc:
                return JsonResponse({"error": str(exc)}, status=400)
            return JsonResponse(
                {
                    "scope": "family",
                    "id": identifier,
                    "tail": logs["tail"],
                    "content": logs["content"],
                    "entries": self._public_entries(logs["entries"]),
                    "family_name": logs["family"]["name"],
                }
            )

        return JsonResponse({"error": "Unknown Docker log scope."}, status=400)
