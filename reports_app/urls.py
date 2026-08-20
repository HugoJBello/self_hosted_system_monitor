from django.urls import path

from .views import ReportDetailView, ReportsView


urlpatterns = [
    path("reports/", ReportsView.as_view(), name="reports"),
    path("reports/<int:report_id>/", ReportDetailView.as_view(), name="report-detail"),
]
