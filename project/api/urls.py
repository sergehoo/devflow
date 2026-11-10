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

from project.api.resources import (  # noqa: E402
    ResourceActionView, ResourceDeleteView, ResourceDetailView, ResourceListView, ResourceRegistryView,
)
from project.api.form_bridge import LegacyActionView, LegacyFormView
from project.api.views_dashboard import DashboardInsightsView, DashboardSummaryView
from project.api.views_teams import TeamMembersView
from project.api.views_timesheets import TimesheetEntriesView, TimesheetWeeksView, TimesheetWeekView
from project.api.views_auth import (
    CsrfView,
    LoginView,
    LogoutView,
    MeView,
    WorkspaceSwitchView,
)
from project.api.views_chat import (
    ChatChannelMembersView,
    ChatChannelMessagesView,
    ChatChannelsListView,
    ChatContactsView,
    ChatConversationsView,
    ChatDirectCreateView,
    ChatGroupCreateView,
    ChatMarkReadView,
    ChatReactionView,
    ChatUnreadCountView,
)
from project.api.views_notifications import (  # noqa: E402
    NotificationDeleteView, NotificationListView, NotificationPreferenceView, NotificationReadAllView,
    NotificationReadView, NotificationSummaryView,
)
from project.api.views_presence import (
    PresenceBatchView,
    PresenceHeartbeatView,
)
from project.api.views_quick import (
    AIChatStreamView,
    MyTodayView,
    TaskMoveKanbanJSONView,
    TaskAssigneesJSONView,
    TaskQuickAssignJSONView,
    TaskQuickUpdateView,
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
    path("tasks/<int:pk>/quick-update/",
         TaskQuickUpdateView.as_view(),
         name="api-task-quick-update"),
    path("tasks/<int:pk>/assignees/",
         TaskAssigneesJSONView.as_view(),
         name="api-task-assignees"),
    path("tasks/<int:pk>/move-kanban/",
         TaskMoveKanbanJSONView.as_view(),
         name="api-task-move-kanban"),
    path("me/today/", MyTodayView.as_view(), name="api-me-today"),

    # Phase 4 — Streaming SSE chat IA (PR20)
    path("ai/chat/stream/", AIChatStreamView.as_view(), name="api-ai-chat-stream"),

    # ────── Chat collaborateurs (DM + groupes) — PR Chat ──────
    # Frontend React — authentification par session
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="api-dashboard-summary"),
    path("dashboard/insights/", DashboardInsightsView.as_view(), name="api-dashboard-insights"),
    path("resources/", ResourceRegistryView.as_view(), name="api-resources"),
    path("resources/<slug:name>/", ResourceListView.as_view(), name="api-resource-list"),
    path("resources/<slug:name>/<int:pk>/", ResourceDetailView.as_view(), name="api-resource-detail"),
    path("resources/<slug:name>/<int:pk>/delete/", ResourceDeleteView.as_view(), name="api-resource-delete"),
    path("resources/<slug:name>/<int:pk>/actions/<slug:action>/", ResourceActionView.as_view(),
         name="api-resource-action"),
    path("forms/<slug:name>/", LegacyFormView.as_view(), name="api-form"),
    path("forms/<slug:name>/<int:pk>/", LegacyFormView.as_view(), name="api-form-instance"),
    path("team-members/", TeamMembersView.as_view(), name="api-team-members"),
    path("timesheet/week/", TimesheetWeekView.as_view(), name="api-timesheet-week"),
    path("timesheet/weeks/", TimesheetWeeksView.as_view(), name="api-timesheet-weeks"),
    path("timesheet/entries/", TimesheetEntriesView.as_view(), name="api-timesheet-entries"),
    path("actions/<slug:name>/", LegacyActionView.as_view(), name="api-action"),
    path("actions/<slug:name>/<int:pk>/", LegacyActionView.as_view(), name="api-action-instance"),
    path("auth/csrf/", CsrfView.as_view(), name="api-auth-csrf"),
    path("auth/me/", MeView.as_view(), name="api-auth-me"),
    path("auth/login/", LoginView.as_view(), name="api-auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="api-auth-logout"),
    path("auth/workspace/", WorkspaceSwitchView.as_view(), name="api-auth-workspace"),
    path("me/chat/conversations/", ChatConversationsView.as_view(), name="api-chat-conversations"),
    path("me/chat/messages/<int:pk>/reactions/", ChatReactionView.as_view(), name="api-chat-reaction"),
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
    path("me/chat/unread/",
         ChatUnreadCountView.as_view(),
         name="api-chat-unread"),
    path("me/chat/channels/<int:pk>/mark-read/",
         ChatMarkReadView.as_view(),
         name="api-chat-mark-read"),
    path("me/chat/channels/<int:pk>/members/",
         ChatChannelMembersView.as_view(),
         name="api-chat-channel-members"),

    # ────── Notifications (frontend React, Phase 4) ──────
    path("me/notifications/", NotificationListView.as_view(), name="api-notifications"),
    path("me/notifications/summary/", NotificationSummaryView.as_view(), name="api-notifications-summary"),
    path("me/notifications/read-all/", NotificationReadAllView.as_view(), name="api-notifications-read-all"),
    path("me/notifications/<int:pk>/read/", NotificationReadView.as_view(), name="api-notification-read"),
    path("me/notifications/<int:pk>/", NotificationDeleteView.as_view(), name="api-notification-delete"),
    path("me/notification-preferences/", NotificationPreferenceView.as_view(), name="api-notification-preferences"),

    # ────── Présence en ligne / inactif (PR-CHAT-1) ──────
    path("me/presence/heartbeat/",
         PresenceHeartbeatView.as_view(),
         name="api-presence-heartbeat"),
    path("me/presence/",
         PresenceBatchView.as_view(),
         name="api-presence-batch"),

    # Schema OpenAPI
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
]

