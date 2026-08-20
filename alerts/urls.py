from django.urls import path

from .views import AlertDetailView, AlertsView


urlpatterns = [
    path("alerts/", AlertsView.as_view(), name="alerts"),
    path("alerts/<int:event_id>/", AlertDetailView.as_view(), name="alert-detail"),
]
