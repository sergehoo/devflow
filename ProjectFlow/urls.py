from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

import project
from project import routing
from project.channel_chat_views import channel_send_message, channel_panel_detail, channel_panel_data
from project.views import HomeView, DashboardView, WorkspaceListView, WorkspaceCreateView, WorkspaceDetailView, \
    WorkspaceUpdateView, KeyResultDetailView, KeyResultDeleteView, KeyResultUpdateView, KeyResultCreateView, \
    KeyResultListView, ObjectiveArchiveView, ObjectiveDeleteView, ObjectiveUpdateView, ObjectiveDetailView, \
    ObjectiveCreateView, ObjectiveListView, WorkspaceSettingsDeleteView, WorkspaceSettingsUpdateView, \
    WorkspaceSettingsDetailView, WorkspaceSettingsCreateView, WorkspaceSettingsListView, APIKeyDeleteView, \
    APIKeyUpdateView, APIKeyDetailView, APIKeyCreateView, APIKeyListView, SprintRetrospectiveDeleteView, \
    SprintRetrospectiveUpdateView, SprintRetrospectiveDetailView, SprintRetrospectiveCreateView, \
    SprintRetrospectiveListView, SprintReviewDeleteView, SprintReviewUpdateView, SprintReviewDetailView, \
    SprintReviewCreateView, SprintReviewListView, MessageAttachmentDeleteView, MessageAttachmentUpdateView, \
    MessageAttachmentDetailView, MessageAttachmentCreateView, MessageAttachmentListView, ReactionDeleteView, \
    ReactionUpdateView, ReactionDetailView, ReactionCreateView, ReactionListView, WebhookDeleteView, WebhookUpdateView, \
    WebhookDetailView, WebhookCreateView, WebhookListView, IntegrationDeleteView, IntegrationUpdateView, \
    IntegrationDetailView, IntegrationCreateView, IntegrationListView, WorkspaceInvitationAcceptView, \
    WorkspaceInvitationDeleteView, WorkspaceInvitationUpdateView, WorkspaceInvitationDetailView, \
    WorkspaceInvitationCreateView, WorkspaceInvitationListView, BoardColumnDeleteView, BoardColumnUpdateView, \
    BoardColumnDetailView, BoardColumnCreateView, BoardColumnListView, RoadmapItemDeleteView, RoadmapItemUpdateView, \
    RoadmapItemDetailView, RoadmapItemCreateView, RoadmapItemListView, RoadmapArchiveView, RoadmapDeleteView, \
    RoadmapUpdateView, RoadmapDetailView, RoadmapCreateView, RoadmapListView, ReleaseArchiveView, ReleaseDeleteView, \
    ReleaseUpdateView, ReleaseDetailView, ReleaseCreateView, ReleaseListView, MilestoneTaskDeleteView, \
    MilestoneTaskUpdateView, MilestoneTaskDetailView, MilestoneTaskCreateView, MilestoneTaskListView, \
    MilestoneArchiveView, MilestoneDeleteView, MilestoneUpdateView, MilestoneDetailView, MilestoneCreateView, \
    MilestoneListView, ChecklistItemDeleteView, ChecklistItemUpdateView, ChecklistItemDetailView, \
    ChecklistItemCreateView, ChecklistItemListView, TaskChecklistDeleteView, TaskChecklistUpdateView, \
    TaskChecklistDetailView, TaskChecklistCreateView, TaskChecklistListView, TaskDependencyDeleteView, \
    TaskDependencyUpdateView, TaskDependencyDetailView, TaskDependencyCreateView, TaskDependencyListView, \
    ProjectLabelDeleteView, ProjectLabelUpdateView, ProjectLabelDetailView, ProjectLabelCreateView, \
    ProjectLabelListView, TaskLabelDeleteView, TaskLabelUpdateView, TaskLabelDetailView, TaskLabelCreateView, \
    TaskLabelListView, LabelDeleteView, LabelUpdateView, LabelDetailView, LabelCreateView, LabelListView, \
    UserPreferenceDeleteView, UserPreferenceUpdateView, UserPreferenceDetailView, UserPreferenceCreateView, \
    UserPreferenceListView, DashboardSnapshotDeleteView, DashboardSnapshotUpdateView, DashboardSnapshotDetailView, \
    DashboardSnapshotCreateView, DashboardSnapshotListView, TimesheetEntryDeleteView, TimesheetEntryUpdateView, \
    TimesheetEntryDetailView, TimesheetEntryCreateView, TimesheetEntryListView, MessageDeleteView, MessageUpdateView, \
    MessageDetailView, MessageCreateView, MessageListView, ChannelMembershipDeleteView, ChannelMembershipUpdateView, \
    ChannelMembershipDetailView, ChannelMembershipCreateView, ChannelMembershipListView, DirectChannelDeleteView, \
    DirectChannelUpdateView, DirectChannelDetailView, DirectChannelCreateView, DirectChannelListView, \
    ActivityLogDeleteView, ActivityLogUpdateView, ActivityLogDetailView, ActivityLogCreateView, ActivityLogListView, \
    NotificationMarkAllReadView, NotificationMarkReadView, NotificationDeleteView, NotificationUpdateView, \
    NotificationDetailView, NotificationCreateView, NotificationListView, AInsightDismissView, AInsightDeleteView, \
    AInsightUpdateView, AInsightDetailView, AInsightCreateView, AInsightListView, RiskArchiveView, RiskDeleteView, \
    RiskUpdateView, RiskDetailView, RiskCreateView, RiskListView, PullRequestDeleteView, PullRequestUpdateView, \
    PullRequestDetailView, PullRequestCreateView, PullRequestListView, TaskAttachmentDeleteView, \
    TaskAttachmentUpdateView, TaskAttachmentDetailView, TaskAttachmentCreateView, TaskAttachmentListView, \
    TaskCommentDeleteView, TaskCommentUpdateView, TaskCommentDetailView, TaskCommentCreateView, TaskCommentListView, \
    TaskAssignmentDeleteView, TaskAssignmentUpdateView, TaskAssignmentDetailView, TaskAssignmentCreateView, \
    TaskAssignmentListView, TaskMarkDoneView, TaskMoveView, TaskArchiveView, TaskDeleteView, TaskUpdateView, \
    TaskDetailView, TaskCreateView, TaskListView, BacklogItemArchiveView, BacklogItemDeleteView, BacklogItemUpdateView, \
    BacklogItemDetailView, BacklogItemCreateView, BacklogItemListView, SprintMetricDeleteView, SprintMetricUpdateView, \
    SprintMetricDetailView, SprintMetricCreateView, SprintMetricListView, SprintArchiveView, SprintDeleteView, \
    SprintUpdateView, SprintDetailView, SprintCreateView, SprintListView, ProjectMemberDeleteView, \
    ProjectMemberUpdateView, ProjectMemberDetailView, ProjectMemberCreateView, ProjectMemberListView, \
    ProjectArchiveView, ProjectDeleteView, ProjectUpdateView, ProjectDetailView, ProjectCreateView, ProjectListView, \
    TeamMembershipDeleteView, TeamMembershipUpdateView, TeamMembershipDetailView, TeamMembershipCreateView, \
    TeamMembershipListView, TeamArchiveView, TeamDeleteView, TeamUpdateView, TeamDetailView, TeamCreateView, \
    TeamListView, WorkspaceArchiveView, WorkspaceDeleteView, ProjectBudgetExportExcelView, sprint_status_update, \
    task_status_update, roadmap_item_shift_dates, AInsightDashboardView, TaskToggleFlagView, TaskQuickCommentView, \
    TaskQuickStatusView, TaskQuickAssignView, ProfileDetailView, ProfileUpdateView, ProfilePasswordChangeView, \
    TaskQuickAttachmentView, TaskKanbanMoveView, ProjectDocumentImportListView, ProjectDocumentImportCreateView, \
    ProjectDocumentImportDetailView
