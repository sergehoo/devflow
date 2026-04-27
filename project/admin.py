from project import models as dm
from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import (
    Workspace,
    Team,
    TeamMembership,
    Project,
    ProjectMember,
    CostCategory,
    BillingRate,
    ProjectBudget,
    ProjectEstimateLine,
    ProjectRevenue,
    ProjectExpense,
    TimesheetCostSnapshot,
    Sprint,
    SprintMetric,
    SprintReview,
    SprintRetrospective,
    BacklogItem,
    Task,
    TaskAssignment,
    TaskComment,
    TaskAttachment,
    PullRequest,
    Risk,
    AInsight,
    Notification,
    ActivityLog,
    DirectChannel,
    ChannelMembership,
    Message,
    TimesheetEntry,
    DashboardSnapshot,
    UserPreference,
    Label,
    TaskLabel,
    ProjectLabel,
    TaskDependency,
    TaskChecklist,
    ChecklistItem,
    Milestone,
    MilestoneTask,
    Release,
    Roadmap,
    RoadmapItem,
    BoardColumn,
    WorkspaceInvitation,
    Integration,
    Webhook,
    Reaction,
    MessageAttachment,
    WorkspaceSettings,
    APIKey,
    Objective,
    KeyResult, UserProfile, ProjectCategory,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def colored_status(value, mapping):
    color = mapping.get(value, "#9CA3AF")
    return format_html(
        '<span style="background:{};color:#fff;padding:2px 8px;'
        'border-radius:999px;font-size:11px;font-weight:600;">{}</span>',
        color,
        value,
    )


STATUS_COLORS = {
    "PLANNED": "#6B7280",
    "IN_PROGRESS": "#F4722B",
    "DONE": "#34A853",
    "BLOCKED": "#E8453C",
    "DELAYED": "#E8950A",
    "CANCELLED": "#9CA3AF",
    "ON_HOLD": "#8B5CF6",
    "IN_DELIVERY": "#0EA5C9",
    "ACTIVE": "#34A853",
    "REVIEW": "#E8950A",
    "OPEN": "#E8453C",
    "MITIGATED": "#34A853",
    "ESCALATED": "#E8950A",
    "CLOSED": "#6B7280",
    "MERGED": "#34A853",
    "APPROVED": "#0EA5C9",
    "PENDING": "#F4722B",
    "ACCEPTED": "#34A853",
    "DECLINED": "#E8453C",
    "EXPIRED": "#9CA3AF",
    "REVOKED": "#6B7280",
    "DRAFT": "#6B7280",
    "SUBMITTED": "#0EA5C9",
    "REVISED": "#8B5CF6",
    "VALIDATED": "#34A853",
    "REJECTED": "#E8453C",
    "RELEASED": "#34A853",
    "AT_RISK": "#E8950A",
    "MISSED": "#E8453C",
    "ON_TRACK": "#34A853",
    "BEHIND": "#E8453C",
    "ERROR": "#E8453C",
    "INACTIVE": "#9CA3AF",
}

PRIORITY_COLORS = {
    "LOW": "#9CA3AF",
    "MEDIUM": "#F4722B",
    "HIGH": "#E8950A",
    "CRITICAL": "#E8453C",
}

SEVERITY_COLORS = {
    "INFO": "#6B7280",
    "LOW": "#9CA3AF",
    "MEDIUM": "#F4722B",
    "HIGH": "#E8950A",
    "CRITICAL": "#E8453C",
}

HEALTH_COLORS = {
    "GREEN": "#34A853",
    "AMBER": "#F4722B",
    "RED": "#E8453C",
    "GRAY": "#9CA3AF",
}


# ─────────────────────────────────────────────────────────────────────────────
# INLINES
# ─────────────────────────────────────────────────────────────────────────────

class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    fields = ("user", "role", "status", "job_title", "capacity_points", "current_load_percent")
    autocomplete_fields = ("user",)


class ProjectMemberInline(admin.TabularInline):
    model = ProjectMember
    extra = 0
    fields = ("user", "team", "role", "allocation_percent", "is_primary")
    autocomplete_fields = ("user", "team")


class SprintInline(admin.TabularInline):
    model = Sprint
    extra = 0
    fields = ("number", "name", "status", "start_date", "end_date", "velocity_target", "velocity_completed")
    ordering = ("-number",)
    show_change_link = True


class SprintMetricInline(admin.TabularInline):
    model = SprintMetric
    extra = 0
    fields = (
        "metric_date",
        "planned_remaining_points",
        "actual_remaining_points",
        "completed_tasks",
        "added_scope_points",
        "removed_scope_points",
    )
    ordering = ("metric_date",)


class TaskAssignmentInline(admin.TabularInline):
    model = TaskAssignment
    extra = 0
    fields = ("user", "assigned_by", "allocation_percent", "is_active")
    autocomplete_fields = ("user", "assigned_by")


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    fields = ("author", "body", "is_internal", "edited_at")
    readonly_fields = ("edited_at",)
    autocomplete_fields = ("author",)


class TaskAttachmentInline(admin.TabularInline):
    model = TaskAttachment
    extra = 0
    fields = ("file", "name", "mime_type", "size", "uploaded_by")
    readonly_fields = ("size",)
    autocomplete_fields = ("uploaded_by",)


class TaskLabelInline(admin.TabularInline):
    model = TaskLabel
    extra = 0
    fields = ("label", "added_by")
    autocomplete_fields = ("label", "added_by")


class TaskChecklistInline(admin.TabularInline):
    model = TaskChecklist
    extra = 0
    fields = ("title", "position")
    show_change_link = True


class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0
    fields = ("text", "is_checked", "checked_at", "checked_by", "position")
    readonly_fields = ("checked_at",)
    autocomplete_fields = ("checked_by",)


class TaskDependencyInline(admin.TabularInline):
    model = TaskDependency
    fk_name = "from_task"
    extra = 0
    fields = ("to_task", "dependency_type", "created_by")
    autocomplete_fields = ("to_task", "created_by")


class MilestoneTaskInline(admin.TabularInline):
    model = MilestoneTask
    extra = 0
    fields = ("task",)
    autocomplete_fields = ("task",)


class BoardColumnInline(admin.TabularInline):
    model = BoardColumn
    extra = 0
    fields = ("name", "mapped_status", "position", "wip_limit", "is_done_column", "color")
    ordering = ("position",)


class KeyResultInline(admin.TabularInline):
    model = KeyResult
    extra = 0
    fields = ("title", "result_type", "target_value", "current_value", "unit", "owner")
    autocomplete_fields = ("owner",)


class ChannelMembershipInline(admin.TabularInline):
    model = ChannelMembership
    extra = 0
    fields = ("user", "joined_at", "is_muted")
    readonly_fields = ("joined_at",)
    autocomplete_fields = ("user",)


class MessageAttachmentInline(admin.TabularInline):
    model = MessageAttachment
    extra = 0
    fields = ("file", "name", "mime_type", "size")
    readonly_fields = ("size",)


class ReactionInline(admin.TabularInline):
    model = Reaction
    fk_name = "task_comment"
    extra = 0
    fields = ("user", "emoji")
    autocomplete_fields = ("user",)


class RoadmapItemInline(admin.TabularInline):
    model = RoadmapItem
    extra = 0
    fields = ("title", "status", "start_date", "end_date", "project", "milestone", "row", "color")
    ordering = ("start_date", "row")
    autocomplete_fields = ("project", "milestone")


class ProjectLabelInline(admin.TabularInline):
    model = ProjectLabel
    extra = 0
    fields = ("label",)
    autocomplete_fields = ("label",)


class ProjectEstimateLineInline(admin.TabularInline):
    model = ProjectEstimateLine
    extra = 0
    fields = (
        "label",
        "category",
        "source_type",
        "task",
        "sprint",
        "milestone",
        "quantity",
        "cost_unit_amount",
        "cost_amount",
        "sale_unit_amount",
        "sale_amount",
        "markup_percent",
        "created_by",
    )
    readonly_fields = ("cost_amount", "sale_unit_amount", "sale_amount")
    autocomplete_fields = ("category", "task", "sprint", "milestone", "created_by")


# ─────────────────────────────────────────────────────────────────────────────
# WORKSPACE
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "is_active", "is_archived", "timezone", "quarter_label", "created_at")
    list_filter = ("is_active", "is_archived")
    search_fields = ("name", "slug", "owner__username", "owner__email")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at", "archived_at")
    ordering = ("name",)
    autocomplete_fields = ("owner",)
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "logo", "owner")}),
        (_("Configuration"), {"fields": ("timezone", "quarter_label", "is_active")}),
        (_("Archive"), {"fields": ("is_archived", "archived_at"), "classes": ("collapse",)}),
        (_("Horodatage"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(WorkspaceSettings)
class WorkspaceSettingsAdmin(admin.ModelAdmin):
    list_display = ("workspace", "default_sprint_duration_days", "ai_insights_enabled", "require_2fa")
    search_fields = ("workspace__name",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("workspace",)
    fieldsets = (
        (_("Workspace"), {"fields": ("workspace",)}),
        (_("Sprints"), {"fields": ("default_sprint_duration_days", "story_points_scale")}),
        (_("Notifications"), {"fields": (
            "notify_task_assigned",
            "notify_task_due_soon",
            "notify_blocked_task",
            "notify_pr_review",
            "due_soon_threshold_days",
        )}),
        (_("Intelligence Artificielle"), {"fields": (
            "ai_insights_enabled",
            "ai_risk_auto_detect",
            "ai_workload_suggestions",
        )}),
        (_("Accès & Sécurité"), {"fields": ("allow_guest_access", "require_2fa")}),
        (_("Apparence"), {"fields": ("primary_color", "logo_url")}),
    )

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "avatar_preview",
        "user",
        "workspace",
        "job_title",
        "seniority",
        "contract_type",
        "availability_percent",
        "cost_per_day",
        "billable_rate_per_day",
        "currency",
        "is_billable",
        "is_active",
        "joined_company_at",
    )
    list_display_links = ("avatar_preview", "user")
    list_filter = (
        "workspace",
        "seniority",
        "contract_type",
        "is_billable",
        "is_active",
        "currency",
        "joined_company_at",
    )
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "workspace__name",
        "job_title",
        "phone",
        "location",
    )
    autocomplete_fields = ("user", "workspace")
    readonly_fields = ("avatar_preview_large", "created_at", "updated_at")
    list_select_related = ("user", "workspace")
    ordering = ("workspace__name", "user__username")

    fieldsets = (
        ("Utilisateur & rattachement", {
            "fields": (
                "user",
                "workspace",
                "avatar_preview_large",
                "avatar",
            )
        }),
        ("Informations générales", {
            "fields": (
                "job_title",
                "seniority",
                "contract_type",
                "phone",
                "location",
                "joined_company_at",
            )
        }),
        ("Capacité & disponibilité", {
            "fields": (
                "capacity_hours_per_day",
                "capacity_hours_per_week",
                "availability_percent",
            )
        }),
        ("Coûts & facturation", {
            "fields": (
                "cost_per_day",
                "billable_rate_per_day",
                "currency",
                "is_billable",
            )
        }),
        ("Performance", {
            "fields": (
                "performance_score",
                "velocity_contribution",
            )
        }),
        ("Statut & méta", {
            "fields": (
                "is_active",
                "created_at",
                "updated_at",
            )
        }),
    )

    @admin.display(description="Avatar")
    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" style="width:36px;height:36px;border-radius:999px;object-fit:cover;border:1px solid #ddd;" />',
                obj.avatar.url
            )
        return "—"

    @admin.display(description="Aperçu avatar")
    def avatar_preview_large(self, obj):
        if obj.pk and obj.avatar:
            return format_html(
                '<img src="{}" style="width:72px;height:72px;border-radius:12px;object-fit:cover;border:1px solid #ddd;" />',
                obj.avatar.url
            )
        return "Aucun avatar"
