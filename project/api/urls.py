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

from project.api.views_chat import (
    ChatChannelMessagesView,
    ChatChannelsListView,
    ChatContactsView,
    ChatDirectCreateView,
    ChatGroupCreateView,
)
from project.api.views_quick import (
    AIChatStreamView,
    MyTodayView,
    TaskMoveKanbanJSONView,
    TaskQuickAssignJSONView,
    TaskSnoozeView,
    TaskToggleCompleteView,
    TaskUpdateStatusView,
)
from project.api.viewsets import (
    AdminCaseViewSet,
    AInsightViewSet,
    BillingRateViewSet,
    FieldReportViewSet,
    ProjectAIReportViewSet,
    ProjectBudgetForecastRunViewSet,
    ProjectBudgetSnapshotViewSet,
    ProjectBudgetViewSet,
    ProjectEstimateLineViewSet,
    ProjectExpenseViewSet,
    ProjectMemberViewSet,
    ProjectPhaseViewSet,
    ProjectRevenueViewSet,
    ProjectViewPreferenceViewSet,
    ProjectViewSet,
    RealEstateLotViewSet,
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

# Phase 2 — Multi-modes projet (PR12)
router.register("project-phases", ProjectPhaseViewSet, basename="api-project-phase")
router.register("project-view-preferences", ProjectViewPreferenceViewSet, basename="api-view-preference")
router.register("field-reports", FieldReportViewSet, basename="api-field-report")
router.register("real-estate-lots", RealEstateLotViewSet, basename="api-real-estate-lot")
router.register("admin-cases", AdminCaseViewSet, basename="api-admin-case")

# Phase 3 — Budget V2 (PR15)
router.register(
    "project-budget-snapshots", ProjectBudgetSnapshotViewSet,
    basename="api-budget-snapshot",
)
router.register(
    "project-budget-forecast-runs", ProjectBudgetForecastRunViewSet,
    basename="api-budget-forecast-run",
)

# Phase 5 — Rapports IA hebdomadaires (PR22)
router.register(
    "project-ai-reports", ProjectAIReportViewSet,
    basename="api-ai-report",
)

urlpatterns = [
    path("", include(router.urls)),

    # Phase 1 — Quick actions JSON (PR7)
    path("tasks/<int:pk>/toggle-complete/",
         TaskToggleCompleteView.as_view(),
         name="api-task-toggle-complete"),
    path("tasks/<int:pk>/update-status/",
         TaskUpdateStatusView.as_view(),
         name="api-task-update-status"),
    path("tasks/<int:pk>/snooze/",
         TaskSnoozeView.as_view(),
         name="api-task-snooze"),
    path("tasks/<int:pk>/quick-assign/",
         TaskQuickAssignJSONView.as_view(),
         name="api-task-quick-assign"),
    path("tasks/<int:pk>/move-kanban/",
         TaskMoveKanbanJSONView.as_view(),
         name="api-task-move-kanban"),
    path("me/today/", MyTodayView.as_view(), name="api-me-today"),

    # Phase 4 — Streaming SSE chat IA (PR20)
    path("ai/chat/stream/", AIChatStreamView.as_view(), name="api-ai-chat-stream"),

    # ────── Chat collaborateurs (DM + groupes) — PR Chat ──────
    path("me/chat/channels/",
         ChatChannelsListView.as_view(),
         name="api-chat-channels"),
    path("me/chat/direct/",
         ChatDirectCreateView.as_view(),
         name="api-chat-direct-create"),
    path("me/chat/groups/",
         ChatGroupCreateView.as_view(),
         name="api-chat-group-create"),
    path("me/chat/channels/<int:pk>/messages/",
         ChatChannelMessagesView.as_view(),
         name="api-chat-messages"),
    path("me/chat/contacts/",
         ChatContactsView.as_view(),
         name="api-chat-contacts"),

    # Schema OpenAPI
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
]