# --- meetings ---
# Réunions, séries, décisions et enregistrements (frontend React). L'upload audio
# ``meetings/<id>/recordings/upload/`` recouvre volontairement la route historique
# ``api_recording_upload`` (ProjectFlow/urls.py, résolue après cet include) : même vue,
# plus le quota IA (AIActionRateThrottle) pour les deux interfaces.
from project.api import views_meetings as vmt  # noqa: E402

urlpatterns += [
    path("meetings/", vmt.MeetingListView.as_view(), name="api-meetings"),
    path("meetings/dashboard/", vmt.MeetingDashboardView.as_view(), name="api-meetings-dashboard"),
    path("meetings/decisions/", vmt.MeetingDecisionsView.as_view(), name="api-meetings-decisions"),
    path("meetings/series/", vmt.MeetingSeriesListView.as_view(), name="api-meeting-series"),
    path("meetings/series/<int:pk>/", vmt.MeetingSeriesDetailView.as_view(), name="api-meeting-series-detail"),
    path("meetings/actions/<int:item_pk>/convert/", vmt.MeetingActionItemConvertAction.as_view(),
         name="api-meeting-action-convert"),
    path("meetings/recordings/<int:recording_pk>/", vmt.MeetingRecordingDetailView.as_view(),
         name="api-meeting-recording"),
    path("meetings/recordings/<int:recording_pk>/status/", vmt.MeetingRecordingStatusView.as_view(),
         name="api-meeting-recording-status"),
    path("meetings/recordings/<int:recording_pk>/speakers/", vmt.RecordingSpeakerMappingAction.as_view(),
         name="api-meeting-recording-speakers"),
    path("meetings/recordings/<int:recording_pk>/confirm-speakers/", vmt.RecordingConfirmSpeakersAction.as_view(),
         name="api-meeting-recording-confirm"),
    path("meetings/recordings/<int:recording_pk>/regenerate/", vmt.RecordingRegenerateAction.as_view(),
         name="api-meeting-recording-regenerate"),
    path("meetings/recordings/<int:recording_pk>/delete/", vmt.RecordingDeleteAction.as_view(),
         name="api-meeting-recording-delete"),
    path("meetings/recordings/<int:recording_pk>/decisions/", vmt.RecordingAcceptDecisionsAction.as_view(),
         name="api-meeting-recording-decisions"),
    path("meetings/recordings/<int:recording_pk>/actions/", vmt.RecordingCreateActionsAction.as_view(),
         name="api-meeting-recording-actions"),
    path("meetings/recordings/<int:recording_pk>/suggestions/", vmt.RecordingConvertSuggestionsAction.as_view(),
         name="api-meeting-recording-suggestions"),
    path("meetings/recordings/<int:recording_pk>/send-minutes/", vmt.RecordingSendMinutesView.as_view(),
         name="api-meeting-recording-send"),
    path("meetings/<int:pk>/", vmt.MeetingDetailView.as_view(), name="api-meeting-detail"),
    path("meetings/<int:meeting_pk>/ai-process/", vmt.MeetingAIProcessAction.as_view(), name="api-meeting-ai-process"),
    path("meetings/<int:pk>/ai-summary/", vmt.MeetingAISummaryAction.as_view(), name="api-meeting-ai-summary"),
    path("meetings/<int:pk>/send-minutes/", vmt.MeetingSendMinutesView.as_view(), name="api-meeting-send-minutes"),
    path("meetings/<int:pk>/reviews/", vmt.MeetingReviewsSaveAction.as_view(), name="api-meeting-reviews"),
    path("meetings/<int:meeting_pk>/rsvp/", vmt.MeetingRSVPAction.as_view(), name="api-meeting-rsvp"),
    path("meetings/<int:meeting_pk>/confirm-presence/", vmt.MeetingSelfPresentAction.as_view(),
         name="api-meeting-confirm-presence"),
    path("meetings/<int:meeting_pk>/attendance/", vmt.MeetingAttendanceAction.as_view(), name="api-meeting-attendance"),
    path("meetings/<int:meeting_pk>/agenda/", vmt.MeetingAgendaCreateAction.as_view(), name="api-meeting-agenda-create"),
    path("meetings/<int:meeting_pk>/agenda/reorder/", vmt.MeetingAgendaReorderAction.as_view(),
         name="api-meeting-agenda-reorder"),
    path("meetings/<int:meeting_pk>/agenda/<int:item_pk>/", vmt.MeetingAgendaUpdateAction.as_view(),
         name="api-meeting-agenda-update"),
    path("meetings/<int:meeting_pk>/agenda/<int:item_pk>/delete/", vmt.MeetingAgendaDeleteAction.as_view(),
         name="api-meeting-agenda-delete"),
    path("meetings/<int:meeting_pk>/actions/", vmt.MeetingActionItemCreateAction.as_view(),
         name="api-meeting-action-create"),
    path("meetings/<int:meeting_pk>/recordings/upload/", vmt.MeetingRecordingUploadView.as_view(),
         name="api-meeting-recording-upload"),
]