# ─────────────────────────────────────────────────────────────────────────────
# ÉQUIPES & MEMBRES
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "workspace",
        "team_type",
        "lead",
        "velocity_current",
        "velocity_target",
        "is_active",
        "is_archived",
    )
    list_filter = ("team_type", "is_active", "is_archived", "workspace")
    search_fields = ("name", "workspace__name", "lead__username", "lead__email")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at", "archived_at")
    autocomplete_fields = ("workspace", "lead")
    inlines = (TeamMembershipInline,)
    fieldsets = (
        (None, {"fields": ("workspace", "name", "slug", "description", "team_type", "lead", "color")}),
        (_("Vélocité"), {"fields": ("velocity_target", "velocity_current")}),
        (_("État"), {"fields": ("is_active", "is_archived", "archived_at")}),
        (_("Horodatage"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "workspace",
        "team",
        "role",
        "status",
        "job_title",
        "capacity_points",
        "current_load_percent",
    )
    list_filter = ("role", "status", "workspace", "team")
    search_fields = ("user__username", "user__email", "job_title")
    autocomplete_fields = ("workspace", "team", "user")
    readonly_fields = ("created_at", "updated_at")


# ─────────────────────────────────────────────────────────────────────────────
# PROJETS
# ─────────────────────────────────────────────────────────────────────────────
@admin.register(ProjectCategory)
class ProjectCategoryAdmin(admin.ModelAdmin):

    list_display = (

        "name",
        "code",
        "is_billable",
        "budget_type",
        "color_badge",
    )
    list_filter = (
        "is_billable",
        "budget_type",
    )
    search_fields = (
        "name",
        "code",
    )
    prepopulated_fields = {"code": ("name",)}
    ordering = ("name",)
    fieldsets = (
        (
            "Informations générales",
            {
                "fields": (
                    "name",
                    "code",
                )
            },
        ),
        (
            "Configuration financière",
            {
                "fields": (
                    "is_billable",
                    "budget_type",
                )
            },
        ),
        (
            "Affichage",
            {
                "fields": ("color",)
          },
      ),
    )

    @admin.display(description="Couleur")
    def color_badge(self, obj):
        if not obj.color:
            return "-"
        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'

            'background:{};color:white;font-weight:600;">{}</span>',

            obj.color,

            obj.color,

        )
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "workspace",
        "team",
        "colored_status_col",
        "colored_priority_col",
        "progress_percent",
        "colored_health_col",
        "risk_score",
        "ai_risk_label",
        "target_date",
        "is_archived",
        'image',
    )
    list_filter = ("status", "priority", "health_status", "workspace", "team", "is_archived")
    search_fields = ("name", "slug", "code", "tech_stack", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at", "archived_at", "risk_score")
    autocomplete_fields = ("workspace",  "category", "team", "owner", "product_manager")
    inlines = (
        ProjectMemberInline,
        SprintInline,
        BoardColumnInline,
        ProjectLabelInline,
        ProjectEstimateLineInline,
    )
    fieldsets = (
        (None, {"fields": ("workspace", "team", "name", "slug", "code", "description", "tech_stack")}),
        (_("Responsables"), {"fields": ("owner", "product_manager")}),
        (_("Statut & Priorité"), {"fields": (
            "status",
            "priority",
            "health_status",
            "progress_percent",
            "category",
            "risk_score",
            "ai_risk_label",
            'image',
        )}),
        (_("Dates & Budget"), {"fields": ("start_date", "target_date", "delivered_at", "budget")}),
        (_("Divers"), {"fields": ("is_favorite", "is_archived", "archived_at")}),
        (_("Horodatage"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Statut"))
    def colored_status_col(self, obj):
        return colored_status(obj.status, STATUS_COLORS)

    @admin.display(description=_("Priorité"))
    def colored_priority_col(self, obj):
        return colored_status(obj.priority, PRIORITY_COLORS)

    @admin.display(description=_("Santé"))
    def colored_health_col(self, obj):
        return colored_status(obj.health_status, HEALTH_COLORS)


@admin.register(ProjectMember)
class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ("user", "project", "team", "role", "allocation_percent", "is_primary")
    list_filter = ("project", "team", "is_primary")
    search_fields = ("user__username", "user__email", "project__name", "role")
    autocomplete_fields = ("user", "project", "team")


@admin.register(ProjectLabel)
class ProjectLabelAdmin(admin.ModelAdmin):
    list_display = ("project", "label", "created_at")
    list_filter = ("label", "project__workspace")
    search_fields = ("project__name", "label__name")
    autocomplete_fields = ("project", "label")


# ─────────────────────────────────────────────────────────────────────────────
# COÛTS / BUDGET / REVENUS
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(ProjectBudget)
class ProjectBudgetAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "status_badge",
        "currency",
        "approved_budget",
        "estimated_total_cost_display",
        "expected_revenue_display",
        "estimated_margin_amount_display",
        "alert_threshold_percent",
        "approved_by",
        "approved_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("project__name", "project__code", "notes")
    autocomplete_fields = ("project", "approved_by")
    readonly_fields = (
        "estimated_total_cost_display",
        "expected_revenue_display",
        "estimated_margin_amount_display",
        "budget_consumption_percent_display",
        "created_at",
        "updated_at",
    )
    # inlines = (ProjectEstimateLineInline,)
    fieldsets = (
        ("Projet", {
            "fields": ("project", "status", "currency")
        }),
        ("Estimation des coûts", {
            "fields": (
                "estimated_labor_cost",
                "estimated_software_cost",
                "estimated_infra_cost",
                "estimated_subcontract_cost",
                "estimated_other_cost",
                "contingency_amount",
                "estimated_total_cost_display",
            )
        }),
        ("Revenu / marge", {
            "fields": (
                "target_margin_percent",
                "markup_percent",
                "planned_revenue",
                "expected_revenue_display",
                "estimated_margin_amount_display",
            )
        }),
        ("Budget validé / contrôle", {
            "fields": (
                "approved_budget",
                "budget_consumption_percent_display",
                "alert_threshold_percent",
            )
        }),
        ("Validation", {
            "fields": ("approved_by", "approved_at", "notes")
        }),
        ("Traçabilité", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )
    from django.contrib import admin
    from django.utils.html import format_html

    from project import models as dm

    @admin.register(dm.CostCategory)
    class CostCategoryAdmin(admin.ModelAdmin):
        list_display = (
            "name",
            "category_type",
            "color_preview",
            "description_short",
            "created_at",
        )
        list_filter = ("category_type",)
        search_fields = ("name", "description")
        ordering = ("name",)
        list_per_page = 25

        fieldsets = (
            ("Informations générales", {
                "fields": (
                    "name",
                    "category_type",
                    "description",
                    "color",
                )
            }),
            ("Métadonnées", {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            }),
        )
        readonly_fields = ("created_at", "updated_at")

        @admin.display(description="Couleur")
        def color_preview(self, obj):
            return format_html(
                '<span style="display:inline-flex;align-items:center;gap:8px;">'
                '<span style="width:16px;height:16px;border-radius:999px;display:inline-block;'
                'background:{};border:1px solid #ddd;"></span>'
                '<code>{}</code>'
                "</span>",
                obj.color or "#7C6FF7",
                obj.color or "-",
            )

        @admin.display(description="Description")
        def description_short(self, obj):
            if not obj.description:
                return "—"
            return obj.description[:60] + ("..." if len(obj.description) > 60 else "")

    @admin.register(dm.BillingRate)
    class BillingRateAdmin(admin.ModelAdmin):
        list_display = (
            "target_label",
            "worker_level",
            "unit",
            "cost_rate_amount",
            "sale_rate_amount",
            "currency",
            "margin_amount_display",
            "margin_percent_display",
            "is_internal_cost",
            "is_billable_rate",
            "is_currently_active_badge",
            "valid_from",
            "valid_to",
            "is_archived",
        )
        list_filter = (
            "worker_level",
            "unit",
            "currency",
            "is_internal_cost",
            "is_billable_rate",
            "is_archived",
            "valid_from",
            "valid_to",
        )
        search_fields = (
            "name",
            "user__username",
            "user__first_name",
            "user__last_name",
            "user__email",
            "team__name",
        )
        autocomplete_fields = ("user", "team")
        ordering = ("-valid_from", "-id")
        list_per_page = 25
        actions = ("archive_selected_rates", "unarchive_selected_rates")

        fieldsets = (
            ("Cible du tarif", {
                "fields": (
                    "user",
                    "team",
                    "name",
                    "worker_level",
                )
            }),
            ("Tarification", {
                "fields": (
                    "unit",
                    "cost_rate_amount",
                    "sale_rate_amount",
                    "currency",
                )
            }),
            ("Validité", {
                "fields": (
                    "valid_from",
                    "valid_to",
                )
            }),
            ("Options", {
                "fields": (
                    "is_internal_cost",
                    "is_billable_rate",
                    "is_archived",
                    "archived_at",
                )
            }),
            ("Lecture seule", {
                "fields": (
                    "margin_amount_display",
                    "margin_percent_display",
                    "is_currently_active_badge",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            }),
        )

        readonly_fields = (
            "margin_amount_display",
            "margin_percent_display",
            "is_currently_active_badge",
            "archived_at",
            "created_at",
            "updated_at",
        )

        @admin.display(description="Marge")
        def margin_amount_display(self, obj):
            return f"{obj.margin_amount:.2f} {obj.currency}"

        @admin.display(description="Marge %")
        def margin_percent_display(self, obj):
            return f"{obj.margin_percent:.2f}%"

        @admin.display(description="Actif")
        def is_currently_active_badge(self, obj):
            if obj.is_currently_active and not obj.is_archived:
                color = "#16a34a"
                label = "Actif"
            elif obj.is_archived:
                color = "#dc2626"
                label = "Archivé"
            else:
                color = "#d97706"
                label = "Inactif"

            return format_html(
                '<span style="padding:4px 10px;border-radius:999px;'
                'background:{}22;color:{};font-weight:600;">{}</span>',
                color,
                color,
                label,
            )

        @admin.action(description="Archiver les tarifs sélectionnés")
        def archive_selected_rates(self, request, queryset):
            count = 0
            for obj in queryset:
                if hasattr(obj, "archive") and not obj.is_archived:
                    obj.archive()
                    count += 1
            self.message_user(request, f"{count} tarif(s) archivé(s).")

        @admin.action(description="Désarchiver les tarifs sélectionnés")
        def unarchive_selected_rates(self, request, queryset):
            updated = queryset.update(is_archived=False, archived_at=None)
            self.message_user(request, f"{updated} tarif(s) désarchivé(s).")
    @admin.display(description="Statut")
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)

    @admin.display(description="Coût total estimé")
    def estimated_total_cost_display(self, obj):
        return f"{obj.total_estimated_cost} {obj.currency}"

    @admin.display(description="Revenu attendu")
    def expected_revenue_display(self, obj):
        return f"{obj.expected_revenue_amount} {obj.currency}"

    @admin.display(description="Marge estimée")
    def estimated_margin_amount_display(self, obj):
        return f"{obj.estimated_margin_amount} {obj.currency} ({obj.estimated_margin_percent:.2f}%)"

    @admin.display(description="Consommation budget")
    def budget_consumption_percent_display(self, obj):
        return f"{obj.budget_consumption_percent:.2f}%"


@admin.register(ProjectEstimateLine)
class ProjectEstimateLineAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "label",
        "category",
        "source_type",
        "quantity",
        "cost_unit_amount",
        "cost_amount",
        "sale_unit_amount",
        "sale_amount",
        "markup_percent",
        "created_by",
    )
    list_filter = ("source_type", "category", "project")
    search_fields = ("label", "description", "project__name")
    autocomplete_fields = ("project", "category", "task", "sprint", "milestone", "created_by")
    readonly_fields = ("cost_amount", "sale_unit_amount", "sale_amount", "created_at", "updated_at")
    ordering = ("project", "label")
    fieldsets = (
        ("Projet", {
            "fields": ("project", "category", "source_type", "task", "sprint", "milestone")
        }),
        ("Ligne", {
            "fields": ("label", "description", "quantity", "markup_percent")
        }),
        ("Montants", {
            "fields": (
                "cost_unit_amount",
                "cost_amount",
                "sale_unit_amount",
                "sale_amount",
            )
        }),
        ("Traçabilité", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(ProjectExpense)
class ProjectExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "title",
        "category",
        "status_badge",
        "amount",
        "currency",
        "expense_date",
        "vendor",
        "validated_by",
        "validated_at",
    )
    list_filter = ("status", "category", "currency", "expense_date")
    search_fields = ("title", "description", "vendor", "reference", "project__name")
    autocomplete_fields = (
        "project",
        "category",
        "task",
        "sprint",
        "milestone",
        "created_by",
        "validated_by",
    )
    date_hierarchy = "expense_date"
    ordering = ("-expense_date", "-created_at")
    readonly_fields = ("created_at", "updated_at", "validated_at")

    fieldsets = (
        ("Projet", {
            "fields": ("project", "category", "task", "sprint", "milestone")
        }),
        ("Dépense", {
            "fields": (
                "title",
                "description",
                "status",
                "expense_date",
                "amount",
                "currency",
                "vendor",
                "reference",
            )
        }),
        ("Validation", {
            "fields": ("created_by", "validated_by", "validated_at")
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Statut")
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)


@admin.register(ProjectRevenue)
class ProjectRevenueAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "title",
        "revenue_type",
        "amount",
        "currency",
        "expected_date",
        "received_date",

    )
    list_filter = ("revenue_type", "currency")
    search_fields = ("title", "notes", "project__name")
    autocomplete_fields = ("project",)
    date_hierarchy = "expected_date"
    ordering = ("expected_date", "title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TimesheetCostSnapshot)
class TimesheetCostSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "timesheet_entry",
        "billing_rate",
        "rate_unit",
        "rate_amount",
        "computed_cost",
        "currency",
        "created_at",
    )
    list_filter = ("rate_unit", "currency")
    search_fields = (
        "timesheet_entry__user__username",
        "timesheet_entry__project__name",
    )
    autocomplete_fields = ("timesheet_entry", "billing_rate")
    readonly_fields = ("created_at", "updated_at")


# ─────────────────────────────────────────────────────────────────────────────
# SPRINTS
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "status_badge",
        "start_date",
        "end_date",
        "remaining_days_col",
        "completed_story_points",
        "total_story_points",
        "is_archived",
    )
    list_filter = ("status", "workspace", "project", "team", "is_archived")
    search_fields = ("name", "project__name")
    readonly_fields = ("created_at", "updated_at", "remaining_days", "archived_at")
    autocomplete_fields = ("workspace", "project", "team")
    inlines = (SprintMetricInline,)
    fieldsets = (
        (None, {"fields": ("workspace", "project", "team", "name", "number", "goal")}),
        (_("Planning"), {"fields": ("status", "start_date", "end_date", "remaining_days")}),
        (_("Points"), {"fields": (
            "velocity_target",
            "velocity_completed",
            "total_story_points",
            "completed_story_points",
            "remaining_story_points",
        )}),
        (_("Archive"), {"fields": ("is_archived", "archived_at"), "classes": ("collapse",)}),
        (_("Horodatage"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)

    @admin.display(description=_("Jours restants"))
    def remaining_days_col(self, obj):
        d = obj.remaining_days
        color = "#E8453C" if d < 0 else "#E8950A" if d <= 3 else "#34A853"
        return format_html('<b style="color:{}">{} j</b>', color, d)


@admin.register(SprintMetric)
class SprintMetricAdmin(admin.ModelAdmin):
    list_display = (
        "sprint",
        "metric_date",
        "planned_remaining_points",
        "actual_remaining_points",
        "completed_tasks",
    )
    list_filter = ("sprint__project",)
    search_fields = ("sprint__name",)
    date_hierarchy = "metric_date"
    autocomplete_fields = ("sprint",)


@admin.register(SprintReview)
class SprintReviewAdmin(admin.ModelAdmin):
    list_display = ("sprint", "held_at", "facilitator", "velocity_actual")
    search_fields = ("sprint__name",)
    autocomplete_fields = ("sprint", "facilitator")
    filter_horizontal = ("accepted_stories",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(SprintRetrospective)
class SprintRetrospectiveAdmin(admin.ModelAdmin):
    list_display = ("sprint", "held_at", "facilitator", "mood_score")
    search_fields = ("sprint__name",)
    autocomplete_fields = ("sprint", "facilitator")
    readonly_fields = ("created_at", "updated_at")


# ─────────────────────────────────────────────────────────────────────────────
# BACKLOG & TÂCHES
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(BacklogItem)
class BacklogItemAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "sprint", "item_type", "rank", "story_points", "is_archived")
    list_filter = ("item_type", "project", "sprint", "is_archived")
    search_fields = ("title", "description")
    readonly_fields = ("created_at", "updated_at", "archived_at")
    autocomplete_fields = ("workspace", "project", "sprint", "parent", "reporter")
    fieldsets = (
        (None, {"fields": ("workspace", "project", "sprint", "parent", "title", "description")}),
        (_("Backlog"), {"fields": ("item_type", "rank", "story_points", "acceptance_criteria", "reporter")}),
        (_("Archive"), {"fields": ("is_archived", "archived_at"), "classes": ("collapse",)}),
    )


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "project",
        "sprint",
        "status_badge",
        "priority_badge",
        "assignee",
        "progress_percent",
        "due_date",
        "is_flagged",
        "is_archived",
    )
    list_filter = ("status", "priority", "is_flagged", "is_archived", "project", "sprint")
    search_fields = ("title", "description", "assignee__username", "reporter__username")
    readonly_fields = ("created_at", "updated_at", "completed_at", "started_at", "archived_at")
    autocomplete_fields = ("workspace", "project", "sprint", "backlog_item", "parent", "reporter", "assignee")
    inlines = (
        TaskAssignmentInline,
        TaskCommentInline,
        TaskAttachmentInline,
        TaskLabelInline,
        TaskChecklistInline,
        TaskDependencyInline,
    )
    fieldsets = (
        (None, {"fields": ("workspace", "project", "sprint", "backlog_item", "parent", "title", "description")}),
        (_("Statut & Priorité"), {"fields": ("status", "priority", "progress_percent", "risk_score", "is_flagged")}),
        (_("Assignation"), {"fields": ("reporter", "assignee")}),
        (_("Temps"), {"fields": ("estimate_hours", "spent_hours", "due_date", "started_at", "completed_at")}),
        (_("Méta"), {"fields": ("position", "comments_count", "attachments_count")}),
        (_("Archive"), {"fields": ("is_archived", "archived_at"), "classes": ("collapse",)}),
        (_("Horodatage"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)

    @admin.display(description=_("Priorité"))
    def priority_badge(self, obj):
        return colored_status(obj.priority, PRIORITY_COLORS)


@admin.register(TaskAssignment)
class TaskAssignmentAdmin(admin.ModelAdmin):
    list_display = ("task", "user", "assigned_by", "allocation_percent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("task__title", "user__username")
    autocomplete_fields = ("task", "user", "assigned_by")


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("pk", "task", "author", "is_internal", "created_at", "edited_at")
    list_filter = ("is_internal",)
    search_fields = ("body", "task__title", "author__username")
    readonly_fields = ("created_at", "updated_at", "edited_at")
    autocomplete_fields = ("task", "author")
    inlines = (ReactionInline,)


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ("name", "task", "mime_type", "size", "uploaded_by", "created_at")
    search_fields = ("name", "task__title")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("task", "uploaded_by")


@admin.register(TaskChecklist)
class TaskChecklistAdmin(admin.ModelAdmin):
    list_display = ("title", "task", "position")
    search_fields = ("title", "task__title")
    autocomplete_fields = ("task",)
    inlines = (ChecklistItemInline,)


@admin.register(ChecklistItem)
class ChecklistItemAdmin(admin.ModelAdmin):
    list_display = ("text", "checklist", "is_checked", "checked_by", "position", "checked_at")
    list_filter = ("is_checked",)
    search_fields = ("text", "checklist__title", "checklist__task__title")
    autocomplete_fields = ("checklist", "checked_by")
    readonly_fields = ("created_at", "updated_at", "checked_at")


@admin.register(TaskDependency)
class TaskDependencyAdmin(admin.ModelAdmin):
    list_display = ("from_task", "dependency_type", "to_task", "created_by", "created_at")
    list_filter = ("dependency_type",)
    search_fields = ("from_task__title", "to_task__title")
    autocomplete_fields = ("from_task", "to_task", "created_by")


# ─────────────────────────────────────────────────────────────────────────────
# LABELS
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("colored_name", "workspace", "description")
    search_fields = ("name", "workspace__name")
    list_filter = ("workspace",)
    autocomplete_fields = ("workspace",)

    @admin.display(description=_("Étiquette"))
    def colored_name(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;border-radius:12px;">{}</span>',
            obj.color,
            obj.name,
        )


@admin.register(TaskLabel)
class TaskLabelAdmin(admin.ModelAdmin):
    list_display = ("task", "label", "added_by", "created_at")
    list_filter = ("label", "task__project")
    search_fields = ("task__title", "label__name")
    autocomplete_fields = ("task", "label", "added_by")


# ─────────────────────────────────────────────────────────────────────────────
# JALONS & RELEASES
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "status_badge", "due_date", "progress_percent", "owner", "is_archived")
    list_filter = ("status", "project", "is_archived")
    search_fields = ("name", "project__name")
    autocomplete_fields = ("workspace", "project", "owner")
    readonly_fields = ("created_at", "updated_at", "archived_at")
    inlines = (MilestoneTaskInline,)

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)


@admin.register(MilestoneTask)
class MilestoneTaskAdmin(admin.ModelAdmin):
    list_display = ("milestone", "task", "created_at")
    search_fields = ("milestone__name", "task__title")
    autocomplete_fields = ("milestone", "task")


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "tag", "status_badge", "release_date", "is_archived")
    list_filter = ("status", "project", "is_archived")
    search_fields = ("name", "tag", "project__name")
    autocomplete_fields = ("workspace", "project")
    readonly_fields = ("created_at", "updated_at", "released_at", "archived_at")
    filter_horizontal = ("tasks", "sprints")

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)


# ─────────────────────────────────────────────────────────────────────────────
# ROADMAP
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Roadmap)
class RoadmapAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "start_date", "end_date", "is_public", "is_archived")
    list_filter = ("is_public", "is_archived", "workspace")
    search_fields = ("name",)
    autocomplete_fields = ("workspace", "owner")
    readonly_fields = ("created_at", "updated_at", "archived_at")
    inlines = (RoadmapItemInline,)


@admin.register(RoadmapItem)
class RoadmapItemAdmin(admin.ModelAdmin):
    list_display = ("title", "roadmap", "status", "start_date", "end_date", "row")
    list_filter = ("status", "roadmap__workspace")
    search_fields = ("title", "roadmap__name")
    autocomplete_fields = ("roadmap", "project", "milestone")


# ─────────────────────────────────────────────────────────────────────────────
# BOARD
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(BoardColumn)
class BoardColumnAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "mapped_status", "position", "wip_limit", "is_done_column")
    list_filter = ("is_done_column", "project")
    search_fields = ("name", "project__name")
    autocomplete_fields = ("project",)


# ─────────────────────────────────────────────────────────────────────────────
# PULL REQUESTS
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(PullRequest)
class PullRequestAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "project",
        "repository",
        "branch_name",
        "status_badge",
        "author",
        "opened_at",
        "merged_at",
    )
    list_filter = ("status", "project", "workspace")
    search_fields = ("title", "branch_name", "repository", "external_id")
    readonly_fields = ("created_at", "updated_at", "opened_at", "merged_at")
    autocomplete_fields = ("workspace", "project", "task", "author")

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)


