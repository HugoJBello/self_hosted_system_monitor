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
from file_manager_app.models import FileOperation, FileSearch
from file_manager_app.search import (
    SEARCH_DEFAULT_TIMEOUT,
    SEARCH_RESULT_LIMIT,
    SEARCH_TIMEOUT_OPTIONS,
    create_search_operation,
    search_operation_url,
    search_result_items,
)
from file_manager_app.services import (
    cancel_file_operation,
    create_file_operation,
    download_archive_path,
    finish_chunked_upload,
    pause_file_operation,
    resume_file_operation,
    save_uploaded_files,
    save_upload_chunk,
    rsync_available,
    start_chunked_upload,
    start_background_file_operation,
)
from file_manager_app.sorting import SORT_DIRECTIONS, SORT_FIELDS, normalize_sort, sort_entries
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
        sort_field, sort_direction = normalize_sort(request.GET.get("sort"), request.GET.get("direction"))
        entries, error = self._entries(current_path, sort_field, sort_direction)
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
                "rsync_available": rsync_available(),
                "sort_field": sort_field,
                "sort_direction": sort_direction,
                "sort_fields": SORT_FIELDS,
                "sort_directions": SORT_DIRECTIONS,
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
                    transfer_method=request.POST.get("transfer_method") or "standard",
                    rsync_delete=request.POST.get("rsync_delete") == "1",
                    conflict_policy=request.POST.get("conflict_policy") or "overwrite",
                    folder_conflict_policy=request.POST.get("folder_conflict_policy") or "merge",
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

    def _entries(self, host_path, sort_field="name", sort_direction="asc"):
        try:
            return list_file_manager_entries(host_path, sort_field=sort_field, sort_direction=sort_direction), ""
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
        sort_field, sort_direction = normalize_sort(request.GET.get("sort"), request.GET.get("direction"))
        try:
            current_path = normalize_host_path(raw_path)
            entries = list_file_manager_entries(
                current_path,
                folders_only=folders_only,
                sort_field=sort_field,
                sort_direction=sort_direction,
            )
        except ValueError as exc:
            return JsonResponse({"items": [], "error": str(exc)}, status=400)

        return JsonResponse(
            {
                "path": current_path,
                "parent_path": self._parent_path(current_path),
                "items": entries,
                "sort_field": sort_field,
                "sort_direction": sort_direction,
            }
        )

    def _parent_path(self, host_path):
        if host_path == "/":
            return ""
        return os.path.dirname(host_path.rstrip("/")) or "/"


