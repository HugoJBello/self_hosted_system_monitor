from django.urls import path

from .views import (
    ScriptJobCreateView,
    ScriptJobEditView,
    ScriptJobRunDetailView,
    ScriptJobRunsView,
    ScriptJobRunStatusView,
    ScriptJobsView,
)


urlpatterns = [
    path("jobs/new/", ScriptJobCreateView.as_view(), name="script-job-create"),
    path("jobs/<int:job_id>/edit/", ScriptJobEditView.as_view(), name="script-job-edit"),
    path("jobs/", ScriptJobsView.as_view(), name="script-jobs"),
    path("jobs/runs/", ScriptJobRunsView.as_view(), name="script-job-runs"),
    path("jobs/runs/<int:run_id>/status/", ScriptJobRunStatusView.as_view(), name="script-job-run-status"),
    path("jobs/runs/<int:run_id>/", ScriptJobRunDetailView.as_view(), name="script-job-run-detail"),
]