# ─────────────────────────────────────────────────────────────────────────────
# RISQUES
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Risk)
class RiskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "project",
        "severity_badge",
        "probability",
        "status_badge",
        "impact_score",
        "owner",
        "due_date",
        "is_archived",
    )
    list_filter = ("severity", "probability", "status", "project", "workspace")
    search_fields = ("title", "description")
    autocomplete_fields = ("workspace", "project", "task", "owner")
    readonly_fields = ("created_at", "updated_at", "escalated_at", "archived_at")
    fieldsets = (
        (None, {"fields": ("workspace", "project", "task", "title", "description")}),
        (_("Évaluation"), {"fields": ("severity", "probability", "impact_score", "status")}),
        (_("Plan de mitigation"), {"fields": ("mitigation_plan", "due_date", "escalated_at")}),
        (_("Responsable"), {"fields": ("owner",)}),
        (_("Archive"), {"fields": ("is_archived", "archived_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Sévérité"))
    def severity_badge(self, obj):
        return colored_status(obj.severity, SEVERITY_COLORS)

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)


# ─────────────────────────────────────────────────────────────────────────────
# IA
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(AInsight)
class AInsightAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "workspace",
        "insight_type",
        "severity_badge",
        "score",
        "is_read",
        "is_dismissed",
        "detected_at",
    )
    list_filter = ("insight_type", "severity", "is_read", "is_dismissed", "workspace")
    search_fields = ("title", "summary")
    readonly_fields = ("created_at", "updated_at", "detected_at")
    autocomplete_fields = ("workspace", "project", "sprint", "task")
    fieldsets = (
        (None, {"fields": ("workspace", "project", "sprint", "task")}),
        (_("Contenu"), {"fields": ("insight_type", "severity", "title", "summary", "recommendation", "score")}),
        (_("État"), {"fields": ("is_read", "is_dismissed", "detected_at")}),
    )

    @admin.display(description=_("Sévérité"))
    def severity_badge(self, obj):
        return colored_status(obj.severity, SEVERITY_COLORS)


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS & ACTIVITÉ
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "workspace", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "workspace")
    search_fields = ("title", "recipient__username", "body")
    readonly_fields = ("created_at", "updated_at", "read_at")
    autocomplete_fields = ("recipient", "workspace")

    @admin.action(description=_("Marquer comme lues"))
    def mark_as_read(self, request, queryset):
        from django.utils import timezone
        queryset.update(is_read=True, read_at=timezone.now())

    actions = ("mark_as_read",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "actor", "activity_type", "project", "created_at")
    list_filter = ("activity_type", "workspace", "project")
    search_fields = ("title", "description", "actor__username")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("workspace", "actor", "project", "task", "sprint")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGERIE
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(DirectChannel)
class DirectChannelAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "is_private", "members_count", "created_at")
    list_filter = ("is_private", "workspace")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("workspace",)
    inlines = (ChannelMembershipInline,)

    @admin.display(description=_("Membres"))
    def members_count(self, obj):
        return obj.memberships.count()


