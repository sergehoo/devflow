"""
DevFlow REST API — URL routing.
Tous les endpoints sont préfixés `/api/v1/` (voir ProjectFlow/urls.py).
"""

from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from project.api.viewsets import (
    AInsightViewSet,
    BillingRateViewSet,
    ProjectBudgetViewSet,
    ProjectEstimateLineViewSet,
    ProjectExpenseViewSet,
    ProjectMemberViewSet,
    ProjectRevenueViewSet,
    ProjectViewSet,
    SprintViewSet,
    TaskViewSet,
    TeamViewSet,
    TimesheetEntryViewSet,
    WorkspaceViewSet,
)

router = DefaultRouter()
router.register("workspaces", WorkspaceViewSet, basename="api-workspace")
router.register("teams", TeamViewSet, basename="api-team")
router.register("projects", ProjectViewSet, basename="api-project")
router.register("project-members", ProjectMemberViewSet, basename="api-project-member")
router.register("billing-rates", BillingRateViewSet, basename="api-billing-rate")
router.register("project-budgets", ProjectBudgetViewSet, basename="api-project-budget")
router.register("project-estimate-lines", ProjectEstimateLineViewSet, basename="api-estimate-line")
router.register("project-revenues", ProjectRevenueViewSet, basename="api-project-revenue")
router.register("project-expenses", ProjectExpenseViewSet, basename="api-project-expense")
router.register("sprints", SprintViewSet, basename="api-sprint")
router.register("tasks", TaskViewSet, basename="api-task")
router.register("timesheets", TimesheetEntryViewSet, basename="api-timesheet")
router.register("ai-insights", AInsightViewSet, basename="api-ai-insight")

urlpatterns = [
    path("", include(router.urls)),
    # Schema OpenAPI
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
]
