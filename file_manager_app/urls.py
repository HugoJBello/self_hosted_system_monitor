from django.urls import path

from .views import (
    FileManagerInformationView,
    FileManagerListView,
    FileManagerOperationDetailView,
    FileManagerOperationDownloadView,
    FileManagerOperationStatusView,
    FileManagerOperationsView,
    FileManagerPreviewView,
    FileManagerView,
)


urlpatterns = [
    path("files/", FileManagerView.as_view(), name="file-manager"),
    path("files/list/", FileManagerListView.as_view(), name="file-manager-list"),
    path("files/information/", FileManagerInformationView.as_view(), name="file-manager-information"),
    path("files/preview/", FileManagerPreviewView.as_view(), name="file-manager-preview"),
    path("files/processes/", FileManagerOperationsView.as_view(), name="file-manager-operations"),
    path("files/processes/<int:operation_id>/download/", FileManagerOperationDownloadView.as_view(), name="file-manager-operation-download"),
    path("files/processes/<int:operation_id>/status/", FileManagerOperationStatusView.as_view(), name="file-manager-operation-status"),
    path("files/processes/<int:operation_id>/", FileManagerOperationDetailView.as_view(), name="file-manager-operation-detail"),
]