class FileManagerSearchView(LoginRequiredMixin, View):
    template_name = "file_manager_app/file_search.html"

    def get(self, request):
        settings_obj = MonitoringSettings.load()
        operation = None
        search = None
        operation_id = request.GET.get("operation_id") or ""
        if operation_id:
            operation = get_object_or_404(FileOperation, pk=operation_id, action="search")
            search = get_object_or_404(FileSearch, operation=operation)
            root_path = search.root_path
            query = search.query
            recursive = search.recursive
            case_sensitive = search.case_sensitive
            use_regex = search.use_regex
            timeout_seconds = search.timeout_seconds
            all_results = search_result_items(search)
            truncated = search.truncated
            timed_out = search.timed_out
            search_error = operation.summary if operation.status == "failed" else ""
        else:
            root_path = request.GET.get("path") or settings_obj.file_manager_start_path or "/"
            try:
                root_path = normalize_host_path(root_path)
            except ValueError:
                root_path = "/"
            query = ""
            recursive = True
            case_sensitive = False
            use_regex = False
            timeout_seconds = SEARCH_DEFAULT_TIMEOUT
            all_results = []
            truncated = False
            timed_out = False
            search_error = ""
        sort_field, sort_direction = normalize_sort(request.GET.get("sort"), request.GET.get("direction"))
        kind_filter = request.GET.get("kind") if request.GET.get("kind") in {"all", "file", "folder"} else "all"
        if kind_filter != "all":
            all_results = [item for item in all_results if item.get("kind") == kind_filter]
        all_results = sort_entries(all_results, sort_field, sort_direction)
        raw_page_size = request.GET.get("page_size") or "25"
        page_size = int(raw_page_size) if str(raw_page_size).isdigit() and int(raw_page_size) in {25, 50, 100} else 25
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        page_obj = Paginator(all_results, page_size).get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "settings_obj": settings_obj,
                "root_path": root_path,
                "query": query,
                "recursive": recursive,
                "case_sensitive": case_sensitive,
                "use_regex": use_regex,
                "timeout_seconds": timeout_seconds,
                "timeout_options": SEARCH_TIMEOUT_OPTIONS,
                "results": page_obj.object_list,
                "all_result_count": len(all_results),
                "page_obj": page_obj,
                "kind_filter": kind_filter,
                "page_size": page_size,
                "pagination_query": pagination_params.urlencode(),
                "result_limit": SEARCH_RESULT_LIMIT,
                "truncated": truncated,
                "timed_out": timed_out,
                "search_error": search_error,
                "sort_field": sort_field,
                "sort_direction": sort_direction,
                "sort_fields": SORT_FIELDS,
                "sort_directions": SORT_DIRECTIONS,
                "operation": operation,
                "search": search,
            },
        )

    def post(self, request):
        if request.POST.get("operation_id"):
            operation = get_object_or_404(FileOperation, pk=request.POST.get("operation_id"), action="search")
            if request.POST.get("cancel_search"):
                cancel_file_operation(operation)
            return redirect(search_operation_url(operation))
        root_path = request.POST.get("path") or MonitoringSettings.load().file_manager_start_path or "/"
        try:
            operation = create_search_operation(
                root_path,
                request.POST.get("q") or "",
                recursive=request.POST.get("recursive") == "1",
                timeout_seconds=request.POST.get("timeout") or SEARCH_DEFAULT_TIMEOUT,
                case_sensitive=request.POST.get("case_sensitive") == "1",
                use_regex=request.POST.get("use_regex") == "1",
            )
        except ValueError as exc:
            return render(request, self.template_name, {
                "settings_obj": MonitoringSettings.load(),
                "root_path": root_path,
                "query": request.POST.get("q") or "",
                "recursive": request.POST.get("recursive") == "1",
                "case_sensitive": request.POST.get("case_sensitive") == "1",
                "use_regex": request.POST.get("use_regex") == "1",
                "timeout_seconds": request.POST.get("timeout") or SEARCH_DEFAULT_TIMEOUT,
                "timeout_options": SEARCH_TIMEOUT_OPTIONS,
                "results": [],
                "result_limit": SEARCH_RESULT_LIMIT,
                "truncated": False,
                "timed_out": False,
                "search_error": str(exc),
                "sort_field": "name",
                "sort_direction": "asc",
                "sort_fields": SORT_FIELDS,
                "sort_directions": SORT_DIRECTIONS,
                "kind_filter": "all",
                "page_size": 25,
                "pagination_query": "",
            }, status=400)
        from file_manager_app.services import start_background_file_operation

        start_background_file_operation(operation)
        return redirect(search_operation_url(operation))


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
        search = getattr(operation, "search", None)
        return render(
            request,
            self.template_name,
            {
                "operation": operation,
                "return_path": return_path,
                "file_manager_back_url": _file_manager_url(return_path),
                "file_manager_operations_url": _operations_url(return_path),
                "settings_obj": MonitoringSettings.load(),
                "search": search,
                "search_url": search_operation_url(operation) if search else "",
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
        search = getattr(operation, "search", None)
        search_items = search_result_items(search) if search else []
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
                "transfer_method": operation.transfer_method,
                "transfer_method_label": operation.get_transfer_method_display(),
                "rsync_delete": operation.rsync_delete,
                "conflict_policy": operation.conflict_policy,
                "conflict_policy_label": operation.get_conflict_policy_display(),
                "folder_conflict_policy": operation.folder_conflict_policy,
                "folder_conflict_policy_label": operation.get_folder_conflict_policy_display(),
                "log_output": operation.log_output,
                "process_pid": operation.process_pid,
                "runner_label": operation.runner_label,
                "heartbeat_at": operation.heartbeat_at.isoformat() if operation.heartbeat_at else None,
                "finished_at": operation.finished_at.isoformat() if operation.finished_at else None,
                "updated_at": timezone.now().isoformat(),
                "download_url": reverse("monitor:file-manager-operation-download", args=[operation.id]) if operation.action == "download" and operation.status == "success" else "",
                "search_result_count": search.result_count if search else None,
                "search_results": search_items if search else [],
                "search_truncated": search.truncated if search else False,
                "search_timed_out": search.timed_out if search else False,
                "search_url": search_operation_url(operation) if search else "",
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
