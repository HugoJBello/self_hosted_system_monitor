import mimetypes
import os
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View
from django.views.decorators.cache import never_cache

from file_manager_app.browser import (
    MAX_IMAGE_PREVIEW_BYTES,
    MAX_TEXT_PREVIEW_BYTES,
    MAX_VIDEO_PREVIEW_BYTES,
    list_file_manager_entries,
    media_kind_for_content_type,
)
from file_manager_app.information import continue_file_information, start_file_information
from file_manager_app.models import FileOperation
from file_manager_app.services import (
    cancel_file_operation,
    create_file_operation,
    download_archive_path,
    finish_chunked_upload,
    pause_file_operation,
    resume_file_operation,
    save_uploaded_files,
    save_upload_chunk,
    start_chunked_upload,
    start_background_file_operation,
)
from main_app.models import MonitoringSettings
from volumes_app.path_browser import create_directory, hostfs_path, normalize_host_path


def _file_manager_url(path):
    url = reverse("monitor:file-manager")
    if path:
        return f"{url}?{urlencode({'path': path})}"
    return url


def _return_path_from_request(request, fallback="/"):
    raw_path = request.POST.get("return_path") or request.GET.get("return_path")
    if not raw_path:
        return fallback
    try:
        return normalize_host_path(raw_path)
    except ValueError:
        return fallback


def _operation_detail_url(operation, return_path=""):
    url = reverse("monitor:file-manager-operation-detail", args=[operation.id])
    if return_path:
        return f"{url}?{urlencode({'return_path': return_path})}"
    return url


def _operations_url(return_path=""):
    url = reverse("monitor:file-manager-operations")
    if return_path:
        return f"{url}?{urlencode({'return_path': return_path})}"
    return url