# --- ticketing ---
from rest_framework.routers import SimpleRouter  # noqa: E402

from django.views.decorators.csrf import csrf_exempt  # noqa: E402

from project.api import views_ticketing as vtk  # noqa: E402

ticket_router = SimpleRouter()
ticket_router.register("tickets", vtk.TicketViewSet, basename="api-ticket")
ticket_router.register("ticket-applications", vtk.ExternalApplicationViewSet, basename="api-ticket-application")
ticket_router.register("ticket-routing-rules", vtk.TicketRoutingRuleViewSet, basename="api-ticket-routing-rule")
ticket_router.register("ticket-sla-policies", vtk.TicketSLAPolicyViewSet, basename="api-ticket-sla-policy")
ticket_router.register("ticket-mailboxes", vtk.TicketMailboxViewSet, basename="api-ticket-mailbox")

urlpatterns += [
    # API d'intégration (applications externes, authentification HMAC / identifiants dédiés)
    path("integrations/tickets/", vtk.IntegrationTicketListCreateView.as_view(), name="api-integration-tickets"),
    path("integrations/tickets/<str:external_id>/", vtk.IntegrationTicketDetailView.as_view(),
         name="api-integration-ticket-detail"),
    path("integrations/tickets/<str:external_id>/comments/", vtk.IntegrationTicketCommentView.as_view(),
         name="api-integration-ticket-comments"),
    # Canal e-mail : webhook entrant du fournisseur (signature HMAC, sans session ni CSRF)
    path("integrations/mail/<str:inbound_key>/", csrf_exempt(vtk.inbound_mail_webhook), name="api-integration-mail"),
    path("", include(ticket_router.urls)),
]
# --- fin ticketing ---
# --- ai ---
# Structuration automatique des projets par l'IA (Genesis, propositions,
# import documentaire, copilote) — frontend React. Voir project/api/views_ai.py.
from project.api import views_ai as _ai  # noqa: E402

