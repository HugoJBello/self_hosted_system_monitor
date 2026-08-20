from django.urls import path

from .views import VolumeOperationDetailView, VolumeOperationStatusView, VolumeOperationsView, VolumeTreeView, VolumesView


urlpatterns = [
    path("volumes/", VolumesView.as_view(), name="volumes"),
    path("volumes/tree/", VolumeTreeView.as_view(), name="volume-tree"),
    path("volumes/operations/", VolumeOperationsView.as_view(), name="volume-operations"),
    path("volumes/operations/<int:operation_id>/status/", VolumeOperationStatusView.as_view(), name="volume-operation-status"),
    path("volumes/operations/<int:operation_id>/", VolumeOperationDetailView.as_view(), name="volume-operation-detail"),
]
