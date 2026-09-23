from django.urls import path

from .views import (
    FileManagerInformationView,
    FileManagerEmbeddedThumbnailView,
    FileManagerListView,
    FileManagerOperationDetailView,
    FileManagerOperationDownloadView,
    FileManagerOperationStatusView,
    FileManagerOperationsView,
    FileManagerPreviewView,
    FileManagerSearchView,
    FileManagerView,
)
from .share_views import (
    FileShareCreateView, FileShareDetailView, FileSharesView, PublicFileShareArchiveView,
    PublicFileShareDownloadView, PublicFileShareView,
)


urlpatterns = [
    path("files/", FileManagerView.as_view(), name="file-manager"),
    path("files/shares/", FileSharesView.as_view(), name="file-shares"),
    path("files/shares/new/", FileShareCreateView.as_view(), name="file-share-create"),
    path("files/shares/<int:pk>/", FileShareDetailView.as_view(), name="file-share-detail"),
    path("shared/<str:token>/", PublicFileShareView.as_view(), name="file-share-public"),
    path("shared/<str:token>/download/", PublicFileShareDownloadView.as_view(), name="file-share-download"),
    path("shared/<str:token>/archive/<int:operation_id>/", PublicFileShareArchiveView.as_view(), name="file-share-archive"),
    path("files/list/", FileManagerListView.as_view(), name="file-manager-list"),
    path("files/information/", FileManagerInformationView.as_view(), name="file-manager-information"),
    path("files/embedded-thumbnail/", FileManagerEmbeddedThumbnailView.as_view(), name="file-manager-embedded-thumbnail"),
    path("files/preview/", FileManagerPreviewView.as_view(), name="file-manager-preview"),
    path("files/search/", FileManagerSearchView.as_view(), name="file-manager-search"),
    path("files/processes/", FileManagerOperationsView.as_view(), name="file-manager-operations"),
    path("files/processes/<int:operation_id>/download/", FileManagerOperationDownloadView.as_view(), name="file-manager-operation-download"),
    path("files/processes/<int:operation_id>/status/", FileManagerOperationStatusView.as_view(), name="file-manager-operation-status"),
    path("files/processes/<int:operation_id>/", FileManagerOperationDetailView.as_view(), name="file-manager-operation-detail"),
]