urlpatterns += [
    path("ai/status/", _ai.AIStatusView.as_view(), name="api-ai-status"),
    path("ai/genesis/", _ai.GenesisView.as_view(), name="api-ai-genesis"),
    path("ai-proposals/", _ai.AIProposalListView.as_view(), name="api-ai-proposal-list"),
    path("ai-proposals/<int:pk>/", _ai.AIProposalDetailView.as_view(), name="api-ai-proposal-detail"),
    path("ai-proposals/<int:pk>/items/<int:item_pk>/form/", _ai.AIProposalItemFormView.as_view(),
         name="api-ai-proposal-item-form"),
    path("ai-proposals/<int:pk>/items/<int:item_pk>/<slug:action>/", _ai.AIProposalItemActionView.as_view(),
         name="api-ai-proposal-item-action"),
    path("ai-proposals/<int:pk>/<slug:action>/", _ai.AIProposalActionView.as_view(), name="api-ai-proposal-action"),
    path("projects/<int:pk>/ai-proposals/", _ai.ProjectAIProposalsView.as_view(), name="api-project-ai-proposals"),
    path("projects/<int:pk>/ai-proposals/trigger/", _ai.ProjectAIProposalTriggerAPIView.as_view(),
         name="api-project-ai-proposal-trigger"),
    path("projects/<int:pk>/ai-proposals/status/", _ai.ProjectAIProposalStatusAPIView.as_view(),
         name="api-project-ai-proposal-status"),
    path("projects/<int:pk>/copilot/", _ai.ProjectCopilotChatView.as_view(), name="api-project-copilot"),
    path("projects/<int:pk>/copilot/logs/", _ai.ProjectCopilotLogsView.as_view(), name="api-project-copilot-logs"),
    path("imports/", _ai.ImportListView.as_view(), name="api-import-list"),
    path("imports/<int:pk>/", _ai.ImportDetailView.as_view(), name="api-import-detail"),
    path("imports/<int:pk>/analyze/", _ai.ImportAnalyzeView.as_view(), name="api-import-analyze"),
]
# --- fin ai ---
# --- projet ---
# Fiche projet complète React (contexte ProjectDetailView, onglets paresseux) + actions de la fiche.
from project.api.views_projet import (  # noqa: E402
    ProjectAIForecastView, ProjectAIGenerationView, ProjectAIRiskAnalysisView, ProjectDetailTabsView,
    ProjectInvoiceGenerateView,
)

urlpatterns += [
    path("projects/<int:pk>/detail-tabs/", ProjectDetailTabsView.as_view(), name="api-project-detail-tabs"),
    path("projects/<int:pk>/detail-tabs/ai-forecast/", ProjectAIForecastView.as_view(),
         name="api-project-detail-ai-forecast"),
    path("projects/<int:pk>/detail-tabs/ai-risk-analysis/", ProjectAIRiskAnalysisView.as_view(),
         name="api-project-detail-ai-risk-analysis"),
    path("projects/<int:pk>/detail-tabs/ai-generation/", ProjectAIGenerationView.as_view(),
         name="api-project-detail-ai-generation"),
    path("projects/<int:pk>/detail-tabs/invoice-generate/", ProjectInvoiceGenerateView.as_view(),
         name="api-project-detail-invoice-generate"),
]

# --- finance ---
from project.api import views_finance as vfi  # noqa: E402

urlpatterns += [
    path("finance/portfolio/", vfi.FinancePortfolioView.as_view(), name="api-finance-portfolio"),
    path("finance/allocation/", vfi.FinanceAllocationView.as_view(), name="api-finance-allocation"),
    path("invoices/<int:pk>/lines/", vfi.InvoiceLinesAPI.as_view(), name="api-invoice-lines"),
    path("invoices/<int:pk>/lines/reorder/", vfi.InvoiceReorderAPI.as_view(), name="api-invoice-lines-reorder"),
    path("invoices/<int:pk>/totals/", vfi.InvoiceTotalsAPI.as_view(), name="api-invoice-totals"),
    path("invoices/<int:pk>/payments/", vfi.InvoicePaymentsAPI.as_view(), name="api-invoice-payments"),
    path("invoice-lines/<int:pk>/", vfi.InvoiceLineAPI.as_view(), name="api-invoice-line"),
]
# --- fin finance ---

# --- agile ---
from project.api import views_agile as vag  # noqa: E402

urlpatterns += [
    path("sprints/<int:pk>/status/", vag.SprintStatusAPI.as_view(), name="api-sprint-status"),
    path("roadmap-items/<int:pk>/shift-dates/", vag.RoadmapShiftAPI.as_view(), name="api-roadmap-item-shift"),
]
# --- fin agile ---

# --- assistant ---
from project.api import views_assistant as vas  # noqa: E402

urlpatterns += [
    path("assistant/welcome/", vas.AssistantWelcomeAPI.as_view(), name="api-assistant-welcome"),
    path("assistant/send/", vas.AssistantSendAPI.as_view(), name="api-assistant-send"),
    path("assistant/sessions/<int:session_id>/messages/", vas.AssistantHistoryAPI.as_view(), name="api-assistant-history"),
    path("assistant/sessions/<int:session_id>/close/", vas.AssistantCloseAPI.as_view(), name="api-assistant-close"),
]
# --- fin assistant ---