from project.views_budget import ProjectBudgetCreateView, ProjectBudgetDetailView, ProjectEstimateLineCreateView, \
    ProjectRevenueCreateView, GenerateEstimateLinesFromTasksView, ProjectExpenseCreateView, ProjectBudgetUpdateView, \
    RecalculateProjectBudgetView, ProjectExpenseRejectView, ProjectExpenseApproveLevel2View, \
    ProjectExpenseApproveLevel1View, ProjectExpenseUpdateView, ProjectExpenseDetailView, ProjectExpenseListView

app_name = "project"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    # path("", HomeView.as_view(), name="home"),
    path("", DashboardView.as_view(), name="dashboard"),

    path("profile/", ProfileDetailView.as_view(), name="profile_detail"),
    path("profile/update/", ProfileUpdateView.as_view(), name="profile_update"),
    path("profile/password/", ProfilePasswordChangeView.as_view(), name="profile_password_change"),

    path("workspaces/", WorkspaceListView.as_view(), name="workspace_list"),
    path("workspaces/create/", WorkspaceCreateView.as_view(), name="workspace_create"),
    path("workspaces/<int:pk>/", WorkspaceDetailView.as_view(), name="workspace_detail"),
    path("workspaces/<int:pk>/update/", WorkspaceUpdateView.as_view(), name="workspace_update"),
    path("workspaces/<int:pk>/delete/", WorkspaceDeleteView.as_view(), name="workspace_delete"),
    path("workspaces/<int:pk>/archive/", WorkspaceArchiveView.as_view(), name="workspace_archive"),

    path("teams/", TeamListView.as_view(), name="team_list"),
    path("teams/create/", TeamCreateView.as_view(), name="team_create"),
    path("teams/<int:pk>/", TeamDetailView.as_view(), name="team_detail"),
    path("teams/<int:pk>/update/", TeamUpdateView.as_view(), name="team_update"),
    path("teams/<int:pk>/delete/", TeamDeleteView.as_view(), name="team_delete"),
    path("teams/<int:pk>/archive/", TeamArchiveView.as_view(), name="team_archive"),

    path("team-memberships/", TeamMembershipListView.as_view(), name="team_membership_list"),
    path("team-memberships/create/", TeamMembershipCreateView.as_view(), name="team_membership_create"),
    path("team-memberships/<int:pk>/", TeamMembershipDetailView.as_view(), name="team_membership_detail"),
    path("team-memberships/<int:pk>/update/", TeamMembershipUpdateView.as_view(), name="team_membership_update"),
    path("team-memberships/<int:pk>/delete/", TeamMembershipDeleteView.as_view(), name="team_membership_delete"),

    path("projects/", ProjectListView.as_view(), name="project_list"),
    path("projects/<int:pk>/budget/export-excel/", ProjectBudgetExportExcelView.as_view(),
         name="project_budget_export_excel", ),
    path("projects/create/", ProjectCreateView.as_view(), name="project_create"),
    path("projects/<int:pk>/", ProjectDetailView.as_view(), name="project_detail"),
    path("projects/<int:pk>/update/", ProjectUpdateView.as_view(), name="project_update"),
    path("projects/<int:pk>/delete/", ProjectDeleteView.as_view(), name="project_delete"),
    path("projects/<int:pk>/archive/", ProjectArchiveView.as_view(), name="project_archive"),

    path("project-budgets/create/", ProjectBudgetCreateView.as_view(), name="project_budget_create"),
    path("project-budgets/<int:pk>/update/", ProjectBudgetUpdateView.as_view(), name="project_budget_update"),
    path("project-budgets/<int:pk>/", ProjectBudgetDetailView.as_view(), name="project_budget_detail"),

    path("project-estimate-lines/create/", ProjectEstimateLineCreateView.as_view(),
         name="project_estimate_line_create"),
    path("project-revenues/create/", ProjectRevenueCreateView.as_view(), name="project_revenue_create"),
    path("project-expenses/create/", ProjectExpenseCreateView.as_view(), name="project_expense_create"),
    path("project-expenses/", ProjectExpenseListView.as_view(), name="project_expense_list"),
    path("project-expenses/<int:pk>/", ProjectExpenseDetailView.as_view(), name="project_expense_detail"),
    path("project-expenses/<int:pk>/update/", ProjectExpenseUpdateView.as_view(), name="project_expense_update"),

    path("project-expenses/<int:pk>/approve-level1/", ProjectExpenseApproveLevel1View.as_view(),
         name="project_expense_approve_level1"),
    path("project-expenses/<int:pk>/approve-level2/", ProjectExpenseApproveLevel2View.as_view(),
         name="project_expense_approve_level2"),
    path("project-expenses/<int:pk>/reject/", ProjectExpenseRejectView.as_view(), name="project_expense_reject"),

    path("projects/<int:project_id>/generate-estimates/", GenerateEstimateLinesFromTasksView.as_view(),
         name="project_generate_estimates"),
    path("projects/<int:project_id>/recalculate-budget/", RecalculateProjectBudgetView.as_view(),
         name="project_recalculate_budget"),
    path("project-members/", ProjectMemberListView.as_view(), name="project_member_list"),
    path("project-members/create/", ProjectMemberCreateView.as_view(), name="project_member_create"),
    path("project-members/<int:pk>/", ProjectMemberDetailView.as_view(), name="project_member_detail"),
    path("project-members/<int:pk>/update/", ProjectMemberUpdateView.as_view(), name="project_member_update"),
    path("project-members/<int:pk>/delete/", ProjectMemberDeleteView.as_view(), name="project_member_delete"),
    path("sprints/status/update/", sprint_status_update, name="sprint_status_update"),
    path("tasks/status/update/", task_status_update, name="task_status_update"),

    path("sprints/", SprintListView.as_view(), name="sprint_list"),
    path("sprints/create/", SprintCreateView.as_view(), name="sprint_create"),
    path("sprints/<int:pk>/", SprintDetailView.as_view(), name="sprint_detail"),
    path("sprints/<int:pk>/update/", SprintUpdateView.as_view(), name="sprint_update"),
    path("sprints/<int:pk>/delete/", SprintDeleteView.as_view(), name="sprint_delete"),
    path("sprints/<int:pk>/archive/", SprintArchiveView.as_view(), name="sprint_archive"),

    path("sprint-metrics/", SprintMetricListView.as_view(), name="sprint_metric_list"),
    path("sprint-metrics/create/", SprintMetricCreateView.as_view(), name="sprint_metric_create"),
    path("sprint-metrics/<int:pk>/", SprintMetricDetailView.as_view(), name="sprint_metric_detail"),
    path("sprint-metrics/<int:pk>/update/", SprintMetricUpdateView.as_view(), name="sprint_metric_update"),
    path("sprint-metrics/<int:pk>/delete/", SprintMetricDeleteView.as_view(), name="sprint_metric_delete"),

    path("backlog-items/", BacklogItemListView.as_view(), name="backlog_item_list"),
    path("backlog-items/create/", BacklogItemCreateView.as_view(), name="backlog_item_create"),
    path("backlog-items/<int:pk>/", BacklogItemDetailView.as_view(), name="backlog_item_detail"),
    path("backlog-items/<int:pk>/update/", BacklogItemUpdateView.as_view(), name="backlog_item_update"),
    path("backlog-items/<int:pk>/delete/", BacklogItemDeleteView.as_view(), name="backlog_item_delete"),
    path("backlog-items/<int:pk>/archive/", BacklogItemArchiveView.as_view(), name="backlog_item_archive"),
    path("tasks/<int:pk>/quick-status/", TaskQuickStatusView.as_view(), name="task_quick_status"),
    path("tasks/<int:pk>/toggle-flag/", TaskToggleFlagView.as_view(), name="task_toggle_flag"),

    path("tasks/<int:pk>/quick-assign/", TaskQuickAssignView.as_view(), name="task_quick_assign"),
    path("tasks/<int:pk>/quick-comment/", TaskQuickCommentView.as_view(), name="task_quick_comment"),
    path("tasks/<int:pk>/quick-attachment/", TaskQuickAttachmentView.as_view(), name="task_quick_attachment"),
    path("tasks/<int:pk>/move/", TaskKanbanMoveView.as_view(), name="task_kanban_move"),
    path("tasks/", TaskListView.as_view(), name="task_list"),
    path("tasks/create/", TaskCreateView.as_view(), name="task_create"),
    path("tasks/<int:pk>/", TaskDetailView.as_view(), name="task_detail"),
    path("tasks/<int:pk>/update/", TaskUpdateView.as_view(), name="task_update"),
    path("tasks/<int:pk>/delete/", TaskDeleteView.as_view(), name="task_delete"),
    path("tasks/<int:pk>/archive/", TaskArchiveView.as_view(), name="task_archive"),
    path("tasks/<int:pk>/move/", TaskMoveView.as_view(), name="task_move"),
    path("tasks/<int:pk>/mark-done/", TaskMarkDoneView.as_view(), name="task_mark_done"),

    path("task-assignments/", TaskAssignmentListView.as_view(), name="task_assignment_list"),
    path("task-assignments/create/", TaskAssignmentCreateView.as_view(), name="task_assignment_create"),
    path("task-assignments/<int:pk>/", TaskAssignmentDetailView.as_view(), name="task_assignment_detail"),
    path("task-assignments/<int:pk>/update/", TaskAssignmentUpdateView.as_view(), name="task_assignment_update"),
    path("task-assignments/<int:pk>/delete/", TaskAssignmentDeleteView.as_view(), name="task_assignment_delete"),

    path("task-comments/", TaskCommentListView.as_view(), name="task_comment_list"),
    path("task-comments/create/", TaskCommentCreateView.as_view(), name="task_comment_create"),
    path("task-comments/<int:pk>/", TaskCommentDetailView.as_view(), name="task_comment_detail"),
    path("task-comments/<int:pk>/update/", TaskCommentUpdateView.as_view(), name="task_comment_update"),
    path("task-comments/<int:pk>/delete/", TaskCommentDeleteView.as_view(), name="task_comment_delete"),

    path("task-attachments/", TaskAttachmentListView.as_view(), name="task_attachment_list"),
    path("task-attachments/create/", TaskAttachmentCreateView.as_view(), name="task_attachment_create"),
    path("task-attachments/<int:pk>/", TaskAttachmentDetailView.as_view(), name="task_attachment_detail"),
    path("task-attachments/<int:pk>/update/", TaskAttachmentUpdateView.as_view(), name="task_attachment_update"),
    path("task-attachments/<int:pk>/delete/", TaskAttachmentDeleteView.as_view(), name="task_attachment_delete"),

    path("pull-requests/", PullRequestListView.as_view(), name="pull_request_list"),
    path("pull-requests/create/", PullRequestCreateView.as_view(), name="pull_request_create"),
    path("pull-requests/<int:pk>/", PullRequestDetailView.as_view(), name="pull_request_detail"),
    path("pull-requests/<int:pk>/update/", PullRequestUpdateView.as_view(), name="pull_request_update"),
    path("pull-requests/<int:pk>/delete/", PullRequestDeleteView.as_view(), name="pull_request_delete"),

    path("risks/", RiskListView.as_view(), name="risk_list"),
    path("risks/create/", RiskCreateView.as_view(), name="risk_create"),
    path("risks/<int:pk>/", RiskDetailView.as_view(), name="risk_detail"),
    path("risks/<int:pk>/update/", RiskUpdateView.as_view(), name="risk_update"),
    path("risks/<int:pk>/delete/", RiskDeleteView.as_view(), name="risk_delete"),
    path("risks/<int:pk>/archive/", RiskArchiveView.as_view(), name="risk_archive"),

    path("ai-insights/dashboard/", AInsightDashboardView.as_view(), name="ai_insight_dashboard"),
    path("ai-insights/", AInsightListView.as_view(), name="ai_insight_list"),
    path("ai-insights/create/", AInsightCreateView.as_view(), name="ai_insight_create"),
    path("ai-insights/<int:pk>/", AInsightDetailView.as_view(), name="ai_insight_detail"),
    path("ai-insights/<int:pk>/update/", AInsightUpdateView.as_view(), name="ai_insight_update"),
    path("ai-insights/<int:pk>/delete/", AInsightDeleteView.as_view(), name="ai_insight_delete"),
    path("ai-insights/<int:pk>/dismiss/", AInsightDismissView.as_view(), name="ai_insight_dismiss"),

    path("notifications/", NotificationListView.as_view(), name="notification_list"),
    path("notifications/create/", NotificationCreateView.as_view(), name="notification_create"),
    path("notifications/<int:pk>/", NotificationDetailView.as_view(), name="notification_detail"),
    path("notifications/<int:pk>/update/", NotificationUpdateView.as_view(), name="notification_update"),
    path("notifications/<int:pk>/delete/", NotificationDeleteView.as_view(), name="notification_delete"),
    path("notifications/<int:pk>/mark-read/", NotificationMarkReadView.as_view(), name="notification_mark_read"),
    path("notifications/mark-all-read/", NotificationMarkAllReadView.as_view(), name="notification_mark_all_read"),

    path("activity-logs/", ActivityLogListView.as_view(), name="activity_log_list"),
    path("activity-logs/create/", ActivityLogCreateView.as_view(), name="activity_log_create"),
    path("activity-logs/<int:pk>/", ActivityLogDetailView.as_view(), name="activity_log_detail"),
    path("activity-logs/<int:pk>/update/", ActivityLogUpdateView.as_view(), name="activity_log_update"),
    path("activity-logs/<int:pk>/delete/", ActivityLogDeleteView.as_view(), name="activity_log_delete"),


    path("channels/panel/", channel_panel_data, name="channel_panel_data"),
    path("channels/<int:pk>/panel/", channel_panel_detail, name="channel_panel_detail"),
    path("channels/<int:pk>/messages/send/", channel_send_message, name="channel_send_message"),
    path("channels/", DirectChannelListView.as_view(), name="direct_channel_list"),
    path("channels/create/", DirectChannelCreateView.as_view(), name="direct_channel_create"),
    path("channels/<int:pk>/", DirectChannelDetailView.as_view(), name="direct_channel_detail"),
    path("channels/<int:pk>/update/", DirectChannelUpdateView.as_view(), name="direct_channel_update"),
    path("channels/<int:pk>/delete/", DirectChannelDeleteView.as_view(), name="direct_channel_delete"),

    path("channel-memberships/", ChannelMembershipListView.as_view(), name="channel_membership_list"),
    path("channel-memberships/create/", ChannelMembershipCreateView.as_view(), name="channel_membership_create"),
    path("channel-memberships/<int:pk>/", ChannelMembershipDetailView.as_view(), name="channel_membership_detail"),
    path("channel-memberships/<int:pk>/update/", ChannelMembershipUpdateView.as_view(),
         name="channel_membership_update"),
    path("channel-memberships/<int:pk>/delete/", ChannelMembershipDeleteView.as_view(),
         name="channel_membership_delete"),

    path("messages/", MessageListView.as_view(), name="message_list"),
    path("messages/create/", MessageCreateView.as_view(), name="message_create"),
    path("messages/<int:pk>/", MessageDetailView.as_view(), name="message_detail"),
    path("messages/<int:pk>/update/", MessageUpdateView.as_view(), name="message_update"),
    path("messages/<int:pk>/delete/", MessageDeleteView.as_view(), name="message_delete"),

    path("timesheets/", TimesheetEntryListView.as_view(), name="timesheet_entry_list"),
    path("timesheets/create/", TimesheetEntryCreateView.as_view(), name="timesheet_entry_create"),
    path("timesheets/<int:pk>/", TimesheetEntryDetailView.as_view(), name="timesheet_entry_detail"),
    path("timesheets/<int:pk>/update/", TimesheetEntryUpdateView.as_view(), name="timesheet_entry_update"),
    path("timesheets/<int:pk>/delete/", TimesheetEntryDeleteView.as_view(), name="timesheet_entry_delete"),

    path("dashboard-snapshots/", DashboardSnapshotListView.as_view(), name="dashboard_snapshot_list"),
    path("dashboard-snapshots/create/", DashboardSnapshotCreateView.as_view(), name="dashboard_snapshot_create"),
    path("dashboard-snapshots/<int:pk>/", DashboardSnapshotDetailView.as_view(), name="dashboard_snapshot_detail"),
    path("dashboard-snapshots/<int:pk>/update/", DashboardSnapshotUpdateView.as_view(),
         name="dashboard_snapshot_update"),
    path("dashboard-snapshots/<int:pk>/delete/", DashboardSnapshotDeleteView.as_view(),
         name="dashboard_snapshot_delete"),

    path("user-preferences/", UserPreferenceListView.as_view(), name="user_preference_list"),
    path("user-preferences/create/", UserPreferenceCreateView.as_view(), name="user_preference_create"),
    path("user-preferences/<int:pk>/", UserPreferenceDetailView.as_view(), name="user_preference_detail"),
    path("user-preferences/<int:pk>/update/", UserPreferenceUpdateView.as_view(), name="user_preference_update"),
    path("user-preferences/<int:pk>/delete/", UserPreferenceDeleteView.as_view(), name="user_preference_delete"),

    path("labels/", LabelListView.as_view(), name="label_list"),
    path("labels/create/", LabelCreateView.as_view(), name="label_create"),
    path("labels/<int:pk>/", LabelDetailView.as_view(), name="label_detail"),
    path("labels/<int:pk>/update/", LabelUpdateView.as_view(), name="label_update"),
    path("labels/<int:pk>/delete/", LabelDeleteView.as_view(), name="label_delete"),

    path("task-labels/", TaskLabelListView.as_view(), name="task_label_list"),
    path("task-labels/create/", TaskLabelCreateView.as_view(), name="task_label_create"),
    path("task-labels/<int:pk>/", TaskLabelDetailView.as_view(), name="task_label_detail"),
    path("task-labels/<int:pk>/update/", TaskLabelUpdateView.as_view(), name="task_label_update"),
    path("task-labels/<int:pk>/delete/", TaskLabelDeleteView.as_view(), name="task_label_delete"),

    path("project-labels/", ProjectLabelListView.as_view(), name="project_label_list"),
    path("project-labels/create/", ProjectLabelCreateView.as_view(), name="project_label_create"),
    path("project-labels/<int:pk>/", ProjectLabelDetailView.as_view(), name="project_label_detail"),
    path("project-labels/<int:pk>/update/", ProjectLabelUpdateView.as_view(), name="project_label_update"),
    path("project-labels/<int:pk>/delete/", ProjectLabelDeleteView.as_view(), name="project_label_delete"),
    path("project-imports/", ProjectDocumentImportListView.as_view(), name="project_document_import_list"),

    path("project-imports/create/", ProjectDocumentImportCreateView.as_view(), name="project_document_import_create"),

    path("project-imports/<int:pk>/", ProjectDocumentImportDetailView.as_view(), name="project_document_import_detail"),
    path("task-dependencies/", TaskDependencyListView.as_view(), name="task_dependency_list"),
    path("task-dependencies/create/", TaskDependencyCreateView.as_view(), name="task_dependency_create"),
    path("task-dependencies/<int:pk>/", TaskDependencyDetailView.as_view(), name="task_dependency_detail"),
    path("task-dependencies/<int:pk>/update/", TaskDependencyUpdateView.as_view(), name="task_dependency_update"),
    path("task-dependencies/<int:pk>/delete/", TaskDependencyDeleteView.as_view(), name="task_dependency_delete"),

    path("task-checklists/", TaskChecklistListView.as_view(), name="task_checklist_list"),
    path("task-checklists/create/", TaskChecklistCreateView.as_view(), name="task_checklist_create"),
    path("task-checklists/<int:pk>/", TaskChecklistDetailView.as_view(), name="task_checklist_detail"),
    path("task-checklists/<int:pk>/update/", TaskChecklistUpdateView.as_view(), name="task_checklist_update"),
    path("task-checklists/<int:pk>/delete/", TaskChecklistDeleteView.as_view(), name="task_checklist_delete"),

    path("checklist-items/", ChecklistItemListView.as_view(), name="checklist_item_list"),
    path("checklist-items/create/", ChecklistItemCreateView.as_view(), name="checklist_item_create"),
    path("checklist-items/<int:pk>/", ChecklistItemDetailView.as_view(), name="checklist_item_detail"),
    path("checklist-items/<int:pk>/update/", ChecklistItemUpdateView.as_view(), name="checklist_item_update"),
    path("checklist-items/<int:pk>/delete/", ChecklistItemDeleteView.as_view(), name="checklist_item_delete"),

    path("milestones/", MilestoneListView.as_view(), name="milestone_list"),
    path("milestones/create/", MilestoneCreateView.as_view(), name="milestone_create"),
    path("milestones/<int:pk>/", MilestoneDetailView.as_view(), name="milestone_detail"),
    path("milestones/<int:pk>/update/", MilestoneUpdateView.as_view(), name="milestone_update"),
    path("milestones/<int:pk>/delete/", MilestoneDeleteView.as_view(), name="milestone_delete"),
    path("milestones/<int:pk>/archive/", MilestoneArchiveView.as_view(), name="milestone_archive"),

    path("milestone-tasks/", MilestoneTaskListView.as_view(), name="milestone_task_list"),
    path("milestone-tasks/create/", MilestoneTaskCreateView.as_view(), name="milestone_task_create"),
    path("milestone-tasks/<int:pk>/", MilestoneTaskDetailView.as_view(), name="milestone_task_detail"),
    path("milestone-tasks/update/<int:pk>", MilestoneTaskUpdateView.as_view(), name="milestone_task_update"),
    path("milestone-tasks/<int:pk>/delete/", MilestoneTaskDeleteView.as_view(), name="milestone_task_delete"),

    path("releases/", ReleaseListView.as_view(), name="release_list"),
    path("releases/create/", ReleaseCreateView.as_view(), name="release_create"),
    path("releases/<int:pk>/", ReleaseDetailView.as_view(), name="release_detail"),
    path("releases/<int:pk>/update/", ReleaseUpdateView.as_view(), name="release_update"),
    path("releases/<int:pk>/delete/", ReleaseDeleteView.as_view(), name="release_delete"),
    path("releases/<int:pk>/archive/", ReleaseArchiveView.as_view(), name="release_archive"),

    path(
        "roadmap-items/shift-dates/",
        roadmap_item_shift_dates,
        name="roadmap_item_shift_dates",
    ),
    path("roadmaps/", RoadmapListView.as_view(), name="roadmap_list"),
    path("roadmaps/create/", RoadmapCreateView.as_view(), name="roadmap_create"),
    path("roadmaps/<int:pk>/", RoadmapDetailView.as_view(), name="roadmap_detail"),
    path("roadmaps/<int:pk>/update/", RoadmapUpdateView.as_view(), name="roadmap_update"),
    path("roadmaps/<int:pk>/delete/", RoadmapDeleteView.as_view(), name="roadmap_delete"),
    path("roadmaps/<int:pk>/archive/", RoadmapArchiveView.as_view(), name="roadmap_archive"),

    path("roadmap-items/", RoadmapItemListView.as_view(), name="roadmap_item_list"),
    path("roadmap-items/create/", RoadmapItemCreateView.as_view(), name="roadmap_item_create"),
    path("roadmap-items/<int:pk>/", RoadmapItemDetailView.as_view(), name="roadmap_item_detail"),
    path("roadmap-items/<int:pk>/update/", RoadmapItemUpdateView.as_view(), name="roadmap_item_update"),
    path("roadmap-items/<int:pk>/delete/", RoadmapItemDeleteView.as_view(), name="roadmap_item_delete"),

    path("board-columns/", BoardColumnListView.as_view(), name="board_column_list"),
    path("board-columns/create/", BoardColumnCreateView.as_view(), name="board_column_create"),
    path("board-columns/<int:pk>/", BoardColumnDetailView.as_view(), name="board_column_detail"),
    path("board-columns/<int:pk>/update/", BoardColumnUpdateView.as_view(), name="board_column_update"),
    path("board-columns/<int:pk>/delete/", BoardColumnDeleteView.as_view(), name="board_column_delete"),

    path("workspace-invitations/", WorkspaceInvitationListView.as_view(), name="workspace_invitation_list"),
    path("workspace-invitations/create/", WorkspaceInvitationCreateView.as_view(), name="workspace_invitation_create"),
    path("workspace-invitations/<int:pk>/", WorkspaceInvitationDetailView.as_view(),
         name="workspace_invitation_detail"),
    path("workspace-invitations/<int:pk>/update/", WorkspaceInvitationUpdateView.as_view(),
         name="workspace_invitation_update"),
    path("workspace-invitations/<int:pk>/delete/", WorkspaceInvitationDeleteView.as_view(),
         name="workspace_invitation_delete"),
    path("workspace-invitations/<int:pk>/accept/", WorkspaceInvitationAcceptView.as_view(),
         name="workspace_invitation_accept"),

    path("integrations/", IntegrationListView.as_view(), name="integration_list"),
    path("integrations/create/", IntegrationCreateView.as_view(), name="integration_create"),
    path("integrations/<int:pk>/", IntegrationDetailView.as_view(), name="integration_detail"),
    path("integrations/<int:pk>/update/", IntegrationUpdateView.as_view(), name="integration_update"),
    path("integrations/<int:pk>/delete/", IntegrationDeleteView.as_view(), name="integration_delete"),

    path("webhooks/", WebhookListView.as_view(), name="webhook_list"),
    path("webhooks/create/", WebhookCreateView.as_view(), name="webhook_create"),
    path("webhooks/<int:pk>/", WebhookDetailView.as_view(), name="webhook_detail"),
    path("webhooks/<int:pk>/update/", WebhookUpdateView.as_view(), name="webhook_update"),
    path("webhooks/<int:pk>/delete/", WebhookDeleteView.as_view(), name="webhook_delete"),

    path("reactions/", ReactionListView.as_view(), name="reaction_list"),
    path("reactions/create/", ReactionCreateView.as_view(), name="reaction_create"),
    path("reactions/<int:pk>/", ReactionDetailView.as_view(), name="reaction_detail"),
    path("reactions/<int:pk>/update/", ReactionUpdateView.as_view(), name="reaction_update"),
    path("reactions/<int:pk>/delete/", ReactionDeleteView.as_view(), name="reaction_delete"),

    path("message-attachments/", MessageAttachmentListView.as_view(), name="message_attachment_list"),
    path("message-attachments/create/", MessageAttachmentCreateView.as_view(), name="message_attachment_create"),
    path("message-attachments/<int:pk>/", MessageAttachmentDetailView.as_view(), name="message_attachment_detail"),
    path("message-attachments/<int:pk>/update/", MessageAttachmentUpdateView.as_view(),
         name="message_attachment_update"),
    path("message-attachments/<int:pk>/delete/", MessageAttachmentDeleteView.as_view(),
         name="message_attachment_delete"),

    path("sprint-reviews/", SprintReviewListView.as_view(), name="sprint_review_list"),
    path("sprint-reviews/create/", SprintReviewCreateView.as_view(), name="sprint_review_create"),
    path("sprint-reviews/<int:pk>/", SprintReviewDetailView.as_view(), name="sprint_review_detail"),
    path("sprint-reviews/<int:pk>/update/", SprintReviewUpdateView.as_view(), name="sprint_review_update"),
    path("sprint-reviews/<int:pk>/delete/", SprintReviewDeleteView.as_view(), name="sprint_review_delete"),

    path("sprint-retrospectives/", SprintRetrospectiveListView.as_view(), name="sprint_retrospective_list"),
    path("sprint-retrospectives/create/", SprintRetrospectiveCreateView.as_view(), name="sprint_retrospective_create"),
    path("sprint-retrospectives/<int:pk>/", SprintRetrospectiveDetailView.as_view(),
         name="sprint_retrospective_detail"),
    path("sprint-retrospectives/<int:pk>/update/", SprintRetrospectiveUpdateView.as_view(),
         name="sprint_retrospective_update"),
    path("sprint-retrospectives/<int:pk>/delete/", SprintRetrospectiveDeleteView.as_view(),
         name="sprint_retrospective_delete"),

    path("api-keys/", APIKeyListView.as_view(), name="api_key_list"),
    path("api-keys/create/", APIKeyCreateView.as_view(), name="api_key_create"),
    path("api-keys/<int:pk>/", APIKeyDetailView.as_view(), name="api_key_detail"),
    path("api-keys/<int:pk>/update/", APIKeyUpdateView.as_view(), name="api_key_update"),
    path("api-keys/<int:pk>/delete/", APIKeyDeleteView.as_view(), name="api_key_delete"),

    path("workspace-settings/", WorkspaceSettingsListView.as_view(), name="workspace_settings_list"),
    path("workspace-settings/create/", WorkspaceSettingsCreateView.as_view(), name="workspace_settings_create"),
    path("workspace-settings/<int:pk>/", WorkspaceSettingsDetailView.as_view(), name="workspace_settings_detail"),
    path("workspace-settings/<int:pk>/update/", WorkspaceSettingsUpdateView.as_view(),
         name="workspace_settings_update"),
    path("workspace-settings/<int:pk>/delete/", WorkspaceSettingsDeleteView.as_view(),
         name="workspace_settings_delete"),

    path("objectives/", ObjectiveListView.as_view(), name="objective_list"),
    path("objectives/create/", ObjectiveCreateView.as_view(), name="objective_create"),
    path("objectives/<int:pk>/", ObjectiveDetailView.as_view(), name="objective_detail"),
    path("objectives/<int:pk>/update/", ObjectiveUpdateView.as_view(), name="objective_update"),
    path("objectives/<int:pk>/delete/", ObjectiveDeleteView.as_view(), name="objective_delete"),
    path("objectives/<int:pk>/archive/", ObjectiveArchiveView.as_view(), name="objective_archive"),

    path("key-results/", KeyResultListView.as_view(), name="key_result_list"),
    path("key-results/create/", KeyResultCreateView.as_view(), name="key_result_create"),
    path("key-results/<int:pk>/", KeyResultDetailView.as_view(), name="key_result_detail"),
    path("key-results/<int:pk>/update/", KeyResultUpdateView.as_view(), name="key_result_update"),
    path("key-results/<int:pk>/delete/", KeyResultDeleteView.as_view(), name="key_result_delete"),
]
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