@method_decorator(never_cache, name="dispatch")
class FileManagerView(LoginRequiredMixin, View):
    template_name = "file_manager_app/file_manager.html"

    def get(self, request):
        settings_obj = MonitoringSettings.load()
        current_path = self._requested_path(request, settings_obj)
        entries, error = self._entries(current_path)
        return render(
            request,
            self.template_name,
            {
                "settings_obj": settings_obj,
                "current_path": current_path,
                "parent_path": self._parent_path(current_path),
                "entries": entries,
                "file_manager_error": error,
                "running_file_operations": FileOperation.objects.filter(status="running").order_by("-started_at")[:5],
            },
        )

    def post(self, request):
        current_path = normalize_host_path(request.POST.get("current_path") or "/")
        return_path = self._return_path(request, current_path)
        action = self._requested_action(request)
        selected_paths = request.POST.getlist("selected_paths")
        try:
            if action == "upload_start":
                operation = start_chunked_upload(
                    current_path,
                    request.POST.get("file_count"),
                    worker_count=request.POST.get("upload_workers"),
                )
                return JsonResponse(
                    {
                        "ok": True,
                        "operation_id": operation.id,
                        "status_url": reverse("monitor:file-manager-operation-status", args=[operation.id]),
                        "detail_url": self._operation_detail_url(operation, return_path),
                        "summary": operation.summary,
                    }
                )
            if action == "upload_chunk":
                operation, saved_path = save_upload_chunk(
                    request.POST.get("operation_id"),
                    current_path,
                    request.POST.get("relative_path") or "",
                    request.FILES.get("chunk"),
                    request.POST.get("chunk_index"),
                    request.POST.get("total_chunks"),
                )
                return JsonResponse(
                    {
                        "ok": True,
                        "operation_id": operation.id,
                        "processed_count": operation.processed_count,
                        "total_count": operation.total_count,
                        "saved_path": saved_path,
                        "summary": operation.summary,
                    }
                )
            if action == "upload_finish":
                operation = finish_chunked_upload(request.POST.get("operation_id"))
                return JsonResponse(
                    {
                        "ok": operation.status == "success",
                        "operation_id": operation.id,
                        "detail_url": self._operation_detail_url(operation, return_path),
                        "summary": operation.summary,
                    },
                    status=200 if operation.status == "success" else 400,
                )
            if action == "upload":
                operation = save_uploaded_files(
                    current_path,
                    request.FILES.getlist("uploads"),
                    worker_count=request.POST.get("upload_workers"),
                )
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse(
                        {
                            "ok": operation.status == "success",
                            "operation_id": operation.id,
                            "detail_url": self._operation_detail_url(operation, return_path),
                            "summary": operation.summary,
                        }
                    )
                messages.success(request, operation.summary)
                return redirect(f"{reverse('monitor:file-manager')}?path={current_path}")
            if action == "mkdir":
                item = create_directory(current_path, request.POST.get("folder_name") or "")
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"ok": True, "item": item})
                messages.success(request, f"Folder '{item['name']}' created.")
                return redirect(f"{reverse('monitor:file-manager')}?path={current_path}")
            if action == "download":
                operation = create_file_operation("download", selected_paths)
                start_background_file_operation(operation)
                payload = self._operation_payload(operation, return_path)
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse(payload)
                messages.success(request, "Download archive preparation started.")
                return redirect(self._operation_detail_url(operation, return_path))
            if action in {"copy", "move", "delete"}:
                operation = create_file_operation(
                    action,
                    selected_paths,
                    destination_path=request.POST.get("destination_path") or "",
                )
                start_background_file_operation(operation)
                messages.success(request, f"{operation.get_action_display()} operation started.")
                return redirect(self._operation_detail_url(operation, return_path))
        except (ValueError, FileOperation.DoesNotExist) as exc:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "error": str(exc)}, status=400)
            messages.error(request, str(exc))
        return redirect(f"{reverse('monitor:file-manager')}?path={current_path}")

    def _requested_action(self, request):
        if request.POST.get("folder_name"):
            return "mkdir"
        valid_actions = {
            "upload_start",
            "upload_chunk",
            "upload_finish",
            "upload",
            "mkdir",
            "download",
            "copy",
            "move",
            "delete",
        }
        for action in reversed(request.POST.getlist("file_action")):
            if action in valid_actions:
                return action
        return ""

    def _requested_path(self, request, settings_obj):
        requested_path = (request.GET.get("path") or "").strip()
        if requested_path:
            try:
                return normalize_host_path(requested_path)
            except ValueError:
                pass
        try:
            return normalize_host_path(settings_obj.file_manager_start_path or "/")
        except ValueError:
            return "/"

    def _entries(self, host_path):
        try:
            return list_file_manager_entries(host_path), ""
        except ValueError as exc:
            return [], str(exc)

    def _parent_path(self, host_path):
        normalized = normalize_host_path(host_path)
        if normalized == "/":
            return ""
        return os.path.dirname(normalized.rstrip("/")) or "/"

    def _operation_payload(self, operation, return_path=""):
        return {
            "ok": True,
            "operation_id": operation.id,
            "status_url": reverse("monitor:file-manager-operation-status", args=[operation.id]),
            "detail_url": self._operation_detail_url(operation, return_path),
            "download_url": reverse("monitor:file-manager-operation-download", args=[operation.id]),
            "summary": operation.summary,
        }

    def _return_path(self, request, fallback):
        return _return_path_from_request(request, fallback)

    def _operation_detail_url(self, operation, return_path=""):
        return _operation_detail_url(operation, return_path)


class FileManagerListView(LoginRequiredMixin, View):
    def get(self, request):
        raw_path = request.GET.get("path") or "/"
        folders_only = request.GET.get("folders_only") == "1"
        try:
            current_path = normalize_host_path(raw_path)
            entries = list_file_manager_entries(current_path, folders_only=folders_only)
        except ValueError as exc:
            return JsonResponse({"items": [], "error": str(exc)}, status=400)

        return JsonResponse(
            {
                "path": current_path,
                "parent_path": self._parent_path(current_path),
                "items": entries,
            }
        )

    def _parent_path(self, host_path):
        if host_path == "/":
            return ""
        return os.path.dirname(host_path.rstrip("/")) or "/"


class FileManagerPreviewView(LoginRequiredMixin, View):
    def get(self, request):
        path = normalize_host_path(request.GET.get("path") or "")
        absolute_path = hostfs_path(path)
        if not os.path.isfile(absolute_path):
            raise Http404("Preview not found.")
        size_bytes = os.path.getsize(absolute_path)
        content_type = mimetypes.guess_type(absolute_path)[0] or ""
        media_kind = media_kind_for_content_type(content_type)
        if media_kind == "image" and size_bytes > MAX_IMAGE_PREVIEW_BYTES:
            raise Http404("Preview is too large.")
        if media_kind == "text" and size_bytes > MAX_TEXT_PREVIEW_BYTES:
            raise Http404("Preview is too large.")
        if media_kind == "video" and size_bytes > MAX_VIDEO_PREVIEW_BYTES:
            raise Http404("Preview is too large.")
        if media_kind not in {"image", "text", "video"}:
            raise Http404("Preview is not available.")
        return FileResponse(open(absolute_path, "rb"), content_type=content_type)


