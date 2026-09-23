import mimetypes
import os
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator

from file_manager_app.models import FileOperation, FileShare, UserFileAccess
from file_manager_app.services import create_file_operation, download_archive_path, start_background_file_operation
from file_manager_app.sharing import can_access_share, parse_expiry, public_share_url, record_share_access, record_share_view_once, resolve_share_path, shared_archive_sources, shared_entries, validate_shared_paths
from main_app.models import MonitoringSettings


def _owned_share(user, pk):
    queryset = FileShare.objects.all() if user.is_superuser else FileShare.objects.filter(created_by=user)
    return get_object_or_404(queryset, pk=pk)


def _authorized_share(request, token):
    share = get_object_or_404(FileShare.objects.select_related("created_by", "recipient"), token=token)
    if not can_access_share(share, request.user, token_present=True):
        raise Http404("This share is unavailable.")
    return share


def _share_context(request, share, **extra):
    context = {
        "share": share,
        "share_url": public_share_url(request, share, MonitoringSettings.load()),
        "settings_obj": MonitoringSettings.load(),
    }
    context.update(extra)
    return context


def _sync_share_grants(share):
    share.access_grants.all().delete()
    if share.recipient_id:
        UserFileAccess.objects.bulk_create([
            UserFileAccess(user=share.recipient, path=path, granted_by=share.created_by, source_share=share)
            for path in share.paths
        ])


class ShareAdminMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff or self.request.user.is_superuser


class FileShareCreateView(LoginRequiredMixin, ShareAdminMixin, View):
    template_name = "file_manager_app/file_share_form.html"

    def post(self, request):
        try:
            paths = validate_shared_paths(request.POST.getlist("selected_paths"))
            if request.POST.get("save_share"):
                recipient_id = request.POST.get("recipient") or None
                recipient = get_user_model().objects.filter(pk=recipient_id, is_active=True).first() if recipient_id else None
                if recipient_id and not recipient:
                    raise ValueError("Choose a valid active user.")
                public_link = request.POST.get("public_link") == "1"
                if not public_link and not recipient:
                    raise ValueError("Choose a user or enable access for anyone with the link.")
                share = FileShare.objects.create(
                    name=(request.POST.get("name") or "").strip()[:160], paths=paths,
                    created_by=request.user, recipient=recipient, public_link=public_link,
                    expires_at=parse_expiry(request.POST.get("expires_at") or ""),
                )
                _sync_share_grants(share)
                messages.success(request, "Share created.")
                return redirect("monitor:file-share-detail", pk=share.pk)
        except ValueError as exc:
            messages.error(request, str(exc))
            paths = request.POST.getlist("selected_paths")
        return render(request, self.template_name, {
            "paths": paths,
            "users": get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("username"),
            "settings_obj": MonitoringSettings.load(),
        })


class FileSharesView(LoginRequiredMixin, View):
    template_name = "file_manager_app/file_shares.html"
    def get(self, request):
        owned = FileShare.objects.filter(created_by=request.user).select_related("recipient")
        received = FileShare.objects.filter(recipient=request.user).exclude(created_by=request.user).select_related("created_by")
        return render(request, self.template_name, {"owned_shares": owned, "received_shares": received, "settings_obj": MonitoringSettings.load()})


class FileShareDetailView(LoginRequiredMixin, ShareAdminMixin, View):
    template_name = "file_manager_app/file_share_detail.html"
    def get(self, request, pk):
        share = _owned_share(request.user, pk)
        return render(request, self.template_name, _share_context(request, share, users=get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("username")))

    def post(self, request, pk):
        share = _owned_share(request.user, pk)
        try:
            if "revoke" in request.POST:
                share.revoked_at = timezone.now()
                share.save(update_fields=["revoked_at", "updated_at"])
                messages.success(request, "Share revoked immediately.")
            elif "restore" in request.POST:
                share.revoked_at = None
                share.save(update_fields=["revoked_at", "updated_at"])
                messages.success(request, "Share restored.")
            else:
                recipient_id = request.POST.get("recipient") or None
                recipient = get_user_model().objects.filter(pk=recipient_id, is_active=True).first() if recipient_id else None
                public_link = request.POST.get("public_link") == "1"
                if recipient_id and not recipient:
                    raise ValueError("Choose a valid active user.")
                if not public_link and not recipient:
                    raise ValueError("Choose a user or enable link access.")
                share.name = (request.POST.get("name") or "").strip()[:160]
                share.recipient = recipient
                share.public_link = public_link
                share.expires_at = parse_expiry(request.POST.get("expires_at") or "")
                share.save()
                _sync_share_grants(share)
                messages.success(request, "Share updated.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("monitor:file-share-detail", pk=pk)


@method_decorator(never_cache, name="dispatch")
class PublicFileShareView(View):
    template_name = "file_manager_app/file_share_public.html"
    def get(self, request, token):
        share = _authorized_share(request, token)
        record_share_view_once(request, share)
        relative = request.GET.get("path") or ""
        try:
            entries, parent = shared_entries(share, relative)
        except ValueError as exc:
            raise Http404(str(exc))
        operation = share.download_operations.order_by("-created_at").first()
        return render(request, self.template_name, _share_context(request, share, entries=entries, relative_path=relative, parent_path=parent, operation=operation))

    def post(self, request, token):
        share = _authorized_share(request, token)
        try:
            sources = shared_archive_sources(share, request.POST.get("archive_path") or "")
        except ValueError as exc:
            raise Http404(str(exc))
        operation = create_file_operation("download", sources, created_by=share.created_by)
        operation.file_share = share
        operation.save(update_fields=["file_share"])
        start_background_file_operation(operation)
        target = reverse("monitor:file-share-public", args=[token])
        current_path = request.POST.get("current_path") or ""
        return redirect(f"{target}?path={quote(current_path)}" if current_path else target)


class PublicFileShareDownloadView(View):
    def get(self, request, token):
        share = _authorized_share(request, token)
        relative = request.GET.get("path") or ""
        try:
            _, absolute = resolve_share_path(share, relative)
        except ValueError as exc:
            raise Http404(str(exc))
        if not os.path.isfile(absolute):
            raise Http404("File not found.")
        record_share_access(request, share, "download", relative)
        return FileResponse(open(absolute, "rb"), as_attachment=True, filename=os.path.basename(absolute), content_type=mimetypes.guess_type(absolute)[0])


class PublicFileShareArchiveView(View):
    def get(self, request, token, operation_id):
        share = _authorized_share(request, token)
        operation = get_object_or_404(FileOperation, pk=operation_id, action="download", file_share=share)
        if operation.status != "success":
            return JsonResponse({"error": "Archive is not ready."}, status=409)
        path = download_archive_path(operation.pk)
        if not path.exists():
            raise Http404("Archive not found.")
        record_share_access(request, share, "archive")
        return FileResponse(open(path, "rb"), as_attachment=True, filename=f"{share.name or 'shared-files'}.zip")