@admin.register(ChannelMembership)
class ChannelMembershipAdmin(admin.ModelAdmin):
    list_display = ("channel", "user", "joined_at", "is_muted")
    list_filter = ("is_muted", "channel__workspace")
    search_fields = ("channel__name", "user__username", "user__email")
    autocomplete_fields = ("channel", "user")
    readonly_fields = ("created_at", "updated_at", "joined_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("author", "channel", "short_body", "is_edited", "created_at")
    list_filter = ("channel", "is_edited")
    search_fields = ("body", "author__username", "channel__name")
    readonly_fields = ("created_at", "updated_at", "edited_at")
    autocomplete_fields = ("channel", "author", "parent")
    inlines = (MessageAttachmentInline,)

    @admin.display(description=_("Message"))
    def short_body(self, obj):
        return obj.body[:80] + "…" if len(obj.body) > 80 else obj.body


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    list_display = ("name", "message", "mime_type", "size", "created_at")
    search_fields = ("name", "message__body")
    autocomplete_fields = ("message",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ("user", "emoji", "task_comment", "message", "created_at")
    list_filter = ("emoji",)
    search_fields = ("user__username",)
    autocomplete_fields = ("user", "task_comment", "message")


# ─────────────────────────────────────────────────────────────────────────────
# TIMESHEET
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(TimesheetEntry)
class TimesheetEntryAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "project",
        "task",
        "entry_date",
        "hours",
        "is_billable",
        "approved_by",
        "approved_at",
    )
    list_filter = ("is_billable", "project", "workspace")
    search_fields = ("user__username", "description")
    date_hierarchy = "entry_date"
    readonly_fields = ("created_at", "updated_at", "approved_at")
    autocomplete_fields = ("user", "workspace", "project", "task", "approved_by")

    @admin.action(description=_("Approuver les entrées sélectionnées"))
    def approve_entries(self, request, queryset):
        from django.utils import timezone
        queryset.update(approved_by=request.user, approved_at=timezone.now())

    actions = ("approve_entries",)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(DashboardSnapshot)
class DashboardSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "workspace",
        "snapshot_date",
        "active_projects",
        "completed_tasks",
        "blocked_tasks",
        "active_members",
        "velocity_score",
        "portfolio_health_percent",
    )
    list_filter = ("workspace",)
    date_hierarchy = "snapshot_date"
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("workspace",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PRÉFÉRENCES UTILISATEUR
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "workspace",
        "theme",
        "default_view",
        "show_ai_panel",
        "notifications_enabled",
        "sidebar_collapsed",
    )
    list_filter = ("theme", "workspace")
    search_fields = ("user__username",)
    autocomplete_fields = ("user", "workspace")
    readonly_fields = ("created_at", "updated_at")