class FileManagerInformationView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            session_id = request.POST.get("session_id") or ""
            if session_id:
                payload = continue_file_information(session_id)
            else:
                paths = request.POST.getlist("selected_paths") or [request.POST.get("current_path") or "/"]
                payload = start_file_information(paths)
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        return JsonResponse(payload)


class FileManagerOperationsView(LoginRequiredMixin, View):
    template_name = "file_manager_app/file_operations.html"

    def get(self, request):
        status = request.GET.get("status") or "all"
        action = request.GET.get("action") or "all"
        return_path = _return_path_from_request(request, "")
        operations_qs = FileOperation.objects.order_by("-started_at")
        if status in {choice[0] for choice in FileOperation.STATUS_CHOICES}:
            operations_qs = operations_qs.filter(status=status)
        if action in {choice[0] for choice in FileOperation.ACTION_CHOICES}:
            operations_qs = operations_qs.filter(action=action)
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        paginator = Paginator(operations_qs, 20)
        return render(
            request,
            self.template_name,
            {
                "page_obj": paginator.get_page(request.GET.get("page")),
                "status_filter": status,
                "action_filter": action,
                "status_choices": FileOperation.STATUS_CHOICES,
                "action_choices": FileOperation.ACTION_CHOICES,
                "pagination_query": pagination_params.urlencode(),
                "return_path": return_path,
                "file_manager_back_url": _file_manager_url(return_path),
                "settings_obj": MonitoringSettings.load(),
            },
        )


class FileManagerOperationDetailView(LoginRequiredMixin, View):
    template_name = "file_manager_app/file_operation_detail.html"

    def get(self, request, operation_id):
        operation = get_object_or_404(FileOperation, pk=operation_id)
        return_path = _return_path_from_request(request, "")
        return render(
            request,
            self.template_name,
            {
                "operation": operation,
                "return_path": return_path,
                "file_manager_back_url": _file_manager_url(return_path),
                "file_manager_operations_url": _operations_url(return_path),
                "settings_obj": MonitoringSettings.load(),
            },
        )

    def post(self, request, operation_id):
        operation = get_object_or_404(FileOperation, pk=operation_id)
        if "pause_operation" in request.POST:
            messages.info(request, "Pause requested." if pause_file_operation(operation) else "Operation is not running.")
        elif "cancel_operation" in request.POST:
            messages.warning(request, "Cancel requested." if cancel_file_operation(operation) else "Operation cannot be cancelled.")
        elif "resume_operation" in request.POST:
            messages.success(request, "Operation resumed." if resume_file_operation(operation) else "Operation cannot be resumed.")
        return redirect(_operation_detail_url(operation, _return_path_from_request(request, "")))


class FileManagerOperationStatusView(LoginRequiredMixin, View):
    def get(self, request, operation_id):
        operation = get_object_or_404(FileOperation, pk=operation_id)
        return JsonResponse(
            {
                "id": operation.id,
                "action": operation.action,
                "action_label": operation.get_action_display(),
                "status": operation.status,
                "status_label": operation.get_status_display(),
                "summary": operation.summary,
                "processed_count": operation.processed_count,
                "total_count": operation.total_count,
                "progress_percent": operation.progress_percent,
                "current_path": operation.current_path,
                "log_output": operation.log_output,
                "process_pid": operation.process_pid,
                "runner_label": operation.runner_label,
                "heartbeat_at": operation.heartbeat_at.isoformat() if operation.heartbeat_at else None,
                "finished_at": operation.finished_at.isoformat() if operation.finished_at else None,
                "updated_at": timezone.now().isoformat(),
                "download_url": reverse("monitor:file-manager-operation-download", args=[operation.id]) if operation.action == "download" and operation.status == "success" else "",
            }
        )


class FileManagerOperationDownloadView(LoginRequiredMixin, View):
    def get(self, request, operation_id):
        operation = get_object_or_404(FileOperation, pk=operation_id, action="download")
        if operation.status != "success":
            return JsonResponse({"error": "Download archive is not ready yet."}, status=409)
        archive_path = download_archive_path(operation.id)
        if not archive_path.exists():
            return JsonResponse({"error": "Download archive is missing."}, status=404)
        return FileResponse(open(archive_path, "rb"), as_attachment=True, filename=f"file-manager-download-{operation.id}.zip")
