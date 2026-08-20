from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from main_app.forms import MonitoringSettingsForm
from main_app.models import MonitoringSettings, SystemSnapshot
from main_app.notification_client import build_test_payload, send_json_notification


User = get_user_model()

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

@method_decorator(csrf_exempt, name="dispatch")
class SettingsView(AdminRequiredMixin, View):
    template_name = "main_app/settings.html"

    def get(self, request):
        settings_obj = MonitoringSettings.load()
        form = MonitoringSettingsForm(instance=settings_obj)
        return render(request, self.template_name, self._context(form, settings_obj))

    def post(self, request):
        settings_obj = MonitoringSettings.load()
        form = MonitoringSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            settings_obj = form.save()
            if "send_test_notification" in request.POST:
                if not settings_obj.notifications_enabled:
                    messages.warning(request, "Notifications are disabled. Enable them before sending a test.")
                elif not settings_obj.notifications_api_url or not settings_obj.notifications_api_token:
                    messages.error(request, "Notifications API URL and API token are required to send a test.")
                else:
                    latest_snapshot = SystemSnapshot.objects.order_by("-captured_at").first()
                    payload = build_test_payload(settings_obj, latest_snapshot)
                    result = send_json_notification(settings_obj, payload)
                    if result["ok"]:
                        messages.success(
                            request,
                            f"Test notification delivered with HTTP {result['status_code']}.",
                        )
                    else:
                        messages.error(
                            request,
                            f"Test notification failed ({result['status_code'] or 'connection error'}): {result['body']}",
                        )
            else:
                messages.success(request, "Monitoring settings updated.")
            return redirect("monitor:settings")
        return render(request, self.template_name, self._context(form, settings_obj))

    def _context(self, form, settings_obj):
        return {
            "form": form,
            "settings_obj": settings_obj,
            "settings_users": list(User.objects.order_by("username")),
        }