# ─────────────────────────────────────────────────────────────────────────────
# INVITATIONS
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(WorkspaceInvitation)
class WorkspaceInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "workspace", "role", "team", "status_badge", "invited_by", "expires_at", "accepted_at")
    list_filter = ("status", "role", "workspace")
    search_fields = ("email", "workspace__name")
    readonly_fields = ("token", "created_at", "updated_at", "accepted_at")
    autocomplete_fields = ("workspace", "team", "invited_by")

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)

    @admin.action(description=_("Révoquer les invitations sélectionnées"))
    def revoke_invitations(self, request, queryset):
        queryset.update(status="REVOKED")

    actions = ("revoke_invitations",)


# ─────────────────────────────────────────────────────────────────────────────
# INTÉGRATIONS & WEBHOOKS
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ("provider_badge", "workspace", "name", "status_badge", "last_synced_at", "installed_by")
    list_filter = ("provider", "status", "workspace")
    search_fields = ("name", "workspace__name")
    readonly_fields = (
        "created_at",
        "updated_at",
        "access_token_encrypted",
        "refresh_token_encrypted",
        "last_synced_at",
        "error_message",
    )
    autocomplete_fields = ("workspace", "installed_by")
    fieldsets = (
        (None, {"fields": ("workspace", "provider", "name", "status", "installed_by")}),
        (_("Configuration"), {"fields": ("config",)}),
        (_("Tokens (lecture seule)"), {
            "fields": ("access_token_encrypted", "refresh_token_encrypted", "token_expires_at"),
            "classes": ("collapse",),
        }),
        (_("Synchronisation"), {"fields": ("last_synced_at", "error_message")}),
    )

    @admin.display(description=_("Provider"))
    def provider_badge(self, obj):
        colors = {
            "GITHUB": "#24292E",
            "GITLAB": "#FC6D26",
            "SLACK": "#4A154B",
            "JIRA": "#0052CC",
            "FIGMA": "#F24E1E",
            "SENTRY": "#362D59",
            "DATADOG": "#632CA6",
            "LINEAR": "#111827",
        }
        return colored_status(obj.provider, colors)

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)


@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ("url", "workspace", "is_active", "failure_count", "last_triggered_at")
    list_filter = ("is_active", "workspace")
    search_fields = ("url", "workspace__name")
    readonly_fields = ("created_at", "updated_at", "last_triggered_at")
    autocomplete_fields = ("workspace",)

    @admin.action(description=_("Réinitialiser le compteur d'erreurs"))
    def reset_failure_count(self, request, queryset):
        queryset.update(failure_count=0)

    actions = ("reset_failure_count",)


# ─────────────────────────────────────────────────────────────────────────────
# CLÉS API
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = (
        "key_prefix",
        "name",
        "workspace",
        "scope",
        "is_active",
        "last_used_at",
        "expires_at",
        "created_by",
    )
    list_filter = ("scope", "is_active", "workspace")
    search_fields = ("name", "key_prefix", "workspace__name")
    readonly_fields = ("key_hash", "key_prefix", "created_at", "updated_at", "last_used_at")
    autocomplete_fields = ("workspace", "created_by")

    @admin.action(description=_("Désactiver les clés sélectionnées"))
    def deactivate_keys(self, request, queryset):
        queryset.update(is_active=False)

    actions = ("deactivate_keys",)


# ─────────────────────────────────────────────────────────────────────────────
# OKR
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Objective)
class ObjectiveAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "workspace",
        "team",
        "level",
        "status_badge",
        "progress_percent",
        "quarter_label",
        "end_date",
        "is_archived",
    )
    list_filter = ("level", "status", "workspace", "team", "is_archived")
    search_fields = ("title", "description")
    autocomplete_fields = ("workspace", "team", "owner")
    readonly_fields = ("created_at", "updated_at", "archived_at")
    inlines = (KeyResultInline,)
    fieldsets = (
        (None, {"fields": ("workspace", "team", "owner", "title", "description")}),
        (_("Statut"), {"fields": ("level", "status", "progress_percent")}),
        (_("Période"), {"fields": ("start_date", "end_date", "quarter_label")}),
        (_("Archive"), {"fields": ("is_archived", "archived_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Statut"))
    def status_badge(self, obj):
        return colored_status(obj.status, STATUS_COLORS)


@admin.register(KeyResult)
class KeyResultAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "objective",
        "result_type",
        "current_value",
        "target_value",
        "unit",
        "progress_col",
        "owner",
    )
    list_filter = ("result_type", "objective__workspace")
    search_fields = ("title", "objective__title")
    autocomplete_fields = ("objective", "owner")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description=_("Avancement"))
    def progress_col(self, obj):
        p = obj.progress_percent
        color = "#34A853" if p >= 70 else "#E8950A" if p >= 40 else "#E8453C"
        return format_html(
            '<div style="width:100px;background:#eee;border-radius:4px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:6px;">'
            '<div style="width:{}%;background:{};height:8px;"></div></div>'
            '<span style="font-size:11px;font-weight:600;color:{};">{} %</span>',
            p,
            color,
            color,
            p,
        )